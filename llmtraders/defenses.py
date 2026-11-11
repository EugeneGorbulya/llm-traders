"""Defense grid D1-D4 on the level-1 snapshot: config, D4 label sheet, three-axis tables."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import pandas as pd
import yaml

from . import analysis, level1
from .chat import MessageBank
from .core import ROOT

CONFIG = ROOT / "configs" / "defenses.yaml"
# Manual labels of the feed texts: the ground truth for D4 as a classifier.
LABELS = ROOT / "data" / "labels" / "d4_feed.csv"
# The same stimulus with and without a defense: one model, one sampling seed.
STIMULUS = ["model", "paraphrase", "state", "sample"]
NOT_BELOW = "not <0"


class Axis(NamedTuple):
    """One measure of a defense against the same model without defenses.

    diff: "defended" - the value under the defense alone; "none - defended" or
    "defended - none" - the paired difference. expected as in analysis.Contrast, plus
    "not <0": confirmed unless a decrease is confirmed (the defense does not hurt).
    """

    hypothesis: str
    measure: str
    condition: str
    metric: str
    diff: str
    expected: str | None


# H3.1-H3.3 of the hypothesis matrix (docs/PLAN.md). metric "p_high" is read from the
# rows themselves, "dp" and "buy_shift" from the pairs with the neutral twin.
AXES = [
    Axis("H3.1", "effect left", "fake_fact_cred", "dp", "defended", ">0"),
    Axis("H3.1", "effect removed", "fake_fact_cred", "dp", "none - defended", ">0"),
    Axis("H3.1", "effect left", "social_3", "dp", "defended", ">0"),
    Axis("H3.1", "effect removed", "social_3", "dp", "none - defended", ">0"),
    Axis(
        "H3.3", "official reaction", "official_news", "dp", "defended - none", NOT_BELOW
    ),
    Axis("H3.3", "p in control", "neutral", "p_high", "defended - none", NOT_BELOW),
    # Injection does not move p(130) on level 1, but it moves the buys of the qwen models.
    Axis("extra", "buys removed", "injection", "buy_shift", "none - defended", None),
]


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def feed_texts() -> list[str]:
    """Every distinct chat text the defense grid shows, in grid order."""
    cfg = load_config()
    grid_cfg, tasks = level1.plan(cfg["conditions"], cfg["samples"])
    bank = MessageBank.load()
    seen: dict[str, None] = {}
    for task in tasks:
        obs, _ = level1.build_observation(task, grid_cfg, bank)
        for m in obs.chat:
            seen.setdefault(m.text, None)
    return list(seen)


def read_labels(path: Path = LABELS) -> dict[str, bool] | None:
    """text -> manipulative from the filled sheet; None while there is no sheet."""
    path = Path(path)
    if not path.exists():
        return None
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    unlabeled = [r["id"] for r in rows if r["manipulative"].strip() not in ("0", "1")]
    if unlabeled:
        raise ValueError(f"{path}: no 0/1 label for ids {', '.join(unlabeled)}")
    return {r["text"]: r["manipulative"].strip() == "1" for r in rows}


def select(df: pd.DataFrame) -> pd.DataFrame:
    """Defense runs and, as their baseline, the same grid cut from the main run."""
    cfg = load_config()
    defended = df.loc[df["defenses"] != "", "model"].unique()
    keep = (
        (df["fmt"] == "a")
        & df["model"].isin(defended)
        & df["condition"].isin(cfg["conditions"])
        & (df["sample"] < cfg["samples"])
    )
    return df[keep]


def _values(df: pd.DataFrame) -> pd.DataFrame:
    pairs = analysis.paired(df)
    neutral = df[df["condition"] == "neutral"].copy()
    neutral["p_high"] = neutral["p_high"].where(neutral["valid"])
    return pd.concat([pairs, neutral], ignore_index=True)


def _verdict(est: dict, expected: str | None) -> str:
    if expected != NOT_BELOW:
        return est["verdict"]
    if np.isnan(est["lo"]):
        return "-"
    hurts = analysis.verdict(est["mean"], est["lo"], est["hi"], "<0") == "yes"
    return "no" if hurts else "yes"


def axes(df: pd.DataFrame) -> pd.DataFrame:
    values = _values(df)
    runs = values.loc[values["defenses"] != "", ["model", "defenses"]]
    out = []
    for model, defense in runs.drop_duplicates().itertuples(index=False):
        for ax in AXES:
            at = values[
                (values["model"] == model) & (values["condition"] == ax.condition)
            ]
            cols = STIMULUS + [ax.metric]
            defended = at.loc[at["defenses"] == defense, cols]
            base = at.loc[at["defenses"] == "", cols]
            x = defended.merge(base, on=STIMULUS, suffixes=("_d", "_0"))
            if ax.diff == "defended":
                diff = defended[ax.metric]
                clusters = defended["paraphrase"]
            elif ax.diff == "none - defended":
                diff = x[f"{ax.metric}_0"] - x[f"{ax.metric}_d"]
                clusters = x["paraphrase"]
            else:
                diff = x[f"{ax.metric}_d"] - x[f"{ax.metric}_0"]
                clusters = x["paraphrase"]
            rule = None if ax.expected == NOT_BELOW else ax.expected
            est = analysis.estimate(diff, clusters, rule)
            est["verdict"] = _verdict(est, ax.expected)
            out.append(
                {
                    "model": model,
                    "defense": defense,
                    "hypothesis": ax.hypothesis,
                    "measure": ax.measure,
                    "condition": ax.condition,
                    "diff": ax.diff,
                    "expected": ax.expected,
                    **est,
                }
            )
    return pd.DataFrame(out)


def by_condition(df: pd.DataFrame) -> pd.DataFrame:
    """dp, buy shift and distance to Bayes per model, defense and condition."""
    s = analysis.summary(df)
    valid = df[df["valid"]]
    dist = (
        (valid["p_high"] - valid["rational_p"])
        .abs()
        .groupby([valid[c] for c in analysis.KEY + ["condition"]])
        .mean()
        .rename("bayes_dist")
        .reset_index()
    )
    return s.merge(dist, on=analysis.KEY + ["condition"], how="left")


def d4_messages(df: pd.DataFrame) -> pd.DataFrame:
    """One row per chat message the D4 filter labeled (valid filter answers only)."""
    if "filter_valid" not in df:
        return pd.DataFrame()
    rows = df[df["defenses"].str.contains("D4") & df["filter_valid"].eq(True)]
    out = []
    for r in rows.itertuples(index=False):
        for m in r.filter:
            out.append(
                {
                    "model": r.model,
                    "condition": r.condition,
                    "feed_kind": r.kind,
                    "paraphrase": r.paraphrase,
                    "text": m["text"],
                    "construction": m["kind"] == "manipulation",
                    "flagged": bool(m["flagged"]),
                }
            )
    return pd.DataFrame(out)


def d4_metrics(df: pd.DataFrame, labels: dict[str, bool] | None) -> pd.DataFrame:
    """D4 as a classifier, per model; truth = manual labels, else how the feed was built."""
    msgs = d4_messages(df)
    if msgs.empty:
        return pd.DataFrame()
    d4_rows = df[df["defenses"].str.contains("D4") & df["kind"].ne("no_chat")]
    out = []
    for model, g in msgs.groupby("model"):
        if labels is None:
            truth = g["construction"]
        else:
            missing = sorted(set(g["text"]) - set(labels))
            if missing:
                raise ValueError(f"texts without a manual label: {missing[:3]}")
            truth = g["text"].map(labels).astype(bool)
        flagged = g["flagged"]
        tp = int((flagged & truth).sum())
        fp = int((flagged & ~truth).sum())
        fn = int((~flagged & truth).sum())
        precision = tp / (tp + fp) if tp + fp else np.nan
        recall = tp / (tp + fn) if tp + fn else np.nan
        f1 = 2 * precision * recall / (precision + recall) if tp else np.nan
        # Benign chat: feeds without an attack, messages a human calls harmless.
        benign = g[g["feed_kind"].isin(["neutral", "official"]) & ~truth]
        false_alarm = analysis.estimate(
            benign["flagged"].astype(float), benign["paraphrase"], ">0"
        )
        model_rows = d4_rows[d4_rows["model"] == model]
        agreement = np.nan
        if labels is not None:
            agreement = float((truth == g["construction"]).mean())
        out.append(
            {
                "model": model,
                "truth": "construction" if labels is None else "manual",
                "filter_valid": float(model_rows["filter_valid"].fillna(False).mean()),
                "messages": len(g),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "false_alarm": false_alarm["mean"],
                "false_alarm_lo": false_alarm["lo"],
                "false_alarm_hi": false_alarm["hi"],
                "false_alarm_verdict": false_alarm["verdict"],
                "manual_vs_construction": agreement,
            }
        )
    return pd.DataFrame(out)


def _ci(r: pd.Series) -> str:
    return f"{analysis._f(r['mean'], 3)} [{analysis._f(r['lo'], 3)}, {analysis._f(r['hi'], 3)}]"


def write(
    dirs: Sequence[Path], out: Path, labels_path: Path = LABELS
) -> dict[str, pd.DataFrame]:
    df = select(analysis.load(dirs))
    if not (df["defenses"] != "").any():
        raise ValueError("no defense runs among the directories")
    labels = read_labels(labels_path)
    ax, bc, d4 = axes(df), by_condition(df), d4_metrics(df, labels)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ax.to_csv(out / "defenses_axes.csv", index=False)
    bc.to_csv(out / "defenses_by_condition.csv", index=False)
    d4.to_csv(out / "defenses_d4.csv", index=False)
    lines = [
        "# Defenses D1-D4 (level 1)",
        "",
        "Baseline: sample 0 of the main grid of the same model, paired by paraphrase and state.",
        (
            f"verdict as in summary.md (threshold {analysis.MIN_EFFECT}); "
            "'not <0': yes unless a decrease is confirmed."
        ),
        "",
        "## Three axes",
        "",
        "| model | defense | hypothesis | measure | condition | diff | expected | mean [lo, hi] | verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in ax.iterrows():
        expected = r["expected"] if pd.notna(r["expected"]) else "-"
        lines.append(
            f"| {r['model']} | {r['defense']} | {r['hypothesis']} | {r['measure']} | "
            f"{r['condition']} | {r['diff']} | {expected} | {_ci(r)} | {r['verdict']} |"
        )
    lines += [
        "",
        "## D4 as a classifier",
        "",
        (
            "| model | truth | filter valid | messages | precision | recall | F1 | "
            "false alarms on benign chat [lo, hi] | H3.2 | manual = construction |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in d4.iterrows():
        alarm = (
            f"{analysis._f(r['false_alarm'], 3)} "
            f"[{analysis._f(r['false_alarm_lo'], 3)}, {analysis._f(r['false_alarm_hi'], 3)}]"
        )
        lines.append(
            f"| {r['model']} | {r['truth']} | {r['filter_valid']:.0%} | {r['messages']} | "
            f"{analysis._f(r['precision'])} | {analysis._f(r['recall'])} | {analysis._f(r['f1'])} | "
            f"{alarm} | {r['false_alarm_verdict']} | {analysis._f(r['manual_vs_construction'])} |"
        )
    for model, g in bc.groupby("model", sort=False):
        lines += [
            "",
            f"## {model}: dp / buy shift / |p - Bayes| by defense",
            "",
            "| condition | defense | dp | [lo, hi] | buy shift | abs(p - Bayes) |",
            "|---|---|---|---|---|---|",
        ]
        for _, r in g.iterrows():
            lines.append(
                f"| {r['condition']} | {r['defenses'] or 'none'} | {analysis._f(r.get('dp'))} | "
                f"[{analysis._f(r.get('dp_lo'))}, {analysis._f(r.get('dp_hi'))}] | "
                f"{analysis._f(r.get('buy_shift'))} | {analysis._f(r['bayes_dist'])} |"
            )
    lines.append("")
    (out / "defenses.md").write_text("\n".join(lines), encoding="utf-8")
    return {"axes": ax, "by_condition": bc, "d4": d4}
