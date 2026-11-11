"""Build the defense tables from the level-1 run directories (with and without defenses)."""

import argparse
from pathlib import Path

from llmtraders.defenses import write
from llmtraders.results import RESULTS

p = argparse.ArgumentParser()
p.add_argument("dirs", nargs="+", type=Path)
p.add_argument("--out", type=Path, default=RESULTS / "level1")
a = p.parse_args()

missing = [str(d) for d in a.dirs if not (d / "results.jsonl").exists()]
if missing:
    p.error(f"no results.jsonl in: {', '.join(missing)}")
write(a.dirs, a.out)
print(a.out / "defenses.md")
