# Pilot (full level-1 grid = 1089 calls per model)

| model | tag | quant | digest | valid | thinking | median s | p90 s | level-1 hours | quiz |
|---|---|---|---|---|---|---|---|---|---|
| qwen3-4b | qwen3:4b-instruct-2507-q4_K_M | Q4_K_M | 0edcdef34593 | 100% | 0% | 0.7 | 0.9 | 0.2 | PASS |
| qwen3-8b | qwen3:8b | Q4_K_M | 500a1f067a9f | 100% | 0% | 0.9 | 1.1 | 0.3 | PASS |
| qwen3-14b | qwen3:14b | Q4_K_M | bdbd181c33f2 | 100% | 0% | 1.3 | 1.5 | 0.4 | PASS |
| qwen3-14b-think | qwen3:14b | Q4_K_M | bdbd181c33f2 | 100% | 100% | 20.6 | 35.9 | 6.2 | PASS |
| llama3.1-8b | llama3.1:8b | Q4_K_M | 46e0c10c039e | 100% | 0% | 0.7 | 0.9 | 0.2 | FAIL |
| gpt-oss-20b-low | gpt-oss:20b | MXFP4 | f38aa0c53da5 | 100% | 100% | 1.5 | 2.6 | 0.4 | PASS |
| gpt-oss-20b-high | gpt-oss:20b | MXFP4 | f38aa0c53da5 | 98% | 100% | 25.9 | 61.1 | 7.8 | PASS |
