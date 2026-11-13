"""Variant C of level 2 (exploratory, no verdicts): crash attack, LLM manipulator, mixed market."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from . import analysis, analysis2, defenses, level2
from .agents import Agent, LLMManipulator, LLMTrader, ScriptedManipulator
from .analysis import fmt_ci, fnum
from .chat import MessageBank, window
from .core import N_PERIODS, ChatMessage, DecisionContext, Observation
from .llm.client import LLMClient
from .llm.config import get_model
from .market import CONTROL, SessionConfig, run_session
from .results import RESULTS, make_client, read_jsonl, session_log

# The pieces run on K0 of the main runs: same market and seeds, so a piece whose control
# arm matches the main control takes it from the cache.
CONFIGURATION = "K0"
LLM_TEXT = "llm_generated"
# A chat window shown to the D4 filter, and the call tags that name it.
WINDOW = ["model", "source", "seed", "period"]
MARKET_TAGS = ("source", "seed", "period")


def piece_market(
    cfg: dict[str, Any],
    piece: str,
    model: str,
    client: LLMClient,
    seed: int,
    bank: MessageBank,
) -> list[Agent]:
    """K0 of the main runs with the traders and the manipulator of a piece."""
    main = cfg["main"]
    spec = cfg["variant_c"]["pieces"][piece]
    agents = level2.market(cfg, model, client, seed, bank.ticker, main["zi_bots"])
    by_id = {a.agent_id: a for a in agents}
    for i, name in enumerate(spec.get("trader_models", [])):
        by_id[f"{level2.LLM}{i}"].model = get_model(name)
    m = spec.get("manipulator", main["manipulator"])
    common = {
        "agent_id": level2.MANIP,
        "cash": float(m["cash"]),
        "shares": int(m["shares"]),
        "bank": bank,
        "seed": seed,
        "direction": spec.get("direction", "up"),
    }
    if "writer" in spec:
        writer = get_model(spec["writer"])
        manipulator = LLMManipulator(**common, model=writer, client=client)
    else:
        manipulator = ScriptedManipulator(**common)
    agents.append(manipulator)
    return agents


def run(
    model: str,
    *,
    pieces: Sequence[str] | None = None,
    seeds_per_value: int | None = None,
    config: Path = level2.CONFIG,
    out_dir: Path | None = None,
    cache_path: Path | None = None,
) -> Path:
    """Every piece x seed x (control, attack); `seeds_per_value` takes the first seeds
    of each value, for a smoke run."""
    cfg = level2.load_config(config)
    c = cfg["variant_c"]
    bank = MessageBank.load()
    default_out = RESULTS / "level2" / "variant_c" / cfg["version"] / model
    out = Path(out_dir) if out_dir else default_out
    for piece in pieces or list(c["pieces"]):
        spec = c["pieces"][piece]
        attack = spec["attack"]
        # Control first: the periods before the first message come from the cache.
        arms = [(CONTROL, None), (attack, {"type": attack})]
        # The layout <piece>/<configuration>/<seed set> is the one analysis2.load reads.
        step = out / piece / CONFIGURATION / "seeds"
        client = make_client(step, cache_path)
        logger = session_log(step)
        tags = {
            "model": model,
            "version": cfg["version"],
            "configuration": CONFIGURATION,
            "seed_set": "seeds",
            "piece": piece,
        }
        piece_seeds = spec.get("seeds", c["seeds"])
        for value, seeds in piece_seeds.items():
            for seed in seeds[:seeds_per_value]:
                for arm, attack_spec in arms:
                    run_session(
                        SessionConfig(seed=seed, value=float(value)),
                        piece_market(cfg, piece, model, client, seed, bank),
                        bank,
                        arm=arm,
                        attack=attack_spec,
                        logger=logger,
                        session_id=f"{piece}-v{value}-s{seed}",
                        tags=tags,
                    )
    return out


def trader_groups(spec: dict[str, Any], traders: int) -> dict[str, str]:
    """LLM trader id -> its model in a mixed market, else one group of all LLM traders."""
    models = spec.get("trader_models")
    ids = [f"{level2.LLM}{i}" for i in range(traders)]
    if not models:
        return dict.fromkeys(ids, level2.LLM)
    return dict(zip(ids, models, strict=True))


def wealth_shifts(piece_dir: Path, groups: dict[str, str]) -> pd.DataFrame:
    """Per seed, attack arm and group: the traders' gain in wealth at the true value,
    attack minus control. Who pays for the manipulation, and in a mixed market who
    gains from whom."""
    rows = []
    for r in analysis2.records(piece_dir, "session"):
        for agent, group in groups.items():
            gain = r["final"][agent]["wealth"] - r["initial"][agent]["wealth"]
            key = {"seed": r["seed"], "value": r["value"], "arm": r["arm"]}
            rows.append({**key, "group": group, "gain": gain})
    keys = ["seed", "value", "group"]
    w = pd.DataFrame(rows).groupby([*keys, "arm"], as_index=False)["gain"].mean()
    m = analysis2.paired(w, keys, ["gain"])
    m["shift"] = m["gain"] - m["gain_control"]
    return m


def wealth_rows(ws: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (arm, group), g in ws.groupby(["arm", "group"], sort=False):
        for value in analysis.SPLITS:
            x = analysis.split_rows(g, value)
            est = analysis2.estimate(x["shift"], x["value"], None, analysis2.MIN_PRICE)
            key = {"arm": arm, "value": value, "metric": f"wealth_shift_{group}"}
            rows.append({**key, **est})
    return pd.DataFrame(rows)


def attack_windows(
    paths: Sequence[Path], arm: str
) -> list[tuple[int, int, list[ChatMessage]]]:
    """(seed, period, chat the traders saw) for each period a manipulator message was
    posted in the attack arm."""
    by_session: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        for r in read_jsonl(path):
            if r["kind"] == "period" and r["arm"] == arm:
                by_session.setdefault(r["session"], []).append(r)
    out = []
    for recs in by_session.values():
        feed: list[ChatMessage] = []
        for r in sorted(recs, key=lambda r: r["period"]):
            posted = [ChatMessage(**m) for m in r["chat"]]
            feed += posted
            if any(m.kind == "manipulation" for m in posted):
                visible = window(feed, r["period"], SessionConfig.chat_window)
                out.append((r["seed"], r["period"], visible))
    return out


def d4_check(
    sources: dict[str, tuple[Sequence[Path], str]],
    models: Sequence[str],
    client: LLMClient,
) -> pd.DataFrame:
    """The D4 filter of level 1 on the chat windows of the market: one row per message
    shown to the filter. `sources` maps a label to (session logs, attack arm)."""
    rows = []
    for model in models:
        # The filter is the trader's own call (D4 uses the trader's model); the agent
        # only carries the model and the client.
        trader = LLMTrader(
            agent_id="d4", cash=0.0, shares=0, model=get_model(model), client=client
        )
        for label, (paths, arm) in sources.items():
            for seed, period, visible in attack_windows(paths, arm):
                obs = Observation(period, N_PERIODS, 0.0, 0, [], [], visible, 0.0)
                tags = {"source": label, "seed": seed, "period": period}
                ctx = DecisionContext(seed_parts=(seed, period), tags=tags)
                _, extra = trader.apply_filter(obs, ctx)
                for pred in extra["filter"]:
                    row = {"model": model, "source": label, "seed": seed}
                    row.update(
                        period=period,
                        kind=pred["kind"],
                        flagged=pred["flagged"],
                        filter_valid=extra["filter_valid"],
                    )
                    rows.append(row)
    return pd.DataFrame(rows)


def d4_annotate(d: pd.DataFrame, labeled: dict[tuple, set[int]]) -> pd.DataFrame:
    """Mark each shown message: labeled by the filter's answer, and the first show of a
    manipulator message. `labeled`: defenses.filter_labels of the D4 check's call log."""
    d = d.copy()
    # Rows of a window keep the order of the filter prompt, so the position is the id.
    position = d.groupby(WINDOW, sort=False).cumcount() + 1
    keys = d[WINDOW].itertuples(index=False, name=None)
    ids = [
        labeled[k] if v else set() for k, v in zip(keys, d["filter_valid"], strict=True)
    ]
    d["labeled"] = [p in s for p, s in zip(position, ids, strict=True)]
    manip = d[d["kind"] == "manipulation"]
    # One manipulator message a period, appended after the earlier chat: the last one in
    # a window was posted in that period and is shown for the first time.
    first = manip.groupby(WINDOW, sort=False).tail(1).index
    d["first_show"] = d.index.isin(first)
    return d


def seed_values(out: Path) -> dict[int, float]:
    """The asset value of each seed, from the session records of the pieces."""
    values = {}
    for path in sorted(Path(out).glob("*/*/*/sessions.jsonl")):
        for r in read_jsonl(path):
            if r["kind"] == "session":
                values[r["seed"]] = r["value"]
    return values


def d4_recall(d: pd.DataFrame, values: dict[int, float]) -> pd.DataFrame:
    """Per filter model and source (d from d4_annotate): share of manipulator messages
    flagged at their first show (95% bootstrap over seeds within each value), the same
    over every show, and the share of neutral messages flagged."""
    rows = []
    for (model, source), g in d.groupby(["model", "source"], sort=False):
        manip = g[g["kind"] == "manipulation"]
        first = manip[manip["first_show"]]
        neutral = g[g["kind"] != "manipulation"]
        flagged = first["flagged"].astype(float)
        strata = first["seed"].map(values)
        if strata.isna().any():
            raise ValueError(
                f"seeds without a value: {sorted(set(first['seed']) - set(values))}"
            )
        lo, hi = analysis2.strata_ci(flagged, strata)
        windows = g.groupby(["seed", "period"])
        valid = windows["filter_valid"].first().astype(bool)
        complete = windows["labeled"].all()[valid]
        rows.append(
            {
                "model": model,
                "source": source,
                "windows": windows.ngroups,
                "filter_valid": valid.mean(),
                "complete": complete.mean(),
                "messages": len(first),
                "recall": flagged.mean(),
                "lo": lo,
                "hi": hi,
                "recall_shows": manip["flagged"].astype(float).mean(),
                "false_alarms": neutral["flagged"].astype(float).mean(),
            }
        )
    return pd.DataFrame(rows)


def d4_table(out: Path) -> pd.DataFrame:
    """d4_recall of a D4 check directory (d4_check.csv and its calls.jsonl)."""
    labeled = defenses.filter_labels(out / "calls.jsonl", MARKET_TAGS)
    d = d4_annotate(pd.read_csv(out / "d4_check.csv"), labeled)
    return d4_recall(d, seed_values(out.parent))


def write_d4(d: pd.DataFrame, out: Path) -> Path:
    """The filter's answers on the market chat, then their table."""
    d.to_csv(out / "d4_check.csv", index=False)
    return write_d4_report(out)


def write_d4_report(out: Path) -> Path:
    """Recall on the manipulator's messages and false alarms on the neutral ones."""
    lines = [
        "# D4 filter on the market chat: LLM-written against bank messages",
        "",
        "Each period a manipulator message was posted, the filter sees the chat window",
        f"the traders saw; a message stays there for {SessionConfig.chat_window} periods.",
        "recall = share of manipulator messages flagged at their first show (95% bootstrap",
        "over seeds within each value); per show = the same over every show; complete =",
        "share of valid filter answers that label every message id (a message without a",
        "label passes the filter); false alarms = share of neutral messages flagged.",
        "",
        (
            "| filter model | source | windows | filter valid | complete | messages | "
            "recall [lo, hi] | per show | false alarms |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in d4_table(out).iterrows():
        lines.append(
            f"| {r['model']} | {r['source']} | {r['windows']} | {fnum(r['filter_valid'])} | "
            f"{fnum(r['complete'])} | {r['messages']} | "
            f"{fmt_ci(r, 2, point='recall')} | {fnum(r['recall_shows'])} | "
            f"{fnum(r['false_alarms'])} |"
        )
    path = out / "d4_check.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def llm_messages(piece_dir: Path) -> list[str]:
    """Texts the LLM manipulator posted, in order."""
    texts = []
    for r in analysis2.records(piece_dir, "period"):
        texts += [m["text"] for m in r["chat"] if m.get("msg_type") == LLM_TEXT]
    return texts


def piece_tables(
    piece_dir: Path, spec: dict[str, Any], cfg: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sessions of a piece and its shifts per arm: price, manipulator profit, belief
    (by model in a mixed market, else by chat access) and traders' wealth."""
    first, last = cfg["main"]["analysis"]["periods"]
    s, b = analysis2.load(piece_dir, cfg)
    groups = trader_groups(spec, len(cfg["traders"]))
    if spec.get("trader_models"):
        b["group"] = b["agent"].map(groups)
    ps = analysis2.price_shifts(s)
    bs = analysis2.belief_shifts(b, (first, last))
    ws = wealth_shifts(piece_dir, groups)
    by_arm = analysis2.by_arm(ps, bs)
    return s, pd.concat([by_arm, wealth_rows(ws)], ignore_index=True)


def write(out: Path, config: Path = level2.CONFIG) -> dict[str, pd.DataFrame]:
    """Descriptive tables per piece, by the definitions of the main metric; no verdicts."""
    cfg = level2.load_config(config)
    c = cfg["variant_c"]
    first, last = cfg["main"]["analysis"]["periods"]
    tables = {}
    lines = [
        f"# Level 2, variant C (exploratory): {Path(out).name}, {cfg['version']}",
        "",
        "K0 market of the main runs, control and attack arm per seed. Price shift = mean",
        f"over P{first}-P{last} of the price level, attack minus control; belief shift =",
        "belief_130, attack minus control, over agents and the same periods.",
        "[lo, hi] = 95% bootstrap over seeds within each value (70, 130). No verdicts.",
    ]
    for piece, spec in c["pieces"].items():
        piece_dir = Path(out) / piece
        if not piece_dir.exists():
            continue
        s, arms = piece_tables(piece_dir, spec, cfg)
        tables[piece] = arms
        arms.to_csv(Path(out) / f"{piece}_by_arm.csv", index=False)
        seeds = s["seed"].nunique()
        lines += [
            "",
            f"## {piece}: {spec['attack']}, {seeds} seeds",
            "",
            "| metric | all seeds | value 70 | value 130 |",
            "|---|---|---|---|",
        ]
        for metric, g in arms.groupby("metric", sort=False):
            nd = 3 if metric.startswith("belief") else 2
            lines.append(f"| {metric} | {analysis2._value_cells(g, nd)} |")
        traded = s.groupby("arm", sort=False)["llm_traded"].mean()
        traded_text = ", ".join(f"{arm} {fnum(v, 1)}" for arm, v in traded.items())
        invalid = s["llm_invalid"].sum() / s["llm_calls"].sum()
        lines += [
            "",
            f"Mean periods with an LLM trade (of {N_PERIODS}): {traded_text}.",
            f"Invalid LLM answers: {fnum(invalid, 3)}.",
        ]
        if "writer" in spec:
            texts = llm_messages(piece_dir)
            attack_sessions = int((s["arm"] != CONTROL).sum())
            unique = list(dict.fromkeys(texts))
            examples = [f"> {t}" for t in unique[:5]]
            posted = (
                f"Messages posted by the LLM manipulator ({spec['writer']}): {len(texts)}"
                f" in {attack_sessions} attack sessions (at most one a period, P2-P6)."
            )
            lines += [posted, "", *examples]
    (Path(out) / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    d4_dir = Path(out) / "d4_check"
    if (d4_dir / "d4_check.csv").exists():
        write_d4_report(d4_dir)
    return tables
