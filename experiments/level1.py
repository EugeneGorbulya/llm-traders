"""Run the level-1 grid into results/level1/<model>/."""

import argparse
from collections import Counter

from llmtraders import level1

p = argparse.ArgumentParser()
p.add_argument("--model", help="comma-separated names from configs/models.yaml")
p.add_argument(
    "--limit", type=int, help="about this many calls (whole neutral-twin groups)"
)
p.add_argument("--conditions", help="comma-separated subset of configs/level1.yaml")
p.add_argument("--defenses", default="", help="e.g. D1 or D3,D4")
p.add_argument("--samples", type=int)
p.add_argument("--fmt", default="a", choices=["a", "b"])
p.add_argument("--dry-run", action="store_true", help="only count the calls")
a = p.parse_args()
if not a.model and not a.dry_run:
    p.error("нужен --model (или --dry-run)")
conditions = a.conditions.split(",") if a.conditions else None

if a.dry_run:
    _, tasks = level1.plan(conditions, a.samples, a.limit)
    for c, n in Counter(t.condition for t in tasks).items():
        print(f"{c:20s} {n}")
    print(f"{'total':20s} {len(tasks)}")
else:
    for m in a.model.split(","):
        out = level1.run(
            m,
            limit=a.limit,
            conditions=conditions,
            samples=a.samples,
            fmt=a.fmt,
            defenses=[d for d in a.defenses.split(",") if d],
        )
        print(out)
