"""Write the blank sheet data/labels/rationales.csv (100 level-1 rationales) and its key."""

from llmtraders import analysis, codebook, level1

df = analysis.load(level1.run_dirs())
rows = codebook.sample_rationales(df)
codebook.write_sheet(rows)
print(f"{codebook.SHEET}: {len(rows)} rationales, key in {codebook.KEY}")
print(rows.groupby("condition").size().to_string())
print(rows.groupby("model").size().to_string())
