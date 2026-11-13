"""Rebuild every table and figure of the report from results/ (run logs and cache) with no
model calls: the analysis scripts of the README, in order. FinBERT and the sentence
encoder run locally; LLM outputs are only read."""

import subprocess
import sys
import time

from llmtraders import level2

cfg = level2.load_config()
main = str(level2.result_root("main", cfg))
variant_c = str(level2.result_root("variant_c", cfg))
STEPS = [
    ("analysis.level1", []),
    ("analysis.defenses", []),
    ("analysis.level15", []),
    ("analysis.level1_extra", []),
    ("analysis.text_regression", []),
    ("analysis.cases", []),
    ("analysis.level2", [main]),
    ("analysis.level2_extra", [main]),
    ("analysis.variant_c", [variant_c]),
    ("analysis.figures", []),
    ("experiments.bank", []),
]

for module, args in STEPS:
    t0 = time.perf_counter()
    # A subprocess per step runs each script exactly as the README does.
    # check=False: on a failure the step's own output is printed before stopping.
    r = subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        print(r.stdout, r.stderr, sep="\n")
        sys.exit(f"{module} failed")
    print(f"{module}: {time.perf_counter() - t0:.0f} s", flush=True)
