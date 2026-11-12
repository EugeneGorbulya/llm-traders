"""Level-2 variant C (exploratory): crash attack, LLM manipulator, mixed market (configs/level2.yaml)."""

import argparse

from llmtraders import level2c

p = argparse.ArgumentParser()
p.add_argument(
    "--model", required=True, help="traders' model, a name from configs/models.yaml"
)
p.add_argument("--piece", action="append", help="run only this piece (repeatable)")
p.add_argument("--seeds", type=int, help="first N seeds of each value: a smoke run")
a = p.parse_args()

print(level2c.run(a.model, pieces=a.piece, seeds_per_value=a.seeds))
