"""LLM judge by the codebook: on the reference sheet (agreement) or, with --grid, on every level-1 rationale."""

import argparse

import pandas as pd

from llmtraders import analysis, codebook, judge, level1
from llmtraders.results import make_client

p = argparse.ArgumentParser()
p.add_argument("--model", required=True, help="a name from configs/models.yaml")
p.add_argument("--grid", action="store_true", help="all rationales of the level-1 grid")
a = p.parse_args()

out = judge.OUT / a.model
if a.grid:
    rows = judge.grid_rows(analysis.load(level1.run_dirs()))
    # Its own folder: make_client starts a fresh calls.jsonl there.
    grid_out = out / "grid"
    judged = judge.judge(rows, a.model, make_client(grid_out), progress=250)
    keys = rows.drop(columns=["text", "official_record"])
    judged = keys.merge(judged, on="id")
    judged.to_csv(grid_out / "judge_grid.csv", index=False)
    shares = judge.grid_shares(judged, codebook.codes())
    shares.to_csv(grid_out / "shares.csv", index=False)
    print(judge.write_grid(shares, judged, a.model, grid_out))
else:
    ref = codebook.read_labels()
    if ref is None:
        p.error(f"no reference sheet {codebook.SHEET}")
    sheet = pd.read_csv(codebook.SHEET, dtype={"id": int})
    judged = judge.judge(sheet, a.model, make_client(out))
    judged.to_csv(out / "judge_reference.csv", index=False)
    table = judge.agreement(ref, judged, codebook.codes())
    table.to_csv(out / "agreement.csv", index=False)
    print(
        judge.write_agreement(table, judged, a.model, out).read_text(encoding="utf-8")
    )
