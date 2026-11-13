"""Cases for the qualitative part of the report into results/level1/extra/ (no model calls)."""

from llmtraders.cases import write

for path in write():
    print(path)
