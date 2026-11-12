"""Level-2 main runs: K0, K1, K3, S x seeds x control and attack arms (configs/level2.yaml)."""

import argparse

from llmtraders import level2

p = argparse.ArgumentParser()
p.add_argument("--model", required=True, help="a name from configs/models.yaml")
p.add_argument(
    "--topup",
    action="store_true",
    help="the extra seeds of the pre-registered top-up rule",
)
a = p.parse_args()

seed_set = "topup_seeds" if a.topup else "seeds"
print(level2.run(a.model, seed_set=seed_set))
