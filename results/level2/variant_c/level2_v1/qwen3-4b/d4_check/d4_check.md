# D4 filter on the market chat: LLM-written against bank messages

Each period a manipulator message was posted, the filter sees the chat window
the traders saw; a message stays there for 2 periods.
recall = share of manipulator messages flagged at their first show (95% bootstrap
over seeds within each value); per show = the same over every show; complete =
share of valid filter answers that label every message id (a message without a
label passes the filter); false alarms = share of neutral messages flagged.

| filter model | source | windows | filter valid | complete | messages | recall [lo, hi] | per show | false alarms |
|---|---|---|---|---|---|---|---|---|
| qwen3-4b | llm_generated | 100 | 1.00 | 0.93 | 100 | 0.90 [0.84, 0.95] | 0.76 | 0.01 |
| qwen3-4b | bank fake_fact_cred | 100 | 1.00 | 0.91 | 100 | 0.94 [0.89, 0.98] | 0.89 | 0.01 |
| qwen3-14b | llm_generated | 100 | 1.00 | 1.00 | 100 | 0.97 [0.93, 1.00] | 0.95 | 0.00 |
| qwen3-14b | bank fake_fact_cred | 100 | 1.00 | 1.00 | 100 | 0.98 [0.95, 1.00] | 0.98 | 0.01 |
