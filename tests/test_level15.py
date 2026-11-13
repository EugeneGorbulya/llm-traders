from collections import defaultdict

from llmtraders import analysis15, level15
from llmtraders.core import N_PERIODS
from llmtraders.results import read_jsonl


def test_plan_has_balanced_values_and_shared_neutral_twins():
    sessions = level15.plan(level15.load_config())
    assert len(sessions) == 60
    by_value = defaultdict(set)
    for s in sessions:
        by_value[s.value].add(s.seed)
    assert {v: len(seeds) for v, seeds in by_value.items()} == {130.0: 5, 70.0: 5}
    assert not by_value[130.0] & by_value[70.0]
    per_seed = defaultdict(int)
    for s in sessions:
        per_seed[s.seed] += 1
    assert set(per_seed.values()) == {6}


def test_cells_agree_until_text_or_price_differ(tmp_path):
    out = level15.run(
        "mock-gullible", seeds=1, out_dir=tmp_path, cache_path=tmp_path / "c.sqlite"
    )
    rows = read_jsonl(out / "results.jsonl")
    assert len(rows) == 12 * N_PERIODS
    assert all(r["valid"] for r in rows)
    p = {
        (r["seed"], r["price_mode"], r["chat"], r["period"]): r["p_high"] for r in rows
    }
    seed = 1
    for t in (1, 2):
        cells = {
            p[seed, mode, chat, t]
            for mode in ("rational", "pumped")
            for chat in ("neutral", "fake_fact_cred", "injection")
        }
        assert len(cells) == 1, f"period {t}: cells differ before the manipulation"
    assert p[seed, "pumped", "neutral", 3] == p[seed, "rational", "neutral", 3]
    assert p[seed, "rational", "fake_fact_cred", 3] >= 0.8
    assert p[seed, "rational", "neutral", 3] < 0.7


def test_tables_pair_the_cells_of_a_seed(tmp_path):
    out = level15.run(
        "mock-gullible", seeds=1, out_dir=tmp_path, cache_path=tmp_path / "c.sqlite"
    )
    res = analysis15.write([out], tmp_path / "tables")
    con = res["contrasts"].set_index(["attack", "contrast", "value"])
    # Before the first message the four cells of a seed see the same prompts.
    for attack in ("fake_fact_cred", "injection"):
        assert con.loc[(attack, "text before", "all"), "mean"] == 0
    assert con.loc[("fake_fact_cred", "text during", "all"), "mean"] > 0
    assert len(res["curves"]) == 2 * N_PERIODS
    assert (tmp_path / "tables" / "summary.md").exists()


def test_load_keeps_models_apart(tmp_path):
    # Two models run the same sessions: their rows must not be merged with each other.
    dirs = []
    for model in ("mock-gullible", "mock-rational"):
        out = level15.run(
            model,
            seeds=1,
            out_dir=tmp_path / model,
            cache_path=tmp_path / "c.sqlite",
        )
        dirs.append(out)
    # Runs with 1 seed per value are smoke runs: the default tables leave them out.
    assert level15.full_runs(tmp_path) == []
    one = analysis15.load(dirs[:1])
    both = analysis15.load(dirs)
    assert len(both) == 2 * len(one)
    assert both.groupby("model")["side"].count().tolist() == [len(one)] * 2
