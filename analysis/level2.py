"""Build level-2 tables (docs/prereg/l2.md) from the main runs of one model."""

import argparse
from pathlib import Path

from llmtraders.analysis2 import write

p = argparse.ArgumentParser()
p.add_argument("dir", type=Path, help="results/level2/main/<version>/<model>/")
a = p.parse_args()

if not any(a.dir.glob("*/*/sessions.jsonl")):
    p.error(f"no <configuration>/<seed set>/sessions.jsonl in {a.dir}")
write(a.dir)
print(a.dir / "summary.md")
