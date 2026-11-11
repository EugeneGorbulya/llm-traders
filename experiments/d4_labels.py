"""Write the blank sheet data/labels/d4_feed.csv for labeling the feed by hand."""

import csv
import random

from llmtraders import defenses

path = defenses.LABELS
if path.exists():
    raise SystemExit(f"{path} already exists: labels are never overwritten")
texts = defenses.feed_texts()
# Shuffled, so that the labeler does not see the attacks grouped by type.
random.Random(0).shuffle(texts)
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["id", "text", "manipulative", "note"])
    for i, text in enumerate(texts, start=1):
        w.writerow([i, text, "", ""])
print(f"{path}: {len(texts)} texts")
