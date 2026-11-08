"""Run level 1.5 into results/level15/<model>/."""

import argparse

from llmtraders import level15
from llmtraders.core import N_PERIODS

p = argparse.ArgumentParser()
p.add_argument("--model", help="comma-separated names from configs/models.yaml")
p.add_argument("--seeds", type=int, help="first N seeds of each final value")
p.add_argument("--dry-run", action="store_true", help="only count the sessions")
a = p.parse_args()
if not a.model and not a.dry_run:
    p.error("нужен --model (или --dry-run)")

if a.dry_run:
    sessions = level15.plan(level15.load_config(), a.seeds)
    print(f"{len(sessions)} sessions, {len(sessions) * N_PERIODS} calls at most")
else:
    for m in a.model.split(","):
        print(level15.run(m, seeds=a.seeds))
