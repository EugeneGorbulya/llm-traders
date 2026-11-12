"""Level-1 check of the crash attack before variant C: does "it pays 70" move belief down?"""

import argparse

from llmtraders import analysis, level1
from llmtraders.results import RESULTS

CONDITION = "fake_fact_cred_down"

p = argparse.ArgumentParser()
p.add_argument("--model", required=True, help="a name from configs/models.yaml")
a = p.parse_args()

# Outside results/level1/<model>/ so the main grid of the model is not overwritten; the
# neutral twins come from the cache of that grid.
out = level1.run(
    a.model,
    conditions=["neutral", CONDITION],
    out_dir=RESULTS / "level1" / "extra" / a.model,
)
df = analysis.load([out])
row = analysis.summary(df).set_index("condition").loc[CONDITION]
valid = df[df["valid"]]
sells = (valid["side"] == "sell").groupby(valid["condition"]).mean()
text = (
    f"{a.model}, {CONDITION} against the neutral twin: "
    f"dp {row['dp']:.3f} [{row['dp_lo']:.3f}, {row['dp_hi']:.3f}], "
    f"buy shift {row['buy_shift']:+.3f}, share of sells "
    f"{sells['neutral']:.2f} -> {sells[CONDITION]:.2f}, valid {row['valid']:.2f}"
)
(out / "crash_check.md").write_text(text + "\n", encoding="utf-8")
print(text)
