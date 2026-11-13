"""Build level-1 tables from one or more run directories."""

import argparse
from pathlib import Path

from llmtraders import level1
from llmtraders.analysis import write
from llmtraders.results import RESULTS

p = argparse.ArgumentParser()
# No directories: every level-1 run (results/level1/*/ would also catch extra/).
p.add_argument("dirs", nargs="*", type=Path)
p.add_argument("--out", type=Path)
a = p.parse_args()
a.dirs = a.dirs or level1.run_dirs()

missing = [str(d) for d in a.dirs if not (d / "results.jsonl").exists()]
if missing:
    p.error(f"no results.jsonl in: {', '.join(missing)}")
out = a.out or (a.dirs[0] if len(a.dirs) == 1 else RESULTS / "level1")
write(a.dirs, out)
print(out / "summary.md")
