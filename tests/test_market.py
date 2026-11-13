import json

import pytest

from llmtraders import level15
from llmtraders.agents import (
    FundamentalBot,
    LLMTrader,
    ScriptedManipulator,
    ZIBot,
)
from llmtraders.llm.config import get_model
from llmtraders.llm.log import JsonlLogger
from llmtraders.market import SessionConfig, pumped_path, run_scripted, run_session


def make_agents(bank, client, seed, model="mock-gullible"):
    m = get_model(model)
    llm = [
        LLMTrader(agent_id=f"llm{i}", cash=c, shares=s, model=m, client=client)
        for i, (c, s) in enumerate([(1500, 5), (1500, 5), (500, 15), (500, 15)])
    ]
    return llm + [
        ZIBot(agent_id="zi", cash=1000, shares=10, seed=seed),
        FundamentalBot(agent_id="fund", cash=1000, shares=10),
        ScriptedManipulator(
            agent_id="manip", cash=500, shares=30, bank=bank, seed=seed
        ),
    ]


def totals(state):
    return round(sum(v["cash"] for v in state.values()), 6), sum(
        v["shares"] for v in state.values()
    )


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_conservation_of_cash_and_shares(bank, client, seed):
    res = run_session(
        SessionConfig(seed=seed),
        make_agents(bank, client, seed),
        bank,
        arm="manip",
        attack={"type": "fake_fact_cred"},
    )
    assert totals(res.final) == totals(res.initial)
    for v in res.final.values():
        assert v["cash"] >= -1e-9 and v["shares"] >= 0
    assert len(res.prices) == 12
    assert sum(res.volumes) > 0, "market should trade at least once"


def _normalise(rec):
    rec = {k: v for k, v in rec.items() if k not in ("ts", "arm")}
    for d in rec.get("decisions", {}).values():
        d.pop("cache_hits", None)
        d.pop("latency_ms", None)
    return json.dumps(rec, sort_keys=True)


def test_twins_identical_before_manipulation(bank, client, tmp_path):
    seed = 7
    logs = {}
    for arm, attack in (("control", None), ("manip", {"type": "fake_fact_cred"})):
        path = tmp_path / f"{arm}.jsonl"
        run_session(
            SessionConfig(seed=seed),
            make_agents(bank, client, seed),
            bank,
            arm=arm,
            attack=attack,
            logger=JsonlLogger(path),
        )
        logs[arm] = [json.loads(line) for line in path.read_text().splitlines()]
    periods = {
        arm: {r["period"]: r for r in recs if r["kind"] == "period"}
        for arm, recs in logs.items()
    }
    assert _normalise(periods["control"][1]) == _normalise(periods["manip"][1])
    for t in range(1, 13):
        assert periods["control"][t]["value"] == periods["manip"][t]["value"]
        assert periods["control"][t]["official"] == periods["manip"][t]["official"]
    chat2 = {arm: [m["kind"] for m in periods[arm][2]["chat"]] for arm in periods}
    assert "manipulation" not in chat2["control"] and "manipulation" in chat2["manip"]


def test_control_arm_manipulator_still_trades(bank, client):
    seed = 3
    res = run_session(
        SessionConfig(seed=seed), make_agents(bank, client, seed), bank, arm="control"
    )
    assert all(m.kind == "neutral" for m in res.chat)


def test_gullible_beliefs_move_rational_do_not(bank, client):
    seed = 11
    cfg = SessionConfig(seed=seed, value=70.0, signals={4: "bad", 8: "bad"})
    res = run_session(
        cfg,
        make_agents(bank, client, seed),
        bank,
        arm="manip",
        attack={"type": "fake_fact_cred"},
    )
    assert res.beliefs["llm0"][2] >= 0.8
    assert res.beliefs["fund"][2] == pytest.approx(0.5)


def test_scripted_world_price_follows_path(bank, client):
    cfg = SessionConfig(seed=5, value=130.0, signals={4: "good", 8: "good"})
    agent = LLMTrader(
        agent_id="solo",
        cash=1000,
        shares=10,
        model=get_model("mock-rational"),
        client=client,
    )
    l15 = level15.load_config()
    pump = {"pump_periods": l15["pump_periods"], "pump": l15["pump"]}
    neutral = run_scripted(cfg, agent, bank, price_mode="rational", **pump)
    pumped = run_scripted(cfg, agent, bank, price_mode="pumped", **pump)
    assert neutral.prices == [round(x, 2) for x in neutral.rational]
    assert pumped.prices == pumped_path(
        neutral.rational, l15["pump_periods"], l15["pump"]
    )
    assert pumped.prices[2] == pytest.approx(neutral.prices[2] * 1.2, abs=0.01)
    assert pumped.prices[0] == neutral.prices[0]
    manip = ScriptedManipulator(agent_id="manip", cash=0, shares=0, bank=bank, seed=5)
    attacked = run_scripted(
        cfg, agent, bank, attack={"type": "hype"}, manipulator=manip, **pump
    )
    assert any(m.kind == "manipulation" for m in attacked.chat)
