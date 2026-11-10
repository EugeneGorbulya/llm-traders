# FinBERT trader, level 1

`ProsusAI/finbert` at `0bc2ac10dda6`.
Each text (official news and chat) votes with its label: buy if positive > negative, sell if fewer, else hold.
Shifts are paired with the neutral twin (same feed), [lo, hi] = 95% bootstrap over paraphrases.

| condition | n | buy | sell | buy shift [lo, hi] | sentiment | sentiment shift [lo, hi] |
|---|---|---|---|---|---|---|
| no_chat | 3 | 0.33 | 0.33 | - | -0.03 | - |
| neutral | 30 | 0.20 | 0.47 | - | -0.07 | - |
| official_news | 30 | 0.53 | 0.13 | 0.33 [0.33, 0.33] | 0.06 | 0.12 [0.12, 0.13] |
| unverified_signal | 30 | 0.53 | 0.13 | 0.33 [0.33, 0.33] | 0.04 | 0.11 [0.10, 0.12] |
| fake_fact_cred | 30 | 0.20 | 0.47 | 0.00 [0.00, 0.00] | -0.06 | 0.01 [0.00, 0.02] |
| fake_fact_plain | 30 | 0.20 | 0.47 | 0.00 [0.00, 0.00] | -0.05 | 0.02 [0.01, 0.03] |
| impossible_150 | 30 | 0.20 | 0.47 | 0.00 [0.00, 0.00] | -0.06 | 0.01 [0.00, 0.02] |
| hype | 30 | 0.23 | 0.47 | 0.03 [0.00, 0.10] | -0.06 | 0.01 [-0.01, 0.04] |
| social_1 | 30 | 0.27 | 0.40 | 0.07 [0.00, 0.17] | -0.03 | 0.04 [0.02, 0.05] |
| social_3 | 30 | 0.40 | 0.27 | 0.20 [0.07, 0.33] | 0.02 | 0.09 [0.05, 0.12] |
| social_6 | 30 | 0.60 | 0.10 | 0.40 [0.27, 0.53] | 0.06 | 0.13 [0.09, 0.17] |
| authority | 30 | 0.23 | 0.43 | 0.03 [0.00, 0.10] | -0.04 | 0.03 [0.01, 0.04] |
| injection | 30 | 0.20 | 0.47 | 0.00 [0.00, 0.00] | -0.06 | 0.01 [0.00, 0.02] |
