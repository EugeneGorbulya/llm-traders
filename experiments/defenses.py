"""Run the defense grid (configs/defenses.yaml) into results/level1/<model>_<defense>/."""

import argparse

from llmtraders import defenses, level1

p = argparse.ArgumentParser()
p.add_argument(
    "--model", required=True, help="comma-separated names from configs/models.yaml"
)
a = p.parse_args()

cfg = defenses.load_config()
for m in a.model.split(","):
    for d in cfg["defenses"]:
        out = level1.run(
            m, conditions=cfg["conditions"], samples=cfg["samples"], defenses=[d]
        )
        print(out)
