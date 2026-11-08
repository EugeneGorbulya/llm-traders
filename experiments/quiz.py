"""Run the Bayes quiz into results/quiz/<model>/."""

import argparse

from llmtraders import quiz
from llmtraders.llm.config import ollama_models

p = argparse.ArgumentParser()
p.add_argument("--model", help="comma-separated; default: all Ollama models")
p.add_argument("--samples", type=int, default=5)
a = p.parse_args()

models = a.model.split(",") if a.model else ollama_models()
for m in models:
    r = quiz.run(m, samples=a.samples)
    print(
        f"{m:20s} valid {r['valid_share']:.0%}  direction {r['direction_share']:.0%}  "
        f"{'PASS' if r['passed'] else 'FAIL'}"
    )
