"""Level-2 smoke: one session of 4 LLM traders and a ZI bot, no manipulator, to the end."""

import argparse

from llmtraders import level2
from llmtraders.chat import MessageBank
from llmtraders.llm.log import JsonlLogger
from llmtraders.market import SessionConfig, run_session
from llmtraders.results import RESULTS, make_client

p = argparse.ArgumentParser()
p.add_argument("--model", required=True, help="a name from configs/models.yaml")
p.add_argument("--seed", type=int, default=1)
a = p.parse_args()

out = RESULTS / "level2_smoke" / a.model
client = make_client(out)
(out / "sessions.jsonl").unlink(missing_ok=True)
bank = MessageBank.load()
# The smoke of 11.11 ran with one ZI bot, before the calibration ladder.
agents = level2.market(level2.load_config(), a.model, client, a.seed, bank.ticker, 1)
res = run_session(
    SessionConfig(seed=a.seed),
    agents,
    bank,
    logger=JsonlLogger(out / "sessions.jsonl"),
)
print(f"value {res.value}, signals {res.signals}")
print("prices  ", res.prices)
print("volumes ", res.volumes)
print("rational", [round(x, 1) for x in res.rational])
print("invalid ", res.invalid)
print(out)
