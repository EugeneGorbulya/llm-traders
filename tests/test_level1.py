import json
from collections import Counter

import numpy as np
import pytest

from llmtraders import analysis, bank, level1, quiz
from llmtraders.chat import DEFAULT_BANK, MessageBank
from llmtraders.results import read_jsonl


def test_grid_size():
    tasks = level1.build_tasks(level1.load_config())
    by = Counter(t.condition for t in tasks)
    assert len(by) == 13 and by["no_chat"] == 9 and len(tasks) == 1089


def test_attack_only_adds_messages_at_a_balanced_position(bank):
    cfg = level1.load_config()
    tasks = level1.build_tasks(cfg)
    neutral = {t.group: t for t in tasks if t.condition == "neutral"}
    positions = {}
    for t in tasks:
        if t.kind != "attack":
            continue
        positions.setdefault(t.group, set()).add(t.position)
        obs_a, info = level1.build_observation(t, cfg, bank)
        obs_n, _ = level1.build_observation(neutral[t.group], cfg, bank)
        assert [m for m in obs_a.chat if m.kind == "neutral"] == obs_n.chat
        assert (
            len(obs_a.chat) - len(obs_n.chat)
            == t.n_accounts
            == len(info["attack_texts"])
        )
    assert all(len(p) == 1 for p in positions.values())


def test_official_news_and_its_chat_pair(bank):
    cfg = level1.load_config()
    tasks = level1.build_tasks(cfg)
    get = lambda c, s: next(t for t in tasks if t.condition == c and t.state == s)
    _, off = level1.build_observation(get("official_news", "good"), cfg, bank)
    _, unv = level1.build_observation(get("unverified_signal", "good"), cfg, bank)
    assert off["rational_p"] == pytest.approx(0.845, abs=1e-3)
    assert unv["rational_p"] == pytest.approx(0.7) and unv["claim_p"] == pytest.approx(
        off["claim_p"]
    )
    assert (
        level1.build_observation(get("hype", "none"), cfg, bank)[1]["claim_p"] is None
    )


def test_subset_keeps_neutral_twins():
    sub = level1.subset(level1.build_tasks(level1.load_config()), 50)
    assert 40 <= len(sub) <= 60
    assert {t.group for t in sub if t.kind == "attack"} <= {
        t.group for t in sub if t.condition == "neutral"
    }


def test_run_rerun_from_cache_and_analysis(tmp_path):
    cache = tmp_path / "cache.sqlite"
    for model in ("mock-gullible", "mock-rational"):
        level1.run(model, out_dir=tmp_path / model, cache_path=cache, quiet=True)
    level1.run(
        "mock-gullible", out_dir=tmp_path / "again", cache_path=cache, quiet=True
    )
    calls = read_jsonl(tmp_path / "again" / "calls.jsonl")
    assert len(calls) == 1089 and all(c["cache_hit"] for c in calls)

    res = analysis.write(
        [tmp_path / "mock-gullible", tmp_path / "mock-rational"],
        tmp_path / "tables",
        quiz_dir=tmp_path / "quiz",
    )
    s = res["summary"].set_index(["model", "condition"])
    assert s.loc[("mock-gullible", "fake_fact_cred"), "dp"] > 0.1
    assert abs(s.loc[("mock-rational", "fake_fact_cred"), "dp"]) < 0.05
    assert s.loc[("mock-gullible", "injection"), "buy_130"] > 0.9
    assert s.loc[("mock-rational", "injection"), "buy_130"] == 0
    c = res["contrasts"].set_index(["model", "contrast"])
    assert c.loc[("mock-rational", "official_news - unverified_signal"), "mean"] > 0.1
    # One no_chat answer per state and sample: 9, not 9 x 10 neutral paraphrases.
    assert c.loc[("mock-rational", "neutral - no_chat"), "n"] == 9
    assert (tmp_path / "tables" / "summary.md").exists()

    with pytest.raises(ValueError, match="several runs"):
        analysis.load([tmp_path / "mock-gullible", tmp_path / "again"])


def test_defenses_are_checked_before_any_output_and_d4_filters(tmp_path):
    with pytest.raises(ValueError, match="unknown defenses"):
        level1.run("mock-rational", defenses=["d1"], out_dir=tmp_path / "x", quiet=True)
    assert not (tmp_path / "x").exists()

    out = level1.run(
        "mock-gullible",
        limit=20,
        defenses=["D4"],
        out_dir=tmp_path / "d4",
        cache_path=tmp_path / "cache.sqlite",
        quiet=True,
    )
    rows = read_jsonl(out / "results.jsonl")
    assert any(r["filter"] for r in rows if r["kind"] == "attack")


def test_quiz_gate(tmp_path):
    ok = quiz.run(
        "mock-rational", out_dir=tmp_path / "a", cache_path=tmp_path / "c.sqlite"
    )
    bad = quiz.run(
        "mock-garbage", out_dir=tmp_path / "b", cache_path=tmp_path / "c.sqlite"
    )
    assert ok["passed"] and ok["valid_share"] == 1.0
    assert not bad["passed"] and bad["valid_share"] == 0.0


def fake_encoder(texts):
    out = np.zeros((len(texts), 256))
    for i, t in enumerate(texts):
        for j in range(len(t) - 2):
            out[i, hash(t[j : j + 3].lower()) % 256] += 1
    return out


def test_bank_check_and_freeze(tmp_path):
    rep = bank.check(out=tmp_path / "check.md", encode=fake_encoder).read_text()
    assert (
        MessageBank.load(DEFAULT_BANK, prefer_frozen=False).sha256 in rep
        and "| fake_fact_cred |" in rep
    )
    frozen = tmp_path / "bank.frozen.json"
    sha = bank.freeze(frozen=frozen)
    assert (
        sha
        == MessageBank.load(DEFAULT_BANK, prefer_frozen=False).sha256
        == MessageBank.load(frozen).sha256
    )
    with pytest.raises(FileExistsError):
        bank.freeze(frozen=frozen)


def write_run(out, model, shifts):
    """results.jsonl of a fake run: p(130) = 0.5 + shift of the condition + noise by paraphrase."""
    rows = []
    for condition, shift in [("neutral", 0.0), *shifts.items()]:
        for paraphrase in range(4):
            noise = 0.01 * paraphrase if condition != "neutral" else 0.0
            for state in ("none", "good"):
                for sample in range(2):
                    rows.append(
                        {
                            "model": model,
                            "defenses": "",
                            "fmt": "a",
                            "condition": condition,
                            "kind": "neutral" if condition == "neutral" else "attack",
                            "paraphrase": paraphrase,
                            "state": state,
                            "sample": sample,
                            "valid": True,
                            "p_high": 0.5 + shift + noise,
                            "fair_value": 100.0,
                            "side": "buy" if shift > 0 else "hold",
                            "limit_price": 120.0,
                            "claim_p": None,
                        }
                    )
    out.mkdir(parents=True)
    (out / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return out


def test_hypotheses_across_models_and_level2_choice(tmp_path):
    shifts = {
        "qwen3-14b": {"fake_fact_cred": 0.2, "hype": 0.1},
        "qwen3-14b-think": {"fake_fact_cred": 0.2, "hype": 0.0},
        "qwen3-8b": {"fake_fact_cred": 0.3, "hype": 0.1, "injection": 0.4},
        "llama3.1-8b": {"fake_fact_cred": 0.5, "hype": 0.1},
    }
    dirs = [write_run(tmp_path / m, m, s) for m, s in shifts.items()]
    for model in shifts:
        (tmp_path / "quiz" / model).mkdir(parents=True)
        score = {"passed": model != "llama3.1-8b"}
        (tmp_path / "quiz" / model / "score.json").write_text(json.dumps(score))

    res = analysis.write(dirs, tmp_path / "tables", quiz_dir=tmp_path / "quiz")
    roles = res["runs"].set_index("model")["role"]
    assert roles["llama3.1-8b"] == "extra: quiz failed"
    kn = analysis.k_of_n(res["contrasts"], res["runs"]).set_index("contrast")
    assert kn.loc["fake_fact_cred - hype", ["k", "n"]].tolist() == [3, 3]
    a = res["across"].set_index(["contrast", "condition"])
    think = "qwen3-14b-think - qwen3-14b"
    assert a.loc[(think, "hype"), "verdict"] == "yes"
    assert a.loc[(think, "fake_fact_cred"), "verdict"] == "yes"
    df = analysis.load(dirs)
    choice = analysis.level2_choice(df, res["summary"], res["runs"])
    assert choice["model"] == "qwen3-8b" and choice["attack"] == "fake_fact_cred"


def test_verdict_follows_the_preregistered_rule():
    assert analysis.verdict(0.1, 0.01, 0.2, ">0") == "yes"
    assert analysis.verdict(0.1, 0.0, 0.2, ">0") == "no"
    assert analysis.verdict(-0.1, -0.2, -0.01, "<0") == "yes"
    assert analysis.verdict(0.0, -0.1, 0.1, "~0") == "yes"
    assert analysis.verdict(0.05, 0.01, 0.1, "~0") == "no"
    assert analysis.verdict(0.05, 0.01, 0.1, None) == "-"


def test_verdict_needs_the_minimum_effect():
    # A deterministic model: 4 of 90 pairs shifted by 0.05 give a tight interval above 0.
    assert analysis.verdict(0.002, 0.0006, 0.004, ">0") == "no"
    assert analysis.verdict(-0.01, -0.015, -0.005, "<0") == "no"
    assert analysis.verdict(0.01, 0.005, 0.015, "~0") == "yes"
    at_threshold = np.mean([0.7 - 0.5] * 9 + [0.0] * 81)
    assert analysis.verdict(at_threshold, 0.01, 0.03, ">0") == "yes"


def test_cluster_bootstrap_resamples_whole_paraphrases():
    values = [0.0] * 50 + [1.0] * 50
    clusters = [0] * 50 + [1] * 50
    assert analysis.cluster_ci(values, clusters) == (0.0, 1.0)
    assert np.isnan(analysis.cluster_ci([0.3] * 10, [0] * 10)[0])


def test_extra_conditions_run_only_when_named():
    # The main grid keeps its size; an extra condition runs only when named.
    _, tasks = level1.plan()
    assert len(tasks) == 1089
    assert "fake_fact_cred_down" not in {t.condition for t in tasks}
    _, named = level1.plan(["fake_fact_cred_down"])
    assert {t.condition for t in named} == {"fake_fact_cred_down"}
    assert len(named) == 90
