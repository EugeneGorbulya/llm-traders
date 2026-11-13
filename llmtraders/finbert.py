"""FinBERT trader: the sentiment-classifier baseline of level 1 on the same feeds."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import level1
from .analysis import cluster_ci
from .chat import MessageBank
from .core import Observation
from .level1 import build_observation, plan
from .llm.log import git_commit
from .results import write_jsonl

FINBERT = "ProsusAI/finbert"
# Pinned: the model page was updated on 12.10.2026, and a re-run must score with
# the same weights.
FINBERT_REVISION = "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
LABELS = ("positive", "negative", "neutral")
OUT = level1.FINBERT_DIR
BATCH = 64

# texts -> probabilities, one row per text, columns in LABELS order.
Classifier = Callable[[list[str]], np.ndarray]


def load_classifier() -> Classifier:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(FINBERT, revision=FINBERT_REVISION)
    model = AutoModelForSequenceClassification.from_pretrained(
        FINBERT, revision=FINBERT_REVISION
    ).eval()
    id2label = {i: label.lower() for i, label in model.config.id2label.items()}
    columns = [next(i for i, lab in id2label.items() if lab == name) for name in LABELS]

    def classify(texts: list[str]) -> np.ndarray:
        out = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            enc = tokenizer(batch, padding=True, truncation=True, return_tensors="pt")
            with torch.no_grad():
                logits = model(**enc).logits
            out.append(torch.softmax(logits, dim=-1)[:, columns].numpy())
        return np.concatenate(out)

    return classify


def texts_seen(obs: Observation) -> list[str]:
    """The text an LLM trader reads as news: official signals, then the chat feed."""
    # A sentence, not the prompt's "Period 4: GOOD": FinBERT labels that line neutral
    # and would not read official news at all.
    official = [
        f"Official news: the exchange published a {s.upper()} signal."
        for _, s in obs.official
    ]
    return official + [m.text for m in obs.chat]


def decide(probs: np.ndarray) -> tuple[str, int, float]:
    """Side, label votes and mean (p_positive - p_negative) of a feed.

    Every text votes with its FinBERT label: buy if positive texts outnumber negative
    ones, sell in the opposite case, hold on a tie. Votes need no threshold to tune.
    """
    if len(probs) == 0:
        return "hold", 0, 0.0
    pos, neg = LABELS.index("positive"), LABELS.index("negative")
    labels = probs.argmax(axis=1)
    votes = int((labels == pos).sum() - (labels == neg).sum())
    sentiment = float((probs[:, pos] - probs[:, neg]).mean())
    if votes > 0:
        side = "buy"
    elif votes < 0:
        side = "sell"
    else:
        side = "hold"
    return side, votes, sentiment


def run(out_dir: Path = OUT, classify: Classifier | None = None) -> Path:
    # One sample: FinBERT is deterministic, so a second sample would repeat the first.
    cfg, tasks = plan(samples=1)
    bank = MessageBank.load()
    seen = [(task, *build_observation(task, cfg, bank)) for task in tasks]
    unique = sorted({text for _, obs, _ in seen for text in texts_seen(obs)})
    classify = classify or load_classifier()
    probs = dict(zip(unique, classify(unique), strict=True))
    commit = git_commit()
    rows = []
    for task, obs, info in seen:
        feed = texts_seen(obs)
        feed_probs = np.array([probs[t] for t in feed]).reshape(len(feed), len(LABELS))
        side, votes, sentiment = decide(feed_probs)
        rows.append(
            {
                "version": cfg["version"],
                "bank_sha256": bank.sha256,
                "model": "finbert",
                "model_revision": FINBERT_REVISION,
                "git": commit,
                **task.__dict__,
                **info,
                "side": side,
                "votes": votes,
                "sentiment": sentiment,
            }
        )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "results.jsonl", rows)
    table(rows, out)
    return out


def table(rows: Sequence[dict[str, Any]], out: Path) -> pd.DataFrame:
    """Per condition: share of buys and shifts vs the neutral twin (same feed)."""
    df = pd.DataFrame(rows)
    df["buy"] = (df["side"] == "buy").astype(float)
    df["sell"] = (df["side"] == "sell").astype(float)
    twin = df[df["condition"] == "neutral"][["paraphrase", "state", "buy", "sentiment"]]
    pairs = df[~df["condition"].isin(["neutral", "no_chat"])].merge(
        twin, on=["paraphrase", "state"], suffixes=("", "_neu")
    )
    pairs["buy_shift"] = pairs["buy"] - pairs["buy_neu"]
    pairs["sentiment_shift"] = pairs["sentiment"] - pairs["sentiment_neu"]
    by_condition = {c: g for c, g in pairs.groupby("condition")}
    out_rows = []
    for condition, g in df.groupby("condition", sort=False):
        rec = {
            "condition": condition,
            "n": len(g),
            "buy": g["buy"].mean(),
            "sell": g["sell"].mean(),
            "sentiment": g["sentiment"].mean(),
        }
        p = by_condition.get(condition)
        if p is not None:
            buy_lo, buy_hi = cluster_ci(p["buy_shift"], p["paraphrase"])
            sent_lo, sent_hi = cluster_ci(p["sentiment_shift"], p["paraphrase"])
            rec.update(
                buy_shift=p["buy_shift"].mean(),
                buy_lo=buy_lo,
                buy_hi=buy_hi,
                sentiment_shift=p["sentiment_shift"].mean(),
                sentiment_lo=sent_lo,
                sentiment_hi=sent_hi,
            )
        out_rows.append(rec)
    t = pd.DataFrame(out_rows)
    t.to_csv(out / "summary.csv", index=False)
    lines = [
        "# FinBERT trader, level 1",
        "",
        f"`{FINBERT}` at `{FINBERT_REVISION[:12]}`.",
        "Each text (official news and chat) votes with its label: buy if positive > negative, sell if fewer, else hold.",
        "Shifts are paired with the neutral twin (same feed), [lo, hi] = 95% bootstrap over paraphrases.",
        "",
        "| condition | n | buy | sell | buy shift [lo, hi] | sentiment | sentiment shift [lo, hi] |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in t.iterrows():
        buy_shift = "-"
        sentiment_shift = "-"
        if pd.notna(r.get("buy_shift")):
            buy_shift = f"{r['buy_shift']:.2f} [{r['buy_lo']:.2f}, {r['buy_hi']:.2f}]"
            sentiment_shift = f"{r['sentiment_shift']:.2f} [{r['sentiment_lo']:.2f}, {r['sentiment_hi']:.2f}]"
        lines.append(
            f"| {r['condition']} | {r['n']} | {r['buy']:.2f} | {r['sell']:.2f} | {buy_shift} | "
            f"{r['sentiment']:.2f} | {sentiment_shift} |"
        )
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return t
