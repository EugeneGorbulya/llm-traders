import pandas as pd
import yaml

from llmtraders import level2
from llmtraders.core import N_PERIODS
from llmtraders.market import CONTROL
from llmtraders.results import read_jsonl


def test_main_market_configurations(client, bank):
    cfg = level2.load_config()
    main = cfg["main"]

    def agents(configuration):
        built = level2.main_market(
            cfg, configuration, "mock-rational", client, 201, bank
        )
        return {a.agent_id: a for a in built}

    k0 = agents("K0")
    assert level2.FUND not in k0
    assert all(a.sees_chat for a in k0.values())
    assert len([k for k in k0 if level2.is_zi(k)]) == main["zi_bots"]
    assert k0[level2.MANIP].shares == main["manipulator"]["shares"]
    for name in ("K1", "K3"):
        fund = agents(name)[level2.FUND]
        spec = main["configurations"][name]["fundamental"]
        assert (fund.cash, fund.shares) == (spec["cash"], spec["shares"])
    s = agents("S")
    blind = sorted(k for k, a in s.items() if not a.sees_chat)
    assert blind == ["llm1", "llm3"]
    # One blind trader of each endowment.
    assert len({s[k].cash for k in blind}) == 2


def test_main_run_twins_and_arms(tmp_path):
    cfg = level2.load_config()
    main = cfg["main"]
    main["seeds"] = {130: [201], 70: [206]}
    path = tmp_path / "level2.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = level2.run(
        "mock-gullible",
        config=path,
        out_dir=tmp_path / "out",
        cache_path=tmp_path / "c.sqlite",
    )
    arms = [CONTROL, *main["attacks"]]
    for name in main["configurations"]:
        recs = read_jsonl(out / name / "seeds" / "sessions.jsonl")
        periods = [r for r in recs if r["kind"] == "period"]
        sids = {r["session"] for r in recs if r["kind"] == "session"}
        assert len(sids) == 2
        assert len(recs) == 2 * len(arms) * (N_PERIODS + 1)
        by = {(r["session"], r["arm"], r["period"]): r for r in periods}
        for r in periods:
            llm = [d for k, d in r["decisions"].items() if k.startswith(level2.LLM)]
            assert len(llm) == 4
            manip_orders = [o for o in r["orders"] if o["agent_id"] == level2.MANIP]
            if manip_orders:
                assert r["period"] in (6, 7, 8, 9)
                assert all(o["side"] == "sell" for o in manip_orders)

        for sid in sids:
            # The twins send the same prompts in the first period (same call keys) and
            # get the same answers; messages come only in attack arms.
            first = []
            for arm in arms:
                decisions = by[(sid, arm, 1)]["decisions"].items()
                answers = {
                    k: (d.get("call_key"), d["order"], d["p_high"])
                    for k, d in decisions
                }
                first.append(answers)
            assert all(a == first[0] for a in first)
            for arm in arms:
                posted = {
                    t
                    for t in range(1, N_PERIODS + 1)
                    if any(
                        m["kind"] == "manipulation" for m in by[(sid, arm, t)]["chat"]
                    )
                }
                assert posted == (set() if arm == CONTROL else {2, 3, 4, 5, 6})

    # In S the blind traders answer the same in every arm (the mock ignores the
    # price), while a trader who sees the fake 130 believes it.
    recs = read_jsonl(out / "S" / "seeds" / "sessions.jsonl")
    beliefs = {
        (r["session"], r["arm"]): r["beliefs"] for r in recs if r["kind"] == "session"
    }
    for sid in {s for s, _ in beliefs}:
        control = beliefs[(sid, CONTROL)]
        fake = beliefs[(sid, "fake_fact_cred")]
        for blind in ("llm1", "llm3"):
            assert fake[blind] == control[blind]
        # The mock's gullible belief is 0.85 with a jitter of 0.02.
        assert fake["llm0"][2] >= 0.8 > control["llm0"][2]


def test_market_follows_the_config(client):
    cfg = level2.load_config()
    agents = level2.market(cfg, "mock-rational", client, seed=1, ticker="KVX", n_zi=3)
    llm = [a for a in agents if not level2.is_zi(a.agent_id)]
    assert [(a.cash, a.shares) for a in llm] == [
        (t["cash"], t["shares"]) for t in cfg["traders"]
    ]
    assert [a.agent_id for a in agents if level2.is_zi(a.agent_id)] == [
        "zi",
        "zi2",
        "zi3",
    ]


def test_ladder_steps_only_add_bots(client):
    assert level2.zi_ids(1) == ["zi"]
    assert level2.zi_ids(3)[:2] == level2.zi_ids(2)
    # The first bot draws the same orders on every step; only the quantity it can
    # afford differs, once its holdings diverge.
    cfg = level2.load_config()
    bots = {}
    for n_zi in (1, 3):
        agents = level2.market(cfg, "mock-rational", client, 5, "KVX", n_zi)
        bots[n_zi] = next(a for a in agents if a.agent_id == "zi")
    for t in range(1, N_PERIODS + 1):
        assert bots[1].raw_order(t) == bots[3].raw_order(t)


def test_choose_takes_the_smallest_passing_step_else_the_most_llm_trades():
    def ladder(turnover, gap, mean):
        return pd.DataFrame(
            {
                "zi_bots": [1, 2, 3],
                "turnover_pass": turnover,
                "gap_pass": gap,
                "mean_llm_traded": mean,
            }
        )

    assert level2.choose(ladder([False, True, True], [True] * 3, [3, 6, 7])) == (
        2,
        True,
    )
    # None passes: the most LLM trades among the steps within the price criterion.
    no_turnover = [False] * 3
    assert level2.choose(ladder(no_turnover, [True] * 3, [3, 5, 4])) == (2, False)
    assert level2.choose(ladder(no_turnover, [True, True, False], [3, 4, 5])) == (
        2,
        False,
    )
    assert level2.choose(ladder(no_turnover, [True] * 3, [4, 4, 4])) == (1, False)


def test_news_moves_compare_the_levels_before_each_news():
    rows = []
    prices = {"up": {2: 100.0, 6: 110.0}, "none": {}, "down": {3: 104.0, 5: 98.0}}
    news = {"up": "good", "none": "good", "down": "good"}
    for session, traded in prices.items():
        for t in range(1, N_PERIODS + 1):
            rows.append(
                {
                    "zi_bots": 1,
                    "session": session,
                    "period": t,
                    "price": traded.get(t),
                    "news": news[session],
                }
            )
    p = pd.DataFrame(rows)
    p["level"] = p.groupby("session")["price"].ffill().fillna(level2.PRIOR_VALUE)
    m = level2.news_moves(p).set_index("session")
    assert m.loc["up", "news_move"] == 10.0 and m.loc["up", "news_follow"] == "with"
    assert m.loc["none", "news_follow"] == "flat"
    assert m.loc["down", "news_move"] == -6.0
    assert m.loc["down", "news_follow"] == "against"


def test_calibration_tables(tmp_path):
    out = level2.calibrate(
        "mock-rational", out_dir=tmp_path, cache_path=tmp_path / "c.sqlite"
    )
    cal = level2.load_config()["calibration"]
    n = sum(len(seeds) for seeds in cal["seeds"].values())
    s = pd.read_csv(out / "calibration.csv")
    assert len(s) == n * len(cal["zi_steps"])
    assert set(s["zi_bots"]) == set(cal["zi_steps"])
    assert set(s["value"]) == {70.0, 130.0}
    assert (s["llm_calls"] == 4 * N_PERIODS).all()
    assert (s["invalid"] == 0).all()
    assert (s["llm_traded"] <= s["traded"]).all()
    assert s["llm_side_share"].dropna().between(0, 1).all()

    # The LLM side share is recomputed by hand from the fills of one session.
    first = s.iloc[0]
    step = out / f"zi{first['zi_bots']}"
    recs = [
        r
        for r in read_jsonl(step / "sessions.jsonl")
        if r["kind"] == "period" and r["session"] == first["session"]
    ]
    volume = sum(r["volume"] for r in recs)
    llm = sum(
        abs(q) for r in recs for k, q in r["fills"].items() if not level2.is_zi(k)
    )
    assert first["volume"] == volume
    if volume:
        assert abs(first["llm_side_share"] - llm / (2 * volume)) < 1e-9

    steps = cal["zi_steps"]
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "Chosen: " in summary
    for n_zi in steps:
        assert f"## {n_zi} ZI bots" in summary
