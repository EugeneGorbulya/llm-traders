import pandas as pd
import yaml

from llmtraders import analysis, extra2, figures, level2, level2c
from llmtraders.core import N_PERIODS


def test_ratio_ci_resamples_whole_paraphrases():
    # Every paraphrase has the same ratio, so every resample has it too.
    num = [1.0, 1.0, 2.0, 2.0]
    den = [2.0, 2.0, 4.0, 4.0]
    assert analysis.ratio_ci(num, den, [0, 0, 1, 1]) == (0.5, 0.5)


def test_trust_weights_on_a_gullible_mock(tmp_path, mock_run):
    conditions = ["neutral", "official_news", "fake_fact_cred"]
    df, quiz_dir = analysis.load([mock_run(conditions)]), tmp_path / "quiz"
    table = figures.trust_weights(df, quiz_dir=quiz_dir)
    w = table.set_index("condition")["w"]
    # The mock updates on official news by Bayes (up to its jitter of 0.02) and lifts
    # its belief to 0.85 of a claimed 1.0 when the chat says 130.
    assert abs(w["official_news"] - 1) < 0.1
    assert 0.5 < w["fake_fact_cred"] < 0.9
    assert table["adopt"].between(0, 1).all()
    assert (table["lo"] <= table["w"]).all() and (table["w"] <= table["hi"]).all()
    path = figures.plot_trust_weights(table, tmp_path / "w.png")
    assert path.stat().st_size > 0


def test_belief_order_and_injection_buys_on_a_gullible_mock(tmp_path, mock_run):
    conditions = ["neutral", "fake_fact_cred", "injection"]
    df, quiz_dir = analysis.load([mock_run(conditions, samples=2)]), tmp_path / "quiz"
    table = figures.belief_order(df, quiz_dir=quiz_dir).set_index("condition")
    quadrants = list(figures.QUADRANTS)
    assert (table[quadrants].sum(axis=1).round(9) == 1).all()
    moved = ["both", "belief only"]
    # The fake 130 lifts the mock's belief in every pair; the injection makes it buy
    # without a word on the value; two neutral samples differ by a jitter under 0.05.
    assert table.loc["fake_fact_cred", moved].sum() == 1
    assert table.loc["injection", "order only"] > 0.9
    assert table.loc[figures.NOISE, moved].sum() == 0
    path = figures.plot_belief_order(table.reset_index(), tmp_path / "q.png")
    assert path.stat().st_size > 0

    buys = figures.injection_buys(df, quiz_dir=quiz_dir).set_index("model")
    # The mock obeys the injection with a limit of 200, above the 130 of success.
    assert buys.loc["mock-gullible", "limit_at_130"] == 1
    assert buys.loc["mock-gullible", "median_above_ref"] > 0


def test_level2_and_variant_c_figures_on_a_mock_market(tmp_path):
    cfg = level2.load_config()
    seeds = {130: [201], 70: [206]}
    cfg["main"]["seeds"] = seeds
    c = cfg["variant_c"]
    c["seeds"] = seeds
    c["pieces"]["llm_manipulator"]["seeds"] = seeds
    c["pieces"]["llm_manipulator"]["writer"] = "mock-rational"
    c["pieces"]["mixed"]["trader_models"] = ["mock-gullible", "mock-rational"] * 2
    config = tmp_path / "level2.yaml"
    config.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    cache = tmp_path / "c.sqlite"
    main = level2.run(
        "mock-gullible", config=config, out_dir=tmp_path / "main", cache_path=cache
    )
    c_out = level2c.run(
        "mock-gullible", config=config, out_dir=tmp_path / "c", cache_path=cache
    )

    paths = extra2.gap_estimates(extra2.price_gaps(main))
    n_arms = len(cfg["main"]["configurations"]) * len(cfg["main"]["attacks"])
    assert len(paths) == n_arms * N_PERIODS
    # The twins see the same first period, so the paired difference starts at 0.
    assert (paths.loc[paths["period"] == 1, "mean"] == 0).all()
    assert figures.plot_price_paths(paths, tmp_path / "p.png").stat().st_size > 0

    u2 = figures.level2_arms(main, cfg)
    assert figures.plot_level2_shifts(u2, tmp_path / "s.png").stat().st_size > 0
    periods = cfg["main"]["analysis"]["periods"]
    orders = extra2.estimates(
        extra2.order_shifts(extra2.decisions(main, cfg), periods), extra2.ORDER_METRICS
    )
    assert set(figures.ORDER_PANELS) <= set(orders["metric"])
    assert figures.plot_level2_orders(orders, tmp_path / "o.png").stat().st_size > 0
    wealth = extra2.estimates(extra2.wealth_by_class(main, cfg), extra2.CLASSES)
    fake = cfg["main"]["attacks"][0]
    who = figures.plot_who_pays(wealth, fake, tmp_path / "w.png")
    assert who.stat().st_size > 0
    gaps = extra2.price_gaps(main)
    recovery = extra2.recovery_table(extra2.recovery(gaps), N_PERIODS)
    assert figures.plot_recovery(recovery, tmp_path / "r.png").stat().st_size > 0
    pieces = {
        piece: level2c.piece_tables(c_out / piece, spec, cfg)[1]
        for piece, spec in c["pieces"].items()
    }
    rows = figures.variant_c_rows(cfg, u2, pieces)
    assert set(rows["panel"]) == {"price", "belief"}
    assert rows["label"].str.contains("2 seeds").all()
    d4 = pd.DataFrame(
        {
            "model": "m",
            "source": ["llm", "llm", "bank", "bank"],
            "seed": [201, 206, 201, 206],
            "period": 2,
            "kind": "manipulation",
            "flagged": [True, False, True, True],
            "filter_valid": True,
            "labeled": True,
            "first_show": True,
        }
    )
    recall = level2c.d4_recall(d4, {201: 70.0, 206: 130.0})
    assert recall.set_index("source")["recall"].to_dict() == {"llm": 0.5, "bank": 1}
    path = figures.plot_variant_c(rows, recall, tmp_path / "c.png")
    assert path.stat().st_size > 0


def test_judge_readouts_and_heatmap(tmp_path):
    rows = []
    for model, chat in (("a", 1), ("b", 0)):
        for condition in (
            "neutral",
            "fake_fact_cred",
            "injection",
            "unverified_signal",
        ):
            for paraphrase in range(3):
                rows.append(
                    {
                        "model": model,
                        "condition": condition,
                        "paraphrase": paraphrase,
                        "valid": True,
                        "uses_chat": chat if condition != "neutral" else 0,
                        "dismisses_chat": 1 - chat,
                        "authority": chat,
                        "confusion": chat,
                        "instruction": chat,
                        "bayes_calc": 1 - chat,
                    }
                )
    table = figures.judge_readouts(pd.DataFrame(rows))
    leans = table[table["readout"] == "leans on the chat"].set_index("model")
    # Attacks only: the neutral rows of model "a" do not dilute its share.
    assert leans.loc["a", "share"] == 1 and leans.loc["b", "share"] == 0
    bayes = table[table["code"] == "bayes_calc"].set_index("model")
    assert bayes.loc["b", "n"] == 12
    assert figures.plot_judge(table, tmp_path / "j.png").stat().st_size > 0
