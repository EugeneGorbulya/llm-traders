"""D4 filter on the manipulator's messages in the market: LLM-written (variant C) against the bank's (U2 K0)."""

import argparse

from llmtraders import level2, level2c
from llmtraders.results import RESULTS, make_client

p = argparse.ArgumentParser()
p.add_argument("--model", default="qwen3-4b", help="traders' model of the runs")
p.add_argument(
    "--filters", default="qwen3-4b,qwen3-14b", help="comma-separated filter models"
)
a = p.parse_args()

cfg = level2.load_config()
version = cfg["version"]
llm_arm = cfg["variant_c"]["pieces"]["llm_manipulator"]["attack"]
fake = cfg["main"]["attacks"][0]
c_dir = RESULTS / "level2" / "variant_c" / version / a.model
main_k0 = RESULTS / "level2" / "main" / version / a.model / level2c.CONFIGURATION
# The same seeds on both sides: the LLM piece runs the 20 seeds of the main runs.
sources = {
    llm_arm: (sorted((c_dir / "llm_manipulator").glob("*/*/sessions.jsonl")), llm_arm),
    f"bank {fake}": (sorted(main_k0.glob("*/sessions.jsonl")), fake),
}
out = c_dir / "d4_check"
d = level2c.d4_check(sources, a.filters.split(","), make_client(out))
print(level2c.write_d4(d, out))
