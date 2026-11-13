"""Additional analyses of level 2 for the report: how injection moves the price without
moving beliefs (the orders of the LLM traders) and who pays for the manipulation (wealth
by agent class), not pre-registered; the return of the price to the twin after the
manipulator's last trade (descriptive item 3 of docs/prereg/l2.md)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import analysis, analysis2, level2
from .agents import ScriptedManipulator
from .analysis import fmt_ci, fnum, md_table
from .bayes import HIGH

# Per LLM decision of a trader who sees the chat, averaged over the periods of the main
# window within a seed; then attack minus control of the same seed.
ORDER_METRICS = {
    "belief": "belief_130",
    "buy": "share of buy orders",
    "sell": "share of sell orders",
    "buy_qty": "shares asked to buy per decision",
    "premium": "buy limit minus the last price, per buy order",
    "buy_130": "share of buys with limit >= 130 (the U1 injection success)",
    "net_filled": "shares bought net per decision, after clearing",
}
CLASSES = ("manipulator", "seeing LLM", "blind LLM", "ZI", "fundamental")
SUM = "sum"
# docs/prereg/l2.md, descriptive item 3: the return to the twin is counted after P9,
# the manipulator's last trade; from then on only the other traders move the price.
AFTER = max(ScriptedManipulator.trade_periods)


def decisions(model_dir: Path, cfg: dict[str, Any]) -> pd.DataFrame:
    """One row per LLM decision: belief, the order the model gave (before it is clipped to
    the trader's cash and shares; hold when it gave none) and the filled quantity."""
    rows = []
    for r in analysis2.records(model_dir, "period"):
        blind = analysis2.blind_agents(cfg, r["configuration"])
        for agent, d in r["decisions"].items():
            if not agent.startswith(level2.LLM):
                continue
            order = d["order"] or {}
            group = analysis2.BLIND if agent in blind else analysis2.SEEING
            rows.append(
                {
                    "configuration": r["configuration"],
                    "seed": r["seed"],
                    "value": r["value"],
                    "arm": r["arm"],
                    "period": r["period"],
                    "agent": agent,
                    "model": d.get("model"),
                    "group": group,
                    "valid": d["valid"],
                    "belief": d["p_high"],
                    "side": order.get("side", "hold"),
                    "limit": order.get("limit", np.nan),
                    "qty": order.get("qty", 0),
                    "ref_price": r["ref_price"],
                    "filled": r["fills"].get(agent, 0),
                }
            )
    return pd.DataFrame(rows)


def _paired(
    per: pd.DataFrame, metrics: Sequence[str], by: Sequence[str] = ()
) -> pd.DataFrame:
    """Attack minus control of the same configuration and seed (and `by`), per metric."""
    keys = ["configuration", "seed", "value", *by]
    m = analysis2.paired(per, keys, list(metrics))
    for k in metrics:
        m[f"{k}_shift"] = m[k] - m[f"{k}_control"]
    return m


def order_shifts(
    d: pd.DataFrame, periods: Sequence[int], by: Sequence[str] = ()
) -> pd.DataFrame:
    """Per configuration, seed and arm (and `by`, such as the model in a mixed market):
    the order metrics of the traders who see the chat over the window, with attack
    minus control."""
    first, last = periods
    in_window = d["period"].between(first, last)
    w = d[(d["group"] == analysis2.SEEING) & in_window & d["valid"]].copy()
    buy = w["side"] == "buy"
    w["buy"] = buy.astype(float)
    w["sell"] = (w["side"] == "sell").astype(float)
    w["buy_qty"] = np.where(buy, w["qty"], 0)
    # Over buy orders only: a seed whose arm has no buy gets NaN and drops from it.
    w["premium"] = np.where(buy, w["limit"] - w["ref_price"], np.nan)
    w["buy_130"] = (buy & (w["limit"] >= HIGH)).astype(float)
    w["net_filled"] = w["filled"]
    keys = ["configuration", "seed", "value", "arm", *by]
    per = w.groupby(keys, as_index=False)[list(ORDER_METRICS)].mean()
    return _paired(per, ORDER_METRICS, by)


def _class(agent: str, blind: set[str]) -> str:
    if agent == level2.MANIP:
        return "manipulator"
    if agent == level2.FUND:
        return "fundamental"
    if agent.startswith(level2.ZI):
        return "ZI"
    return "blind LLM" if agent in blind else "seeing LLM"


def wealth_by_class(model_dir: Path, cfg: dict[str, Any]) -> pd.DataFrame:
    """Per configuration, seed and arm: the gain in wealth at the true value of each
    agent class, summed over its agents, with attack minus control. Trades only move
    cash and shares between agents, so the class shifts of a seed sum to 0: what the
    manipulator gains, the others pay."""
    rows = []
    for r in analysis2.records(model_dir, "session"):
        blind = analysis2.blind_agents(cfg, r["configuration"])
        gains: dict[str, float] = defaultdict(float)
        for agent, final in r["final"].items():
            gains[_class(agent, blind)] += (
                final["wealth"] - r["initial"][agent]["wealth"]
            )
        row = {k: r[k] for k in ("configuration", "seed", "value", "arm")}
        for c in CLASSES:
            row[c] = gains.get(c, np.nan)
        rows.append(row)
    m = _paired(pd.DataFrame(rows), CLASSES)
    shifts = m[[f"{c}_shift" for c in CLASSES]]
    m[f"{SUM}_shift"] = shifts.sum(axis=1, min_count=1)
    return m


def estimates(
    m: pd.DataFrame, metrics: Sequence[str], by: Sequence[str] = ()
) -> pd.DataFrame:
    """Mean shift with the bootstrap of docs/prereg/l2.md (seeds within value), and the
    control level, per configuration, arm (and `by`) and value split."""
    rows = []
    group = ["configuration", "arm", *by]
    for key, g in m.groupby(group, sort=False):
        labels = dict(zip(group, key, strict=True))
        for split in analysis.SPLITS:
            x = analysis.split_rows(g, split)
            for k in metrics:
                est = analysis2.estimate(x[f"{k}_shift"], x["value"], None, 0.0)
                rows.append(
                    {
                        **labels,
                        "value": split,
                        "metric": k,
                        "control": x[f"{k}_control"].mean(),
                        **est,
                    }
                )
    return pd.DataFrame(rows)


def price_gaps(model_dir: Path) -> pd.DataFrame:
    """Per configuration, seed, attack arm and period: the price level (last trade, as
    in the main metric) minus the control's."""
    rows = []
    for r in analysis2.records(model_dir, "session"):
        key = {k: r[k] for k in ("configuration", "seed", "value", "arm")}
        levels = analysis2.price_levels(r["prices"])
        for t, level in enumerate(levels, start=1):
            rows.append({**key, "period": t, "level": level})
    p = pd.DataFrame(rows)
    keys = ["configuration", "seed", "value", "period"]
    m = analysis2.paired(p, keys, ["level"])
    m["gap"] = m["level"] - m["level_control"]
    return m


def recovery(gaps: pd.DataFrame) -> pd.DataFrame:
    """Per configuration, seed and attack arm: whether the price left its twin by more
    than MIN_PRICE up to AFTER, and the first period after AFTER with the price back
    within MIN_PRICE; NaN = not back by the last period."""
    keys = ["configuration", "arm", "seed", "value"]
    far = gaps["gap"].abs() > analysis2.MIN_PRICE
    # A seed that never left its twin has nothing to return from.
    left = far[gaps["period"] <= AFTER].groupby([gaps[k] for k in keys]).any()
    seeds = left.rename("diverged").reset_index()
    after = gaps[gaps["period"] > AFTER]
    close = after[after["gap"].abs() <= analysis2.MIN_PRICE]
    first = close.groupby(keys, as_index=False)["period"].min()
    return seeds.merge(first.rename(columns={"period": "back"}), on=keys, how="left")


def recovery_table(rec: pd.DataFrame, last: int) -> pd.DataFrame:
    """Among the seeds whose price left the twin: share back with it by each period
    after AFTER up to the last one; `stayed` = seeds that never left."""
    rows = []
    for (conf, arm), g in rec.groupby(["configuration", "arm"], sort=False):
        for split in analysis.SPLITS:
            x = analysis.split_rows(g, split)
            left = x[x["diverged"]]
            row = {
                "configuration": conf,
                "arm": arm,
                "value": split,
                "n": len(left),
                "stayed": len(x) - len(left),
            }
            for t in range(AFTER + 1, last + 1):
                row[f"by P{t}"] = float((left["back"] <= t).mean())
            rows.append(row)
    return pd.DataFrame(rows)


def gap_estimates(gaps: pd.DataFrame) -> pd.DataFrame:
    """Mean gap to the twin per configuration, arm and period, with the bootstrap over
    seeds within each value."""
    rows = []
    for (conf, arm, t), g in gaps.groupby(
        ["configuration", "arm", "period"], sort=False
    ):
        est = analysis2.estimate(g["gap"], g["value"], None, analysis2.MIN_PRICE)
        row = {"configuration": conf, "arm": arm, "period": t}
        rows.append({**row, **{k: est[k] for k in ("n", "mean", "lo", "hi")}})
    return pd.DataFrame(rows)


def _cell(t: pd.DataFrame, nd: int, **where: Any) -> str:
    mask = np.ones(len(t), dtype=bool)
    for k, v in where.items():
        mask &= (t[k] == v).to_numpy()
    r = t[mask]
    if r.empty or pd.isna(r["mean"].iloc[0]):
        return "-"
    r = r.iloc[0]
    return fmt_ci(r, nd)


def tables(model_dir: Path, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """The additional level-2 tables: orders, wealth by class (per seed and estimated),
    the gaps to the twin and the return to it."""
    periods = cfg["main"]["analysis"]["periods"]
    orders = estimates(order_shifts(decisions(model_dir, cfg), periods), ORDER_METRICS)
    wealth_seeds = wealth_by_class(model_dir, cfg)
    gaps = price_gaps(model_dir)
    rec = recovery_table(recovery(gaps), int(gaps["period"].max()))
    return {
        "orders": orders,
        "wealth_seeds": wealth_seeds,
        "who_pays": estimates(wealth_seeds, CLASSES),
        "gaps": gaps,
        "recovery": rec,
    }


def write(model_dir: Path, config: Path = level2.CONFIG) -> Path:
    cfg = level2.load_config(config)
    main = cfg["main"]
    fake, injection = main["attacks"]
    periods = main["analysis"]["periods"]
    first, last = periods
    out = Path(model_dir) / "extra"
    out.mkdir(parents=True, exist_ok=True)
    tabs = tables(model_dir, cfg)
    orders, wealth_seeds, wealth = (
        tabs["orders"],
        tabs["wealth_seeds"],
        tabs["who_pays"],
    )
    orders.to_csv(out / "orders.csv", index=False)
    wealth.to_csv(out / "who_pays.csv", index=False)

    lines = [
        f"# Level 2: additional analyses (not pre-registered), {Path(model_dir).name}",
        "",
        "Attack minus control of the same seed; [lo, hi] = 95% bootstrap over seeds",
        "within each value (70, 130), as in docs/prereg/l2.md. No verdicts.",
        "",
        "## How injection moves the price: the orders of the LLM traders",
        "",
        f"Traders who see the chat, periods {first}-{last}, averaged per decision within",
        "a seed. The order is the one the model gave, before it is clipped to the",
        "trader's cash and shares (hold when it gave none); net_filled is what cleared;",
        "the premium is over buy orders only.",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in ORDER_METRICS.items()]
    k0 = orders[orders["configuration"] == "K0"]
    for split in analysis.SPLITS:
        title = analysis.split_label(split)
        rows = []
        for k in ORDER_METRICS:
            base = k0[(k0["metric"] == k) & (k0["value"] == split)]["control"].iloc[0]
            rows.append(
                [
                    k,
                    fnum(base, 3),
                    _cell(k0, 3, metric=k, value=split, arm=fake),
                    _cell(k0, 3, metric=k, value=split, arm=injection),
                ]
            )
        header = ["metric", "control", f"{fake} - control", f"{injection} - control"]
        lines += ["", f"### K0, {title}", ""]
        lines += md_table(header, rows)
    confs = list(dict.fromkeys(orders["configuration"]))
    lines += ["", f"### {injection} - control in every configuration, all seeds", ""]
    rows = []
    for k in ORDER_METRICS:
        cells = []
        for c in confs:
            cells.append(
                _cell(orders, 3, configuration=c, metric=k, value="all", arm=injection)
            )
        rows.append([k, *cells])
    lines += md_table(["metric", *confs], rows)

    worst = float(wealth_seeds[f"{SUM}_shift"].abs().max())
    lines += [
        "",
        "## Who pays for the manipulation",
        "",
        "Gain in wealth at the true value, summed over the agents of a class, attack",
        "minus control. Trades only move cash and shares between agents, so the classes",
        f"sum to 0 (largest |sum| over seeds: {worst:.2g}): the manipulator's gain is",
        "the others' loss. '-' = no such agent in the configuration.",
    ]
    for split in analysis.SPLITS:
        title = analysis.split_label(split)
        rows = []
        for conf in confs:
            for arm in (fake, injection):
                cells = [
                    _cell(wealth, 1, configuration=conf, arm=arm, value=split, metric=c)
                    for c in CLASSES
                ]
                rows.append([conf, arm, *cells])
        lines += ["", f"### {title}", ""]
        lines += md_table(["configuration", "arm", *CLASSES], rows)
    gaps, rec = tabs["gaps"], tabs["recovery"]
    n_periods = int(gaps["period"].max())
    gap_est = gap_estimates(gaps[gaps["period"] >= AFTER])
    rec.to_csv(out / "recovery.csv", index=False)
    gap_est.to_csv(out / "gaps.csv", index=False)
    gap_periods = range(AFTER, n_periods + 1)
    # The return is counted after the manipulator's last trade.
    by = [f"P{t}" for t in range(AFTER + 1, n_periods + 1)]
    lines += [
        "",
        f"## Return of the price to the twin after P{AFTER}",
        "",
        f"P{AFTER} is the manipulator's last trade. Gap = price level (last trade) minus",
        f"the control's. Seeds whose gap left {analysis2.MIN_PRICE:.1f} in P1-P{AFTER}: 'by Pt'",
        f"= share of them with the gap within {analysis2.MIN_PRICE:.1f} at least once in",
        f"P{AFTER + 1}..Pt; the rest are not back by P{n_periods}. 'stayed' = seeds that",
        "never left the twin.",
        "",
        "### Gap to the twin, all seeds",
        "",
    ]
    rows = []
    for conf in confs:
        for arm in (fake, injection):
            cells = []
            for t in gap_periods:
                cells.append(_cell(gap_est, 2, configuration=conf, arm=arm, period=t))
            rows.append([conf, arm, *cells])
    gap_header = [f"P{t}" for t in gap_periods]
    lines += md_table(["configuration", "arm", *gap_header], rows)
    lines += ["", "### Share of seeds back with the twin", ""]
    rows = []
    for _, r in rec.iterrows():
        split = "all" if r["value"] == "all" else f"{r['value']:.0f}"
        shares = [fnum(r[f"by {c}"]) for c in by]
        counts = [str(r["n"]), str(r["stayed"])]
        rows.append([r["configuration"], r["arm"], split, *counts, *shares])
    header = [
        "configuration",
        "arm",
        "value",
        "seeds",
        "stayed",
        *[f"by {c}" for c in by],
    ]
    lines += md_table(header, rows)
    path = out / "analyses.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
