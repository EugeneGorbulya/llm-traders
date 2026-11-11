"""Level-2 calibration: K0 sessions without a manipulator, turnover and price against the rational one."""

import argparse

from llmtraders import level2

p = argparse.ArgumentParser()
p.add_argument("--model", required=True, help="a name from configs/models.yaml")
a = p.parse_args()

out = level2.calibrate(a.model)
print((out / "summary.md").read_text(encoding="utf-8"))
print(out)
