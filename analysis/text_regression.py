"""Regression of the level-1 belief shift on properties of the text into
results/level1/extra/ (FinBERT runs locally, no LLM calls)."""

from llmtraders.textreg import write

print(write().read_text(encoding="utf-8"))
