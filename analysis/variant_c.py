"""Build the descriptive tables of level-2 variant C from the runs of one model."""

import argparse
from pathlib import Path

from llmtraders.level2c import write

p = argparse.ArgumentParser()
p.add_argument("dir", type=Path, help="results/level2/variant_c/<version>/<model>/")
a = p.parse_args()

if not any(a.dir.glob("*/*/*/sessions.jsonl")):
    p.error(f"no <piece>/<configuration>/<seed set>/sessions.jsonl in {a.dir}")
write(a.dir)
print(a.dir / "summary.md")
