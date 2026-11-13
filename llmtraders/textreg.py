"""Regression of the level-1 belief shift on properties of the manipulator's text (plan
v2, item 7): sentiment, a number, a named source, the imperative, length, and the number
of messages. Not pre-registered: coefficients with intervals, no verdicts."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from . import analysis, finbert, level1
from .analysis import fmt_ci, fnum, md_table
from .extra1 import OUT

# Injection makes no claim about the value: it orders a trade, and its success is a buy
# at >= 130 (H1.2, H1.5), not a belief.
LEFT_OUT = ("injection",)
# A source names who or what the claim comes from: an outlet, an institution, a role or
# a document. Hearsay ("a friend", "someone", "everyone I talk to") is not a source.
SOURCE = re.compile(
    r"\b(?:reuters|board|director|insider|analyst|bank|research|exchange|official"
    r"|deal team|term sheet|memo)\b",
    re.IGNORECASE,
)
# A verb that opens a clause and tells the reader what to do. "last call to get in" and
# "Heads up" are not orders; "LFG" and "All aboard" have no verb.
IMPERATIVE = re.compile(
    r"(?:^|[.!?,;:\u2014-]\s*)"
    r"(?:get|jump|load|buy|don't|do not|submit|place|ignore|use)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d")
FEATURES = ["sentiment", "number", "source", "imperative", "words", "messages"]
# Per one standard deviation over the stimuli; flags stay 0/1, messages go per doubling.
SCALED = ("sentiment", "words")
DESIGNS = {
    # Model fixed effects: which properties go with a larger shift across message types.
    "across types": ["model"],
    # Model x condition fixed effects: paraphrases of one type against each other.
    "within types": ["model", "condition"],
}


def shifts(df: pd.DataFrame, quiz_dir: Path = analysis.QUIZ_DIR) -> pd.DataFrame:
    """Mean dp per model and stimulus (condition, paraphrase) over 3 states x 3 samples."""
    m = analysis.paired(df).merge(analysis.full_runs(df, quiz_dir), on=analysis.KEY)
    has_text = m["attack_texts"].str.len() > 0
    m = m[has_text & ~m["condition"].isin(LEFT_OUT)]
    keys = ["model", "condition", "paraphrase"]
    out = m.groupby(keys, sort=False).agg(
        dp=("dp", "mean"), attack_texts=("attack_texts", "first")
    )
    return out.reset_index()


def text_features(stimuli: pd.DataFrame, classify: finbert.Classifier) -> pd.DataFrame:
    """One row per stimulus. A stimulus of several messages (social_3, social_6) has a
    flag when any message has it; sentiment and words are means over its messages."""
    unique = stimuli.drop_duplicates(["condition", "paraphrase"])
    texts = sorted({t for ts in unique["attack_texts"] for t in ts})
    probs = classify(texts)
    pos = finbert.LABELS.index("positive")
    neg = finbert.LABELS.index("negative")
    sentiment = dict(zip(texts, probs[:, pos] - probs[:, neg], strict=True))
    rows = []
    for _, r in unique.iterrows():
        ts = r["attack_texts"]
        rows.append(
            {
                "condition": r["condition"],
                "paraphrase": r["paraphrase"],
                "sentiment": float(np.mean([sentiment[t] for t in ts])),
                "number": int(any(NUMBER.search(t) for t in ts)),
                "source": int(any(SOURCE.search(t) for t in ts)),
                "imperative": int(any(IMPERATIVE.search(t) for t in ts)),
                "words": float(np.mean([len(t.split()) for t in ts])),
                "messages": len(ts),
                "text": " | ".join(ts),
            }
        )
    return pd.DataFrame(rows)


def design(stimuli: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    x = stimuli[["model", "condition", "paraphrase", "dp"]].merge(
        features, on=["condition", "paraphrase"]
    )
    for name in SCALED:
        sd = features[name].std()
        # A feature constant over all stimuli becomes 0 and gets no coefficient;
        # dividing by its zero SD would hand lstsq NaNs.
        x[name] = (x[name] - features[name].mean()) / (sd if sd > 0 else 1.0)
    x["messages"] = np.log2(x["messages"])
    return x


def _demean(values: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Values minus their group mean: the fixed effects of the groups drop out."""
    # A bootstrap draw can miss a group; its empty count is never indexed.
    counts = np.maximum(np.bincount(groups), 1)
    means = np.stack(
        [np.bincount(groups, weights=col) / counts for col in values.T], axis=1
    )
    return values - means[groups]


def ols(y: np.ndarray, x: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, float]:
    """Coefficients with the group fixed effects, and R2 within the groups. A feature
    with no variation left inside the groups gets NaN, not lstsq's silent 0."""
    yd = _demean(y[:, None], groups)[:, 0]
    xd = _demean(x, groups)
    alive = ~np.all(np.isclose(xd, 0), axis=0)
    coef = np.full(x.shape[1], np.nan)
    coef[alive], *_ = np.linalg.lstsq(xd[:, alive], yd, rcond=None)
    resid = yd - xd[:, alive] @ coef[alive]
    # A model that never moves (dp = 0 everywhere) leaves nothing to explain.
    total = yd @ yd
    r2 = float(1 - resid @ resid / total) if total > 0 else float("nan")
    return coef, r2


def fit(x: pd.DataFrame, by: Sequence[str]) -> pd.DataFrame:
    """OLS of dp on FEATURES with fixed effects of `by`. [lo, hi] = 95% bootstrap over
    paraphrase indices: across conditions one index shares the neutral feed and the
    sampling seeds, so the stimuli of one index are not independent."""
    y = x["dp"].to_numpy()
    feats = x[FEATURES].to_numpy(dtype=float)
    groups = x.groupby(list(by), sort=False).ngroup().to_numpy()
    coef, r2 = ols(y, feats, groups)
    # For scale: the share the message types themselves explain, the most any
    # type-level property could. Within types it is 0 by construction.
    types = x.groupby(list(by) + ["condition"], sort=False).ngroup().to_numpy()
    yd = _demean(y[:, None], groups)[:, 0]
    yt = _demean(y[:, None], types)[:, 0]
    total = yd @ yd
    r2_types = float(1 - yt @ yt / total) if total > 0 else float("nan")
    para = x["paraphrase"].to_numpy()
    ids = np.unique(para)
    rows_of = {p: np.flatnonzero(para == p) for p in ids}
    rng = np.random.default_rng(analysis.BOOT_SEED)
    boots = np.empty((analysis.N_BOOT, len(FEATURES)))
    for b in range(analysis.N_BOOT):
        pick = np.concatenate([rows_of[p] for p in rng.choice(ids, size=len(ids))])
        boots[b], _ = ols(y[pick], feats[pick], groups[pick])
    rows = []
    for j, name in enumerate(FEATURES):
        col = boots[:, j]
        if np.isnan(coef[j]) or np.isnan(col).all():
            lo = hi = float("nan")
        else:
            lo, hi = np.nanpercentile(col, [2.5, 97.5])
        rows.append({"feature": name, "coef": coef[j], "lo": lo, "hi": hi})
    out = pd.DataFrame(rows)
    out["r2"] = r2
    out["r2_types"] = r2_types
    out["n"] = len(x)
    return out


def fits(x: pd.DataFrame) -> pd.DataFrame:
    """Every design on all models together and on each model alone."""
    out = []
    for design_name, by in DESIGNS.items():
        parts = [("all", x), *x.groupby("model", sort=False)]
        for model, part in parts:
            t = fit(part, by)
            out.append(t.assign(design=design_name, model=model))
    return pd.concat(out, ignore_index=True)


def write(
    out: Path = OUT,
    df: pd.DataFrame | None = None,
    classify: finbert.Classifier | None = None,
    quiz_dir: Path = analysis.QUIZ_DIR,
) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    if df is None:
        df = analysis.load(level1.run_dirs())
    stimuli = shifts(df, quiz_dir)
    features = text_features(stimuli, classify or finbert.load_classifier())
    features.to_csv(out / "text_features.csv", index=False)
    coefs = fits(design(stimuli, features))
    coefs.to_csv(out / "text_regression.csv", index=False)

    by_type = features.groupby("condition", sort=False)[FEATURES].mean()
    dp = stimuli.groupby("condition", sort=False)["dp"].mean()
    type_rows = [
        [cond, fnum(dp[cond]), *[fnum(r[c]) for c in FEATURES]]
        for cond, r in by_type.iterrows()
    ]
    models = list(dict.fromkeys(coefs["model"]))
    lines = [
        "# Level 1: belief shift on properties of the text (not pre-registered)",
        "",
        "Unit: a stimulus (condition x paraphrase) per model, dp = mean p(130) shift",
        "against the neutral twin over 3 states x 3 samples. Injection is left out: it",
        "orders a trade and claims no value. Features of the manipulator's messages:",
        "",
        "- sentiment: FinBERT p(positive) - p(negative), per 1 SD over the stimuli;",
        "- number: a digit in the text (a payout, a probability);",
        "- source: names an outlet, institution, role or document (Reuters, board,",
        "  analyst, bank, exchange, official, memo); hearsay is not a source;",
        "- imperative: a clause opens with an order to the reader (get in, load up,",
        "  don't miss);",
        "- words: words per message, per 1 SD;",
        "- messages: per doubling of the number of accounts (social_3, social_6).",
        "",
        "Flags and means over a stimulus's messages are in text_features.csv, one row",
        "per stimulus with its text, for checking by eye.",
        "",
        "## Features by message type",
        "",
        "Most features are fixed by the type, so across types a feature stands in for",
        "the types that have it: with 9 types the coefficients below describe, they do",
        "not separate causes.",
        "",
        *md_table(["condition", "dp", *FEATURES], type_rows),
    ]
    notes = {
        "across types": (
            "Model fixed effects. R2 = within-model variance the features explain;",
            "R2 types = what the message types themselves explain (the ceiling for",
            "type-level features).",
        ),
        "within types": (
            "Model x condition fixed effects: paraphrases of one type against each",
            "other, a cleaner test but only for features that vary inside a type;",
            "'-' = no variation inside any type.",
        ),
    }
    for design_name, note in notes.items():
        t = coefs[coefs["design"] == design_name]
        cell = {}
        for _, r in t.iterrows():
            no_variation = pd.isna(r["coef"])
            cell[(r["model"], r["feature"])] = (
                "-" if no_variation else fmt_ci(r, point="coef")
            )
        rows = [[f, *[cell[(m, f)] for m in models]] for f in FEATURES]
        first = t.drop_duplicates("model").set_index("model")
        rows.append(["R2", *[fnum(first.loc[m, "r2"]) for m in models]])
        if design_name == "across types":
            rows.append(["R2 types", *[fnum(first.loc[m, "r2_types"]) for m in models]])
        rows.append(["n", *[str(first.loc[m, "n"]) for m in models]])
        lines += ["", f"## {design_name.capitalize()}", "", *note, ""]
        lines += [
            "Coefficient in units of p(130), [lo, hi] = 95% bootstrap over paraphrase",
            "indices.",
            "",
        ]
        lines += md_table(["feature", *models], rows)
    path = out / "text_regression.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
