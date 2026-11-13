"""Additional analyses of variant C (exploratory, no verdicts): what the LLM manipulator
writes, set against the message bank, and whose orders move the price in the mixed
market."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import bank, extra2, finbert, level1, level2, level2c, textreg
from .analysis import fmt_ci, fnum, md_table
from .chat import MessageBank

LLM_PIECE = "llm_manipulator"
MIXED_PIECE = "mixed"
# Flags beside the text-regression features: what the zero-shot writer leans on.
MESSAGE_FLAGS = {
    "claims 130": r"\b130\b",
    "cites the news": r"\b(?:news|signal|GOOD|P4|period 4)\b",
    "first person": r"\b(?:I think|I believe|I'm|I am|I've)\b",
}
Encoder = Callable[[list[str]], np.ndarray]


def bank_types() -> list[str]:
    """Message types of the main level-1 grid (social once for its three doses)."""
    conditions = level1.load_config()["conditions"]
    attacks = [c for c in conditions if c["kind"] == "attack" and not c.get("extra")]
    return list(dict.fromkeys(c["type"] for c in attacks))


def message_table(
    texts: list[str], messages: MessageBank, classify: finbert.Classifier
) -> pd.DataFrame:
    """One row per text, LLM messages and bank paraphrases alike: its origin ("llm" or
    the bank type), the text-regression features and MESSAGE_FLAGS."""
    rows = [("llm", i, t) for i, t in enumerate(texts)]
    for name in bank_types():
        paraphrases = messages.types[name].paraphrases
        rows += [(name, i, t) for i, t in enumerate(paraphrases)]
    stimuli = pd.DataFrame(rows, columns=["condition", "paraphrase", "text"])
    stimuli["attack_texts"] = stimuli["text"].map(lambda t: [t])
    t = textreg.text_features(stimuli, classify).rename(columns={"condition": "origin"})
    for name, pattern in MESSAGE_FLAGS.items():
        t[name] = t["text"].str.contains(pattern, regex=True).astype(int)
    return t


def nearest_types(
    texts: list[str], messages: MessageBank, encode: Encoder
) -> pd.Series:
    """For each text, the bank type whose paraphrases it is closest to on average
    (cosine of normalised sentence embeddings)."""
    names = bank_types()
    vectors = encode(texts)
    means = []
    for name in names:
        ref = encode(messages.types[name].paraphrases)
        means.append((vectors @ ref.T).mean(axis=1))
    best = np.argmax(np.stack(means, axis=1), axis=1)
    return pd.Series([names[i] for i in best], name="nearest")


def mixed_orders(piece_dir: Path, cfg: dict[str, Any]) -> pd.DataFrame:
    """Order metrics of each model in the mixed market, attack minus control."""
    periods = cfg["main"]["analysis"]["periods"]
    d = extra2.decisions(piece_dir, cfg)
    shifts = extra2.order_shifts(d, periods, by=("model",))
    return extra2.estimates(shifts, extra2.ORDER_METRICS, by=("model",))


def write(
    out: Path,
    config: Path = level2.CONFIG,
    classify: finbert.Classifier | None = None,
    encode: Encoder | None = None,
) -> Path:
    cfg = level2.load_config(config)
    messages = MessageBank.load()
    texts = level2c.llm_messages(Path(out) / LLM_PIECE)
    table = message_table(texts, messages, classify or finbert.load_classifier())
    llm = table[table["origin"] == "llm"].reset_index(drop=True)
    llm["nearest"] = nearest_types(texts, messages, encode or bank._encoder())
    llm.to_csv(Path(out) / "llm_messages.csv", index=False)
    # One message each, so the number of messages is always 1 here.
    single = [f for f in textreg.FEATURES if f != "messages"]
    features = [*single, *MESSAGE_FLAGS]
    means = table.groupby("origin", sort=False)[features].mean()
    orders = mixed_orders(Path(out) / MIXED_PIECE, cfg)
    orders.to_csv(Path(out) / "mixed_orders.csv", index=False)

    writer = cfg["variant_c"]["pieces"][LLM_PIECE]["writer"]
    lines = [
        f"# Variant C, additional analyses (exploratory): {Path(out).name}",
        "",
        f"## What the LLM manipulator ({writer}) writes",
        "",
        f"{len(texts)} messages posted, {len(set(texts))} different. Features as in the",
        "level-1 text regression (sentiment = FinBERT p(positive) - p(negative); flags",
        "are shares of messages), next to the bank types of the main grid. 'number' is",
        "any digit, so 'P4' counts; 'claims 130' is the payout claim itself.",
        "",
    ]
    rows = [[src, *[fnum(r[c]) for c in features]] for src, r in means.iterrows()]
    lines += md_table(["origin", *features], rows)
    share = llm["nearest"].value_counts(normalize=True)
    nearest = ", ".join(f"{name} {fnum(v)}" for name, v in share.items())
    lines += [
        "",
        f"Closest bank type (mean cosine of {bank.EMBED_MODEL} embeddings to its",
        f"paraphrases), share of messages: {nearest}.",
        "",
        f"## Mixed market: whose orders move the price ({MIXED_PIECE})",
        "",
        "Per model, the traders' orders over the window, attack minus control; the",
        "metrics of extra/analyses.md of the main runs. [lo, hi] = 95% bootstrap over",
        "seeds within each value.",
        "",
    ]
    pooled = orders[orders["value"] == "all"]
    models = list(dict.fromkeys(pooled["model"]))
    rows = []
    for metric in extra2.ORDER_METRICS:
        cells = []
        for model in models:
            r = pooled[(pooled["metric"] == metric) & (pooled["model"] == model)]
            r = r.iloc[0]
            ci = fmt_ci(r)
            cells.append(f"{fnum(r['control'], 3)} / {ci}")
        rows.append([metric, *cells])
    lines += [
        "Cell: control level / attack minus control.",
        "",
        *md_table(["metric", *models], rows),
    ]
    path = Path(out) / "extra.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
