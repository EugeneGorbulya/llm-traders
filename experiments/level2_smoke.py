"""Level-2 smoke: one session of 4 LLM traders and a ZI bot, no manipulator, to the end."""

import argparse

from llmtraders.agents import LLMTrader, ZIBot
from llmtraders.chat import MessageBank
from llmtraders.llm.config import get_model
from llmtraders.llm.log import JsonlLogger
from llmtraders.market import SessionConfig, run_session
from llmtraders.results import RESULTS, make_client

# Two cash-rich and two share-rich traders, as in tests/test_market.py.
# для У2 (гейт 3): состав рынка и сиды - в конфиг после калибровки
ENDOWMENTS = [(1500, 5), (1500, 5), (500, 15), (500, 15)]

p = argparse.ArgumentParser()
p.add_argument("--model", required=True, help="a name from configs/models.yaml")
p.add_argument("--seed", type=int, default=1)
a = p.parse_args()

out = RESULTS / "level2_smoke" / a.model
client = make_client(out)
(out / "sessions.jsonl").unlink(missing_ok=True)
model = get_model(a.model)
agents = [
    LLMTrader(agent_id=f"llm{i}", cash=cash, shares=shares, model=model, client=client)
    for i, (cash, shares) in enumerate(ENDOWMENTS)
]
agents.append(ZIBot(agent_id="zi", cash=1000, shares=10, seed=a.seed))
res = run_session(
    SessionConfig(seed=a.seed),
    agents,
    MessageBank.load(),
    logger=JsonlLogger(out / "sessions.jsonl"),
)
print(f"value {res.value}, signals {res.signals}")
print("prices  ", res.prices)
print("volumes ", res.volumes)
print("rational", [round(x, 1) for x in res.rational])
print("invalid ", res.invalid)
print(out)
