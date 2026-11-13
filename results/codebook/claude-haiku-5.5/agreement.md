# LLM judge against the reference labels: claude-haiku-5.5, judge_v1

The reference labels of 100 rationales were made by a model, not by people: the
kappa is the judge's agreement with that reference (docs/report/codebook.md).
Valid judge answers: 100 of 100.
[lo, hi] = 95% bootstrap over rationales. Target kappa >= 0.6.

| code | reference 1s | judge 1s | agreement | kappa [lo, hi] | precision | recall |
|---|---|---|---|---|---|---|
| uses_chat | 26 | 28 | 0.96 | 0.90 [0.79, 0.98] | 0.89 | 0.96 |
| dismisses_chat | 27 | 26 | 0.99 | 0.97 [0.91, 1.00] | 1.00 | 0.96 |
| takes_as_fact | 3 | 1 | 0.98 | 0.49 [0.00, 1.00] | 1.00 | 0.33 |
| confusion | 8 | 8 | 1.00 | 1.00 [1.00, 1.00] | 1.00 | 1.00 |
| official | 70 | 67 | 0.97 | 0.93 [0.84, 1.00] | 1.00 | 0.96 |
| authority | 11 | 13 | 0.96 | 0.81 [0.59, 0.96] | 0.77 | 0.91 |
| instruction | 4 | 5 | 0.99 | 0.88 [0.49, 1.00] | 0.80 | 1.00 |
| bayes_calc | 45 | 42 | 0.97 | 0.94 [0.86, 1.00] | 1.00 | 0.93 |
