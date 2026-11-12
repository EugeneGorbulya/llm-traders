# D4 filter on the market chat: LLM-written against bank messages

Each period a manipulator message was posted, the filter sees the chat window
the traders saw. recall = share of manipulator messages flagged (95% bootstrap
over seeds); false alarms = share of neutral messages flagged.

| filter model | source | windows | filter valid | recall [lo, hi] | false alarms |
|---|---|---|---|---|---|
| qwen3-4b | llm_generated | 100 | 1.00 | 0.76 [0.69, 0.81] | 0.01 |
| qwen3-4b | bank fake_fact_cred | 100 | 1.00 | 0.89 [0.83, 0.94] | 0.01 |
| qwen3-14b | llm_generated | 100 | 1.00 | 0.95 [0.91, 0.98] | 0.00 |
| qwen3-14b | bank fake_fact_cred | 100 | 1.00 | 0.98 [0.97, 1.00] | 0.01 |
