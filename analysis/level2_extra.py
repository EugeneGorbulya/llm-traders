"""Additional level-2 analyses for the report into <dir>/extra/ (no model calls):
how injection moves the price, who pays for the manipulation."""

import argparse
from pathlib import Path

from llmtraders.extra2 import write

p = argparse.ArgumentParser()
p.add_argument("dir", type=Path, help="results/level2/main/<version>/<model>/")
a = p.parse_args()

if not any(a.dir.glob("*/*/sessions.jsonl")):
    p.error(f"no <configuration>/<seed set>/sessions.jsonl in {a.dir}")
print(write(a.dir).read_text(encoding="utf-8"))
