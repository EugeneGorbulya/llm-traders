"""Run the FinBERT trader on the level-1 feeds into results/level1/finbert/."""

from llmtraders import finbert

print(finbert.run() / "summary.md")
