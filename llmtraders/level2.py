"""Level 2: a market of 4 LLM traders and ZI bots; for now the K0 calibration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .agents import Agent, LLMTrader, ZIBot
from .analysis import _f
from .bayes import PRIOR_HIGH, value_from_p
from .chat import MessageBank
from .core import N_PERIODS, ROOT
from .llm.client import LLMClient
from .llm.config import get_model
from .llm.log import JsonlLogger
from .market import SessionConfig, run_session
from .prompts import PromptConfig
from .results import RESULTS, make_client, read_jsonl

CONFIG = ROOT / "configs" / "level2.yaml"
ZI = "zi"
# Before the first trade the reference price is the prior value, as in run_session.
PRIOR_VALUE = value_from_p(PRIOR_HIGH)


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def zi_ids(n: int) -> list[str]:
    # ZI orders are seeded by the bot's id, so the first bot keeps the id of the
    # one-bot market and every step of the ladder only adds bots.
    return [ZI] + [f"{ZI}{j}" for j in range(2, n + 1)]


def is_zi(agent_id: str) -> bool:
    return agent_id.startswith(ZI)


def market(
    cfg: dict[str, Any],
    model: str,
    client: LLMClient,
    seed: int,
    ticker: str,
    n_zi: int,
) -> list[Agent]:
    mcfg = get_model(model)
    pcfg = PromptConfig(ticker=ticker)
    agents: list[Agent] = [
        LLMTrader(
            agent_id=f"llm{i}",
            cash=float(t["cash"]),
            shares=int(t["shares"]),
            model=mcfg,
            client=client,
            prompt_cfg=pcfg,
        )
        for i, t in enumerate(cfg["traders"])
    ]
    zi = cfg["zi"]
    for agent_id in zi_ids(n_zi):
        bot = ZIBot(
            agent_id=agent_id,
            cash=float(zi["cash"]),
            shares=int(zi["shares"]),
            seed=seed,
        )
        agents.append(bot)
    return agents


def calibrate(
    model: str, *, out_dir: Path | None = None, cache_path: Path | None = None
) -> Path:
    cfg = load_config()
    cal = cfg["calibration"]
    bank = MessageBank.load()
    default_out = RESULTS / "level2" / "calibration" / cfg["version"] / model
    out = Path(out_dir) if out_dir else default_out
    for n_zi in cal["zi_steps"]:
        step = out / f"zi{n_zi}"
        client = make_client(step, cache_path)
        (step / "sessions.jsonl").unlink(missing_ok=True)
        logger = JsonlLogger(step / "sessions.jsonl")
        tags = {"model": model, "version": cfg["version"], "zi_bots": n_zi}
        for value, seeds in cal["seeds"].items():
            for seed in seeds:
                run_session(
                    SessionConfig(seed=seed, value=float(value)),
                    market(cfg, model, client, seed, bank.ticker, n_zi),
                    bank,
                    logger=logger,
                    session_id=f"v{value}-s{seed}",
                    tags=tags,
                )
    write_calibration(out, cfg, model)
    return out


def periods_table(path: Path) -> pd.DataFrame:
    """One row per session and period, from sessions.jsonl."""
    rows, news = [], {}
    first_news = SessionConfig.signal_periods[0]
    for r in read_jsonl(path):
        if r["kind"] == "session":
            news[r["session"]] = r["signals"][str(first_news)]
            continue
        llm = [d for k, d in r["decisions"].items() if not is_zi(k)]
        llm_volume = sum(abs(q) for k, q in r["fills"].items() if not is_zi(k))
        rows.append(
            {
                "zi_bots": r["zi_bots"],
                "session": r["session"],
                "value": r["value"],
                "seed": r["seed"],
                "period": r["period"],
                "price": r["price"],
                "rational": r["rational"],
                "volume": r["volume"],
                "llm_volume": llm_volume,
                "llm_calls": len(llm),
                "llm_holds": sum(d["side"] == "hold" for d in llm),
                "llm_invalid": sum(not d["valid"] for d in llm),
            }
        )
    p = pd.DataFrame(rows).sort_values(["zi_bots", "session", "period"])
    p["news"] = p["session"].map(news)
    p["traded"] = p["volume"] > 0
    p["llm_traded"] = p["llm_volume"] > 0
    p["gap"] = (p["price"] - p["rational"]).where(p["traded"])
    p["abs_gap"] = p["gap"].abs()
    # The price a trader sees in a period without a trade: the last one, else the prior.
    last = p.groupby(["zi_bots", "session"])["price"].ffill()
    p["level"] = last.fillna(PRIOR_VALUE)
    return p.reset_index(drop=True)


def news_moves(p: pd.DataFrame) -> pd.DataFrame:
    """Per session: price level before the second official news minus before the first."""
    first, second = SessionConfig.signal_periods[:2]
    keys = ["zi_bots", "session"]
    lvl = p.set_index([*keys, "period"])["level"]
    move = lvl.xs(second - 1, level="period") - lvl.xs(first - 1, level="period")
    out = move.rename("news_move").reset_index()
    news = p.groupby(keys)["news"].first().reset_index()
    out = out.merge(news, on=keys)
    expected = np.where(out["news"] == "good", 1, -1)
    direction = np.sign(out["news_move"])
    out["news_follow"] = np.select(
        [direction == 0, direction == expected], ["flat", "with"], "against"
    )
    return out


def sessions_table(p: pd.DataFrame) -> pd.DataFrame:
    keys = ["zi_bots", "session", "value", "seed"]
    s = p.groupby(keys, as_index=False).agg(
        llm_traded=("llm_traded", "sum"),
        traded=("traded", "sum"),
        volume=("volume", "sum"),
        llm_volume=("llm_volume", "sum"),
        median_abs_gap=("abs_gap", "median"),
        llm_calls=("llm_calls", "sum"),
        llm_holds=("llm_holds", "sum"),
        invalid=("llm_invalid", "sum"),
    )
    # A traded share has two sides; 0.5 means the LLM traders were always one side and
    # never both, 0 that only ZI bots traded.
    s["llm_side_share"] = s["llm_volume"] / (2 * s["volume"].where(s["volume"] > 0))
    s["hold_share"] = s["llm_holds"] / s["llm_calls"]
    return s.merge(news_moves(p), on=["zi_bots", "session"])


def step_row(p: pd.DataFrame, s: pd.DataFrame, cal: dict[str, Any]) -> dict[str, Any]:
    k = cal["min_llm_traded_periods"]
    enough = int((s["llm_traded"] >= k).sum())
    median = p["abs_gap"].median()
    follow = s["news_follow"].value_counts()
    return {
        "zi_bots": int(s["zi_bots"].iloc[0]),
        "sessions": len(s),
        "turnover_ok": enough,
        "turnover_pass": enough > len(s) / 2,
        "mean_llm_traded": s["llm_traded"].mean(),
        # Trades between ZI bots only: price noise that says nothing of the LLM orders.
        "zi_only_periods": int((p["traded"] & ~p["llm_traded"]).sum()),
        "median_abs_gap": median,
        # NaN when nothing traded: the comparison is False, so the step fails.
        "gap_pass": bool(median <= cal["max_median_deviation"]),
        "news_with": int(follow.get("with", 0)),
        "news_flat": int(follow.get("flat", 0)),
        "news_against": int(follow.get("against", 0)),
    }


def choose(ladder: pd.DataFrame) -> tuple[int, bool]:
    """The smallest step that passes both criteria; else the step where the LLM traders
    trade most (among those that pass the price criterion, if any), fewer bots on ties."""
    passed = ladder[ladder["turnover_pass"] & ladder["gap_pass"]]
    if len(passed):
        return int(passed["zi_bots"].min()), True
    # Not simply the last step: extra ZI bots may trade with each other and add
    # noise to the price without more trades of the LLM traders.
    pool = ladder[ladder["gap_pass"]]
    if not len(pool):
        pool = ladder
    ranked = pool.sort_values(["mean_llm_traded", "zi_bots"], ascending=[False, True])
    return int(ranked["zi_bots"].iloc[0]), False


def _step_lines(p: pd.DataFrame, s: pd.DataFrame) -> list[str]:
    header = (
        "| session | news P4 | LLM traded periods | traded periods | volume "
        "| LLM side share | median abs gap | LLM hold share | invalid | price after P4 news |"
    )
    lines = [header, "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in s.iterrows():
        move = f"{r['news_move']:+.1f} ({r['news_follow']})"
        lines.append(
            f"| {r['session']} | {r['news']} | {r['llm_traded']} | {r['traded']} | "
            f"{r['volume']} | {_f(r['llm_side_share'])} | {_f(r['median_abs_gap'], 1)} | "
            f"{_f(r['hold_share'])} | {r['invalid']} | {move} |"
        )
    by_period = p.groupby("period").agg(
        llm_traded=("llm_traded", "sum"), gap=("gap", "median")
    )
    lines += [
        "",
        "| period | sessions where an LLM traded | median gap |",
        "|---|---|---|",
    ]
    for period, r in by_period.iterrows():
        n = int(r["llm_traded"])
        lines.append(f"| {period} | {n} of {len(s)} | {_f(r['gap'], 1)} |")
    return lines


def write_calibration(out: Path, cfg: dict[str, Any], model: str) -> tuple[int, bool]:
    cal = cfg["calibration"]
    tables = []
    for n_zi in cal["zi_steps"]:
        p = periods_table(out / f"zi{n_zi}" / "sessions.jsonl")
        tables.append((p, sessions_table(p)))
    sessions = pd.concat([s for _, s in tables], ignore_index=True)
    sessions.to_csv(out / "calibration.csv", index=False)
    ladder = pd.DataFrame([step_row(p, s, cal) for p, s in tables])
    chosen, passed = choose(ladder)

    traders = ", ".join(f"{t['cash']}+{t['shares']}" for t in cfg["traders"])
    zi = cfg["zi"]
    k = cal["min_llm_traded_periods"]
    first, second = SessionConfig.signal_periods[:2]
    header = (
        f"| ZI bots | LLM trades in >= {k} of {N_PERIODS} periods "
        "| mean LLM traded periods | median abs gap | pass | periods with ZI-only trades "
        f"| price after P{first} news: with / flat / against |"
    )
    lines = [
        f"# Level 2 calibration (K0): {model}, {cfg['version']}",
        "",
        f"4 LLM traders (cash+shares: {traders}) and n ZI bots ({zi['cash']}+{zi['shares']}",
        "each), no manipulator. gap = price - rational price, over traded periods only.",
        f"Price after news: price level in P{second - 1} minus P{first - 1} (last trade",
        f"price, else {PRIOR_VALUE:.0f}), compared with the direction of the official",
        f"news in P{first}.",
        "",
        header,
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in ladder.iterrows():
        ok = "yes" if r["turnover_pass"] and r["gap_pass"] else "NO"
        lines.append(
            f"| {r['zi_bots']} | {r['turnover_ok']} of {r['sessions']} | "
            f"{_f(r['mean_llm_traded'], 1)} | {_f(r['median_abs_gap'], 1)} | {ok} | "
            f"{r['zi_only_periods']} | "
            f"{r['news_with']} / {r['news_flat']} / {r['news_against']} |"
        )
    verdict = (
        "passes"
        if passed
        else "no step passes: the one where the LLM traders trade most, as a limitation"
    )
    criteria = (
        f"Criteria: an LLM trades in >= {k} of {N_PERIODS} periods in most sessions; "
        f"median abs gap <= {cal['max_median_deviation']}."
    )
    lines += ["", criteria, f"Chosen: {chosen} ZI bots ({verdict}).", ""]
    for p, s in tables:
        lines += [f"## {int(s['zi_bots'].iloc[0])} ZI bots", "", *_step_lines(p, s), ""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return chosen, passed
