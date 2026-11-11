import pandas as pd

from llmtraders import level2
from llmtraders.core import N_PERIODS
from llmtraders.results import read_jsonl


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
