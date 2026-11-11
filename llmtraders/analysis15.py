"""Level-1.5 tables: p(130) by period, text/price/interaction effects paired within a seed."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

from . import analysis, level15
from .market import SessionConfig
from .results import read_jsonl

# Cells of the 2x2 within one seed: Rational/Pumped price x Neutral/Attack chat.
CELLS = ["RN", "PN", "RA", "PA"]
# Paired differences per period; all four cells of a seed share the sampling seeds.
EFFECTS = {
    "text": ("RA", "RN"),
    "text_pumped": ("PA", "PN"),
    "price": ("PN", "RN"),
}
GROUPS = ["all", 70.0, 130.0]


class Window(NamedTuple):
    """mean over `periods` of `effect` (minus the same over `minus`, if given)."""

    name: str
    effect: str
    periods: tuple[int, ...]
    minus: tuple[int, ...] = ()


def windows() -> list[Window]:
    cfg = level15.load_config()
    msg = tuple(cfg["msg_periods"])
    before = tuple(range(1, min(msg)))
    # The chat window keeps the last manipulator message visible for chat_window - 1
    # more periods, so "after" starts once it is gone.
    after_start = max(msg) + SessionConfig.chat_window
    after = tuple(range(after_start, SessionConfig.n_periods + 1))
    last = max(msg)
    return [
        # Sanity check: before the first message the cells see the same prompts.
        Window("text before", "text", before),
        Window("text during", "text", msg),
        Window("text after", "text", after),
        Window("accumulation: last - first message", "text", (last,), (min(msg),)),
        Window("decay: during - after", "text", msg, after),
        Window("news at P8: P8 - P7", "text", (last + 1,), (last,)),
        Window("price during", "price", msg),
        Window("price after", "price", after),
        Window("interaction during", "interaction", msg),
        Window("buys during", "buys", msg),
    ]


def load(dirs: Sequence[Path]) -> pd.DataFrame:
    rows, sides, signals = [], [], []
    for d in dirs:
        rows += read_jsonl(Path(d) / "results.jsonl")
        for r in read_jsonl(Path(d) / "sessions.jsonl"):
            if r["kind"] == "period":
                side = r["decisions"]["trader"]["side"]
                sides.append(
                    {"session": r["session"], "period": r["period"], "side": side}
                )
            elif r["kind"] == "session":
                news = {int(k): v for k, v in r["signals"].items()}
                signals.append({"session": r["session"], "news_p4": news.get(4)})
    df = pd.DataFrame(rows)
    df = df.merge(pd.DataFrame(sides), on=["session", "period"], how="left")
    df = df.merge(pd.DataFrame(signals), on="session", how="left")
    df["p"] = df["p_high"].where(df["valid"])
    df["buy"] = np.where(df["valid"], (df["side"] == "buy").astype(float), np.nan)
    return df


def cells(df: pd.DataFrame, attack: str, metric: str) -> pd.DataFrame:
    """Indexed by (model, seed, value, news_p4, period): the metric in each cell."""
    sub = df[df["chat"].isin([level15.NEUTRAL, attack])].copy()
    price = sub["price_mode"].map({"rational": "R", "pumped": "P"})
    chat = np.where(sub["chat"] == level15.NEUTRAL, "N", "A")
    sub["cell"] = price + chat
    index = ["model", "seed", "value", "news_p4", "period"]
    return sub.pivot(index=index, columns="cell", values=metric)


def effects(df: pd.DataFrame, attack: str) -> pd.DataFrame:
    p = cells(df, attack, "p")
    for name, (a, b) in EFFECTS.items():
        p[name] = p[a] - p[b]
    p["interaction"] = p["text_pumped"] - p["text"]
    # Same index as p, so the columns align row by row.
    buys = cells(df, attack, "buy")
    p["buys"] = buys["RA"] - buys["RN"]
    return p.reset_index()


def _window_values(e: pd.DataFrame, w: Window) -> pd.DataFrame:
    """Per seed: the window mean of the effect."""
    keys = ["model", "seed", "value"]
    inside = e[e["period"].isin(w.periods)].groupby(keys)[w.effect].mean()
    if w.minus:
        base = e[e["period"].isin(w.minus)].groupby(keys)[w.effect].mean()
        inside = inside - base
    return inside.rename("x").reset_index()


def contrasts(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for attack in sorted(set(df["chat"]) - {level15.NEUTRAL}):
        e = effects(df, attack)
        for w in windows():
            per_seed = _window_values(e, w)
            for model, g in per_seed.groupby("model"):
                for group in GROUPS:
                    x = g if group == "all" else g[g["value"] == group]
                    out.append(
                        {
                            "model": model,
                            "attack": attack,
                            "contrast": w.name,
                            "value": group,
                            **analysis.estimate(x["x"], x["seed"], None),
                        }
                    )
        # Official news in P4 can confirm the fake (GOOD) or contradict it (BAD).
        at_p4 = e[e["period"] == 4]
        for (model, news), g in at_p4.groupby(["model", "news_p4"]):
            out.append(
                {
                    "model": model,
                    "attack": attack,
                    "contrast": f"text at P4, {news.upper()} news",
                    "value": "all",
                    **analysis.estimate(g["text"], g["seed"], None),
                }
            )
    return pd.DataFrame(out)


def curves(df: pd.DataFrame) -> pd.DataFrame:
    """Per model, attack and period: mean p of each cell, Bayes, and the paired effects."""
    out = []
    for attack in sorted(set(df["chat"]) - {level15.NEUTRAL}):
        e = effects(df, attack)
        bayes = (
            df[df["price_mode"] == "rational"]
            .groupby(["model", "seed", "period"])["rational_p"]
            .first()
            .groupby(["model", "period"])
            .mean()
        )
        for (model, period), g in e.groupby(["model", "period"]):
            rec = {"model": model, "attack": attack, "period": period}
            rec.update({c: g[c].mean() for c in CELLS})
            rec["bayes"] = bayes.get((model, period), np.nan)
            for name in ["text", "price", "interaction"]:
                est = analysis.estimate(g[name], g["seed"], None)
                rec.update(
                    {
                        name: est["mean"],
                        f"{name}_lo": est["lo"],
                        f"{name}_hi": est["hi"],
                    }
                )
            out.append(rec)
    return pd.DataFrame(out)


def recovery(c: pd.DataFrame) -> pd.DataFrame:
    """First period after the messages where the mean text effect is below MIN_EFFECT."""
    cfg = level15.load_config()
    last = max(cfg["msg_periods"])
    out = []
    for (model, attack), g in c.groupby(["model", "attack"]):
        after = g[g["period"] > last]
        below = after[after["text"].abs() < analysis.MIN_EFFECT]
        period = int(below["period"].min()) if len(below) else None
        out.append({"model": model, "attack": attack, "recovered_at": period})
    return pd.DataFrame(out)


def _ci(r: pd.Series) -> str:
    f = analysis._f
    return f"{f(r['mean'], 3)} [{f(r['lo'], 3)}, {f(r['hi'], 3)}]"


def write(dirs: Sequence[Path], out: Path) -> dict[str, pd.DataFrame]:
    df = load(dirs)
    con, cur = contrasts(df), curves(df)
    rec = recovery(cur)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    con.to_csv(out / "contrasts.csv", index=False)
    cur.to_csv(out / "curves.csv", index=False)
    f = analysis._f
    lines = [
        "# Level 1.5",
        "",
        "Cells of a seed: R/P = rational/pumped price, N/A = neutral chat/attack; they share",
        "the sampling seeds, so every effect is a paired difference within a seed.",
        "text = RA - RN, price = PN - RN, interaction = (PA - PN) - (RA - RN);",
        "buys = share of buys RA - RN. [lo, hi] = 95% bootstrap over seeds. No verdicts.",
        "",
    ]
    for (model, attack), g in con.groupby(["model", "attack"], sort=False):
        lines += [
            f"## {model}, {attack}",
            "",
            "| contrast | all seeds | value 70 | value 130 |",
            "|---|---|---|---|",
        ]
        for name, h in g.groupby("contrast", sort=False):
            by = {r["value"]: _ci(r) for _, r in h.iterrows()}
            lines.append(
                f"| {name} | {by.get('all', '-')} | {by.get(70.0, '-')} | {by.get(130.0, '-')} |"
            )
        r = rec[(rec["model"] == model) & (rec["attack"] == attack)]
        recovered = r["recovered_at"].iloc[0] if len(r) else None
        recovered = (
            "not within the session" if pd.isna(recovered) else f"P{int(recovered)}"
        )
        lines += [
            "",
            f"Text effect below {analysis.MIN_EFFECT} after the messages: {recovered}.",
            "",
            "| period | RN | PN | RA | PA | Bayes | text [lo, hi] | price | interaction |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        cg = cur[(cur["model"] == model) & (cur["attack"] == attack)]
        for _, c in cg.iterrows():
            text = f"{f(c['text'])} [{f(c['text_lo'])}, {f(c['text_hi'])}]"
            lines.append(
                f"| {c['period']} | {f(c['RN'])} | {f(c['PN'])} | {f(c['RA'])} | {f(c['PA'])} | "
                f"{f(c['bayes'])} | {text} | {f(c['price'])} | {f(c['interaction'])} |"
            )
        lines.append("")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return {"contrasts": con, "curves": cur, "recovery": rec}
