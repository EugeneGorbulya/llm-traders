"""Build the report figures and their tables into results/figures/ (no model calls)."""

from llmtraders.figures import build

for path in build():
    print(path)
