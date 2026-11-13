"""Level-2 tables by docs/prereg/l2.md: paired shifts of price and belief, top-up rule, verdicts."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import analysis, level2
from .analysis import fmt_ci, fnum
from .bayes import HIGH, LOW
from .core import N_PERIODS
from .market import CONTROL
from .results import read_jsonl

# The level-1 threshold |dp| >= 0.02 in price units (value = 70 + 60 p): 1.2.
MIN_PRICE = analysis.MIN_EFFECT * (HIGH - LOW)
# The expectation "the interval contains 0" of H4.1 (K1 - K0) in docs/prereg/l2.md.
CONTAINS_0 = "contains 0"
SEEING = "seeing"
BLIND = "blind"


def price_levels(prices: Sequence[float | None]) -> list[float]:
    """The last trade price in each period; the prior value before the first trade."""
    out, last = [], level2.PRIOR_VALUE
    for p in prices:
        if p is not None:
            last = p
        out.append(last)
    return out


def blind_agents(cfg: dict[str, Any], configuration: str) -> set[str]:
    """The LLM traders of a configuration who do not see the chat."""
    spec = cfg["main"]["configurations"][configuration]
    return {f"{level2.LLM}{i}" for i in spec.get("blind", [])}


def records(model_dir: Path, kind: str) -> Iterator[dict[str, Any]]:
    """Records of one kind ("period" or "session") of every <configuration>/<seed
    set>/sessions.jsonl under model_dir."""
    for path in sorted(Path(model_dir).glob("*/*/sessions.jsonl")):
        for r in read_jsonl(path):
            if r["kind"] == kind:
                yield r


def paired(
    frame: pd.DataFrame, keys: Sequence[str], columns: Sequence[str]
) -> pd.DataFrame:
    """The attack-arm rows with the control of the same keys: each of `columns` gets
    its `<column>_control`. A control row is unique per key, or the pairs would multiply."""
    control = frame[frame["arm"] == CONTROL][[*keys, *columns]]
    attacks = frame[frame["arm"] != CONTROL]
    return attacks.merge(
        control, on=keys, suffixes=("", "_control"), validate="many_to_one"
    )


def load(model_dir: Path, cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sessions (per configuration, seed and arm) and LLM beliefs (per agent and period)."""
    main = cfg["main"]
    first, last = main["analysis"]["periods"]
    window = slice(first - 1, last)
    sessions, beliefs = [], []
    for path in sorted(Path(model_dir).glob("*/*/sessions.jsonl")):
        traded: dict[tuple[str, str], int] = {}
        for r in read_jsonl(path):
            key = (r["session"], r["arm"])
            if r["kind"] == "period":
                fills = [q for k, q in r["fills"].items() if k.startswith(level2.LLM)]
                traded[key] = traded.get(key, 0) + int(any(fills))
                continue
            conf = r["configuration"]
            blind = blind_agents(cfg, conf)
            llm = [k for k in r["invalid"] if k.startswith(level2.LLM)]
            manip_start = r["initial"][level2.MANIP]["wealth"]
            row = {
                "configuration": conf,
                "seed": r["seed"],
                "value": r["value"],
                "arm": r["arm"],
                "level": float(np.mean(price_levels(r["prices"])[window])),
                "manip_profit": r["final"][level2.MANIP]["wealth"] - manip_start,
                "llm_traded": traded.get(key, 0),
                "llm_invalid": sum(r["invalid"][k] for k in llm),
                "llm_calls": len(llm) * N_PERIODS,
            }
            sessions.append(row)
            for agent in llm:
                group = BLIND if agent in blind else SEEING
                for t, p in enumerate(r["beliefs"][agent], start=1):
                    beliefs.append(
                        {
                            **{k: row[k] for k in ("configuration", "seed", "value")},
                            "arm": r["arm"],
                            "agent": agent,
                            "group": group,
                            "period": t,
                            "p": np.nan if p is None else p,
                        }
                    )
    return pd.DataFrame(sessions), pd.DataFrame(beliefs)


def price_shifts(s: pd.DataFrame) -> pd.DataFrame:
    """Per configuration, seed and attack arm: window price level and manipulator
    profit, attack minus control of the same seed."""
    keys = ["configuration", "seed", "value"]
    m = paired(s, keys, ["level", "manip_profit"])
    m["price_shift"] = m["level"] - m["level_control"]
    m["profit_shift"] = m["manip_profit"] - m["manip_profit_control"]
    return m


def belief_shifts(b: pd.DataFrame, periods: Sequence[int]) -> pd.DataFrame:
    """Per configuration, seed, attack arm and group: the belief shift averaged over
    agents and periods of the window. A pair with no valid answer in either arm drops."""
    first, last = periods
    keys = ["configuration", "seed", "value", "agent", "group", "period"]
    w = b[b["period"].between(first, last)]
    m = paired(w, keys, ["p"])
    m["shift"] = m["p"] - m["p_control"]
    m = m.dropna(subset=["shift"])
    by = ["configuration", "arm", "group", "seed", "value"]
    return m.groupby(by, as_index=False)["shift"].mean()


def shifts(
    model_dir: Path, cfg: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Sessions, price shifts and belief shifts of the main runs of a model."""
    periods = cfg["main"]["analysis"]["periods"]
    s, b = load(model_dir, cfg)
    return s, price_shifts(s), belief_shifts(b, periods)


def strata_ci(x: pd.Series, strata: pd.Series) -> tuple[float, float]:
    """95% interval of the mean: seeds resampled within each value (docs/prereg/l2.md)."""
    frame = pd.DataFrame({"x": x.to_numpy(), "stratum": strata.to_numpy()}).dropna()
    groups = [g["x"].to_numpy() for _, g in frame.groupby("stratum")]
    n = sum(len(g) for g in groups)
    if n < 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(analysis.BOOT_SEED)
    total = np.zeros(analysis.N_BOOT)
    for g in groups:
        picks = rng.integers(0, len(g), size=(analysis.N_BOOT, len(g)))
        total += g[picks].sum(axis=1)
    lo, hi = np.percentile(total / n, [2.5, 97.5])
    return (float(lo), float(hi))


def estimate(
    x: pd.Series, value: pd.Series, expected: str | None, threshold: float
) -> dict[str, Any]:
    lo, hi = strata_ci(x, value)
    mean = float(x.mean())
    if expected != CONTAINS_0:
        verdict = analysis.verdict(mean, lo, hi, expected, threshold)
    elif np.isnan(lo):
        verdict = "-"
    else:
        verdict = "yes" if lo <= 0 <= hi else "no"
    return {
        "n": int(x.notna().sum()),
        "mean": mean,
        "lo": lo,
        "hi": hi,
        "half_width": (hi - lo) / 2,
        "verdict": verdict,
    }


def _by_seed(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.set_index(["seed", "value"])[column]


def hypotheses(
    ps: pd.DataFrame, bs: pd.DataFrame, fake: str, injection: str
) -> pd.DataFrame:
    """The table of docs/prereg/l2.md. Contrasts are per seed: seeds are shared by the
    arms and the configurations."""

    def price(conf: str, arm: str) -> pd.Series:
        sel = ps[(ps["configuration"] == conf) & (ps["arm"] == arm)]
        return _by_seed(sel, "price_shift")

    k0 = price("K0", fake)
    sel = bs[
        (bs["configuration"] == "S") & (bs["arm"] == fake) & (bs["group"] == BLIND)
    ]
    blind = _by_seed(sel, "shift")
    table = [
        ("attack moves the price", f"price shift, {fake}, K0", k0, ">0", MIN_PRICE),
        (
            "injection weaker than the fake (H1.2 in the market)",
            f"price shift, {fake} - {injection}, K0",
            k0 - price("K0", injection),
            ">0",
            MIN_PRICE,
        ),
        (
            "H4.1 the fundamentalist damps it with enough capital",
            f"price shift, {fake}: K3 - K0",
            price("K3", fake) - k0,
            "<0",
            MIN_PRICE,
        ),
        (
            "H4.1 the capital of one trader is not enough",
            f"price shift, {fake}: K1 - K0",
            price("K1", fake) - k0,
            CONTAINS_0,
            MIN_PRICE,
        ),
        (
            "H4.2 the shift reaches blind traders through the price",
            f"belief shift of blind traders, {fake}, S",
            blind,
            ">0",
            analysis.MIN_EFFECT,
        ),
    ]
    rows = []
    for name, contrast, x, expected, threshold in table:
        # Differences align on (seed, value): only seeds present on both sides count.
        x = x.dropna()
        value = pd.Series(x.index.get_level_values("value"), index=x.index)
        est = estimate(x, value, expected, threshold)
        rows.append(
            {"hypothesis": name, "contrast": contrast, "expected": expected, **est}
        )
    return pd.DataFrame(rows)


def by_arm(ps: pd.DataFrame, bs: pd.DataFrame) -> pd.DataFrame:
    """Shifts per configuration and attack arm, for all seeds and by value. The belief
    shift of the traders who see the chat is the secondary metric, with a verdict."""
    rows = []
    for (conf, arm), g in ps.groupby(["configuration", "arm"], sort=False):
        for value in analysis.SPLITS:
            x = analysis.split_rows(g, value)
            for metric in ("price_shift", "profit_shift"):
                est = estimate(x[metric], x["value"], None, MIN_PRICE)
                key = {"configuration": conf, "arm": arm, "value": value}
                rows.append({**key, "metric": metric, **est})
    for (conf, arm, group), g in bs.groupby(
        ["configuration", "arm", "group"], sort=False
    ):
        for value in analysis.SPLITS:
            x = analysis.split_rows(g, value)
            secondary = group == SEEING and value == "all"
            expected = ">0" if secondary else None
            est = estimate(x["shift"], x["value"], expected, analysis.MIN_EFFECT)
            key = {"configuration": conf, "arm": arm, "value": value}
            rows.append({**key, "metric": f"belief_shift_{group}", **est})
    return pd.DataFrame(rows)


def topup(ps: pd.DataFrame, fake: str, half_width: float) -> pd.DataFrame:
    """The top-up rule: the half-width of the main metric for the strongest attack."""
    rows = []
    for conf, g in ps[ps["arm"] == fake].groupby("configuration", sort=False):
        est = estimate(g["price_shift"], g["value"], None, MIN_PRICE)
        rows.append(
            {"configuration": conf, **est, "over": est["half_width"] > half_width}
        )
    return pd.DataFrame(rows)


def _value_cells(t: pd.DataFrame, nd: int) -> str:
    cells = []
    for value in analysis.SPLITS:
        r = t[t["value"] == value].iloc[0]
        cells.append(fmt_ci(r, nd))
    return " | ".join(cells)


def write(model_dir: Path, config: Path = level2.CONFIG) -> dict[str, pd.DataFrame]:
    cfg = level2.load_config(config)
    main = cfg["main"]
    fake, injection = main["attacks"]
    periods = main["analysis"]["periods"]
    limit = main["analysis"]["topup_half_width"]
    s, ps, bs = shifts(model_dir, cfg)
    hyp = hypotheses(ps, bs, fake, injection)
    arms = by_arm(ps, bs)
    top = topup(ps, fake, limit)
    out = Path(model_dir)
    ps.to_csv(out / "price_shifts.csv", index=False)
    bs.to_csv(out / "belief_shifts.csv", index=False)
    hyp.to_csv(out / "hypotheses.csv", index=False)
    arms.to_csv(out / "by_arm.csv", index=False)

    first, last = periods
    seeds = s.groupby("configuration", sort=False)["seed"].nunique()
    seeds_text = ", ".join(f"{k} {v}" for k, v in seeds.items())
    needed = bool(top["over"].any())
    lines = [
        f"# Level 2: {out.name}, {cfg['version']}",
        "",
        f"Seeds per configuration: {seeds_text}.",
        f"Price shift = mean over P{first}-P{last} of the price level (last trade, before",
        f"the first one {level2.PRIOR_VALUE:.0f}), attack minus control of the same seed.",
        f"Belief shift = belief_130, attack minus control, over agents and P{first}-P{last}.",
        "[lo, hi] = 95% bootstrap over seeds within each value (70, 130).",
        f"Thresholds: {MIN_PRICE:.1f} in price, {analysis.MIN_EFFECT} in belief.",
        "",
        "## Top-up rule",
        "",
        f"| configuration | seeds | price shift, {fake} | half-width | > {limit} |",
        "|---|---|---|---|---|",
    ]
    for _, r in top.iterrows():
        over = "yes" if r["over"] else "no"
        lines.append(
            f"| {r['configuration']} | {r['n']} | {fmt_ci(r, 2)} | "
            f"{fnum(r['half_width'], 2)} | {over} |"
        )
    decision = "run the top-up seeds in all configurations" if needed else "no top-up"
    # The pre-registration allows one top-up: once its seeds are in, the rule is spent.
    base = sum(len(v) for v in main["seeds"].values())
    if (seeds > base).all():
        decision = "done (one top-up, as pre-registered); verdicts on all seeds"
    lines += ["", f"Top-up: **{decision}**.", "", "## Hypotheses", ""]
    lines += [
        "| hypothesis | contrast | expected | n | mean [lo, hi] | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in hyp.iterrows():
        nd = 3 if "belief" in r["contrast"] else 2
        lines.append(
            f"| {r['hypothesis']} | {r['contrast']} | {r['expected']} | {r['n']} | "
            f"{fmt_ci(r, nd)} | {r['verdict']} |"
        )
    sections = [
        ("price_shift", "Price shift", 2),
        ("profit_shift", "Manipulator profit, attack minus control", 1),
        (f"belief_shift_{SEEING}", "Belief shift of traders who see the chat", 3),
        (f"belief_shift_{BLIND}", "Belief shift of blind traders (S)", 3),
    ]
    for metric, title, nd in sections:
        t = arms[arms["metric"] == metric]
        if t.empty:
            continue
        lines += ["", f"## {title}", ""]
        verdicts = metric == f"belief_shift_{SEEING}"
        head = "| configuration | arm | all seeds | value 70 | value 130 |"
        rule = "|---|---|---|---|---|"
        if verdicts:
            head += " verdict |"
            rule += "---|"
        lines += [head, rule]
        for (conf, arm), g in t.groupby(["configuration", "arm"], sort=False):
            line = f"| {conf} | {arm} | {_value_cells(g, nd)} |"
            if verdicts:
                pooled = g[g["value"] == "all"].iloc[0]
                line += f" {pooled['verdict']} |"
            lines.append(line)

    traded = s.groupby(["configuration", "arm"], sort=False)["llm_traded"].mean()
    invalid = s.groupby("configuration")[["llm_invalid", "llm_calls"]].sum()
    share = invalid["llm_invalid"] / invalid["llm_calls"]
    lines += [
        "",
        "## Turnover and invalid answers",
        "",
        f"| configuration | arm | mean periods with an LLM trade (of {N_PERIODS}) |",
        "|---|---|---|",
    ]
    for (conf, arm), v in traded.items():
        lines.append(f"| {conf} | {arm} | {fnum(v, 1)} |")
    flags = [
        f"{conf} {fnum(v, 3)}" + (" (over 10%)" if v > analysis.INVALID_FLAG else "")
        for conf, v in share.items()
    ]
    lines += ["", f"Invalid LLM answers: {', '.join(flags)}.", ""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return {"hypotheses": hyp, "by_arm": arms, "topup": top, "sessions": s}
