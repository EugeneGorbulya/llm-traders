import numpy as np
import pandas as pd
import pytest

from llmtraders import finbert
from llmtraders.results import read_jsonl


def official_good_is_positive(texts):
    """Stand-in for FinBERT: an official GOOD is positive, BAD negative, the rest neutral."""
    probs = np.tile([0.0, 0.0, 1.0], (len(texts), 1))
    for i, text in enumerate(texts):
        if text.startswith("Official news") and "GOOD" in text:
            probs[i] = [1.0, 0.0, 0.0]
        elif text.startswith("Official news") and "BAD" in text:
            probs[i] = [0.0, 1.0, 0.0]
    return probs


def test_finbert_trader_votes_on_the_same_feeds(tmp_path):
    out = finbert.run(tmp_path, classify=official_good_is_positive)
    rows = read_jsonl(out / "results.jsonl")
    assert len(rows) == 363 and {r["sample"] for r in rows} == {0}
    t = pd.read_csv(out / "summary.csv").set_index("condition")
    # The extra GOOD turns a hold into a buy only in state "none"; with an earlier
    # GOOD the twin already buys, after a BAD the votes tie.
    assert t.loc["official_news", "buy_shift"] == pytest.approx(1 / 3)
    assert t.loc["hype", "buy_shift"] == 0
    assert finbert.decide(np.empty((0, 3))) == ("hold", 0, 0.0)
