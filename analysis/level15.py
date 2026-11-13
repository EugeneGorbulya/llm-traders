"""Build level-1.5 tables from one or more run directories."""

import argparse
from pathlib import Path

from llmtraders import level15
from llmtraders.analysis15 import write
from llmtraders.results import RESULTS

p = argparse.ArgumentParser()
# No directories: the runs with every seed of configs/level15.yaml (not the smoke runs).
p.add_argument("dirs", nargs="*", type=Path)
p.add_argument("--out", type=Path, default=RESULTS / "level15")
a = p.parse_args()
a.dirs = a.dirs or level15.full_runs()

missing = [str(d) for d in a.dirs if not (d / "sessions.jsonl").exists()]
if missing:
    p.error(f"no sessions.jsonl in: {', '.join(missing)}")
write(a.dirs, a.out)
print(a.out / "summary.md")
