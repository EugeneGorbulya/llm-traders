"""Gate-0 pilot: ~50 level-1 calls and the quiz per model, seconds per call."""

import argparse
import json
import statistics
import urllib.request

from llmtraders import level1, quiz
from llmtraders.llm.config import load_models, ollama_models
from llmtraders.results import RESULTS, read_jsonl

p = argparse.ArgumentParser()
p.add_argument("--model", help="comma-separated; default: all Ollama models")
p.add_argument("--n", type=int, default=50)
a = p.parse_args()

configs = load_models()
models = a.model.split(",") if a.model else ollama_models()
ollama_url = configs[models[0]].base_url
with urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=5) as r:
    pulled = {m["name"]: m for m in json.loads(r.read())["models"]}
full_grid = len(level1.build_tasks(level1.load_config()))

lines = [
    f"# Pilot (full level-1 grid = {full_grid} calls per model)",
    "",
    "| model | tag | quant | digest | valid | thinking | median s | p90 s | level-1 hours | quiz |",
    "|---|---|---|---|---|---|---|---|---|---|",
]
for name in models:
    tag = configs[name].model
    if tag not in pulled:
        raise SystemExit(f"{tag} is not pulled: ollama pull {tag}")
    level1.run(name, limit=a.n, out_dir=RESULTS / "pilot" / name)
    quiz.run(name)

# The table covers every model piloted so far, not only this run's ones:
# rerunning one model must not drop the others from it.
for name in configs:
    out = RESULTS / "pilot" / name
    if not (out / "results.jsonl").exists():
        continue
    rows = read_jsonl(out / "results.jsonl")
    calls = [
        c
        for c in read_jsonl(out / "calls.jsonl")
        if c.get("tags", {}).get("role") != "filter"
    ]
    score = json.loads((quiz.QUIZ_DIR / name / "score.json").read_text())
    secs = sorted(r["latency_ms"] / 1000 for r in rows if r["latency_ms"])
    if not secs:
        print(f"[pilot {name}] no answers with a latency, see {out}/calls.jsonl")
        continue
    med, p90 = statistics.median(secs), secs[int(0.9 * (len(secs) - 1))]
    tag = configs[name].model
    info = pulled.get(tag, {})
    lines.append(
        f"| {name} | {tag} | {info.get('details', {}).get('quantization_level', '-')} | "
        f"{info.get('digest', '')[:12]} | {sum(r['valid'] for r in rows) / len(rows):.0%} | "
        f"{sum(bool(c.get('thinking')) for c in calls) / len(calls):.0%} | {med:.1f} | {p90:.1f} | "
        f"{full_grid * med / 3600:.1f} | {'PASS' if score['passed'] else 'FAIL'} |"
    )
    print(lines[-1], flush=True)

(RESULTS / "pilot" / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(RESULTS / "pilot" / "summary.md")
