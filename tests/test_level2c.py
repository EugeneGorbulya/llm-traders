import yaml

from llmtraders import level2, level2c
from llmtraders.agents import LLMManipulator, ScriptedManipulator
from llmtraders.market import CONTROL
from llmtraders.results import make_client, read_jsonl


def test_piece_markets(client, bank):
    cfg = level2.load_config()
    pieces = cfg["variant_c"]["pieces"]

    def agents(piece):
        built = level2c.piece_market(cfg, piece, "mock-rational", client, 201, bank)
        return {a.agent_id: a for a in built}

    crash = agents("crash")[level2.MANIP]
    spec = pieces["crash"]["manipulator"]
    assert type(crash) is ScriptedManipulator and crash.direction == "down"
    assert (crash.cash, crash.shares) == (spec["cash"], spec["shares"])
    writer = agents("llm_manipulator")[level2.MANIP]
    assert isinstance(writer, LLMManipulator)
    assert writer.model.name == pieces["llm_manipulator"]["writer"]
    mixed = agents("mixed")
    names = [mixed[f"{level2.LLM}{i}"].model.name for i in range(4)]
    assert names == pieces["mixed"]["trader_models"]
    # One trader of each endowment per model.
    for model in set(names):
        cash = {mixed[f"{level2.LLM}{i}"].cash for i in range(4) if names[i] == model}
        assert len(cash) == 2


def _small_config(tmp_path):
    cfg = level2.load_config()
    seeds = {130: [201], 70: [206]}
    cfg["main"]["seeds"] = seeds
    cfg["main"]["configurations"] = {"K0": {}}
    c = cfg["variant_c"]
    c["seeds"] = seeds
    c["pieces"]["llm_manipulator"]["seeds"] = seeds
    c["pieces"]["llm_manipulator"]["writer"] = "mock-rational"
    c["pieces"]["mixed"]["trader_models"] = ["mock-gullible", "mock-rational"] * 2
    path = tmp_path / "level2.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_pieces_run_on_the_main_k0(tmp_path):
    path = _small_config(tmp_path)
    cache = tmp_path / "c.sqlite"
    level2.run(
        "mock-gullible", config=path, out_dir=tmp_path / "main", cache_path=cache
    )
    out = level2c.run(
        "mock-gullible", config=path, out_dir=tmp_path / "c", cache_path=cache
    )

    # The silent LLM manipulator trades like the scripted one, so its control arm is
    # the main K0 control and comes from the cache call by call.
    calls = read_jsonl(out / "llm_manipulator" / "K0" / "seeds" / "calls.jsonl")
    control = [r for r in calls if r["tags"].get("arm") == CONTROL]
    assert control and all(r["cache_hit"] for r in control)
    posted = level2c.llm_messages(out / "llm_manipulator")
    assert len(posted) == 2 * 5 and all("130" in t for t in posted)

    # Crash: the manipulator only buys, and the fake 70 pulls a gullible belief down.
    recs = read_jsonl(out / "crash" / "K0" / "seeds" / "sessions.jsonl")
    for r in recs:
        if r["kind"] != "period":
            continue
        for o in r["orders"]:
            if o["agent_id"] == level2.MANIP:
                assert o["side"] == "buy" and r["period"] in (6, 7, 8, 9)
    beliefs = {
        (r["session"], r["arm"]): r["beliefs"] for r in recs if r["kind"] == "session"
    }
    for (sid, arm), b in beliefs.items():
        if arm != CONTROL:
            assert b["llm0"][2] < beliefs[(sid, CONTROL)]["llm0"][2]

    # Mixed: beliefs split by model; the rational mock ignores the chat.
    tables = level2c.write(out, config=path)
    mixed = tables["mixed"]
    pooled = mixed[mixed["value"] == "all"].set_index("metric")["mean"]
    assert pooled["belief_shift_mock-gullible"] > 0.2
    assert pooled["belief_shift_mock-rational"] == 0
    # Wealth by model; outside the mixed market all LLM traders form one group.
    assert {"wealth_shift_mock-gullible", "wealth_shift_mock-rational"} <= set(
        pooled.index
    )
    crash = tables["crash"]
    assert "wealth_shift_llm" in set(crash["metric"])
    summary = (out / "summary.md").read_text(encoding="utf-8")
    for piece in ("crash", "llm_manipulator", "mixed"):
        assert f"## {piece}:" in summary

    # D4 on the chat windows of the LLM piece and of the bank attack in the main K0.
    llm_logs = sorted((out / "llm_manipulator").glob("*/*/sessions.jsonl"))
    bank_logs = sorted((tmp_path / "main" / "K0").glob("*/sessions.jsonl"))
    sources = {
        "llm": (llm_logs, "llm_generated"),
        "bank": (bank_logs, "fake_fact_cred"),
    }
    client = make_client(tmp_path / "d4", tmp_path / "c.sqlite")
    d = level2c.d4_check(sources, ["mock-rational"], client)
    # One window per message period P2-P6 in each of the 2 attack sessions.
    windows = d.groupby(["source", "seed", "period"]).ngroups
    assert windows == 2 * 2 * 5
    manip = d[d["kind"] == "manipulation"]
    assert set(manip["source"]) == {"llm", "bank"} and manip["flagged"].all()
    assert level2c.write_d4(d, tmp_path / "d4").exists()
