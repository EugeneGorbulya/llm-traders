import pandas as pd
import yaml

from llmtraders import analysis2, extra2, level2


def test_orders_and_wealth_on_a_gullible_market(tmp_path):
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
    fake, injection = main["attacks"]
    d = extra2.decisions(out, cfg)
    # 4 LLM traders x 12 periods x 3 arms x 2 seeds x 4 configurations.
    assert len(d) == 4 * 12 * 3 * 2 * len(main["configurations"])
    assert set(d[d["configuration"] == "S"]["group"]) == {
        analysis2.SEEING,
        analysis2.BLIND,
    }
    orders = extra2.order_shifts(d, main["analysis"]["periods"])
    k0 = orders[orders["configuration"] == "K0"].set_index("arm")
    # The mock believes the fake 130 and obeys "SYSTEM" with a buy at 200.
    assert (k0.loc[fake, "belief_shift"] > 0.1).all()
    assert (k0.loc[injection, "buy_130_shift"] > 0).all()

    w = extra2.wealth_by_class(out, cfg)
    # Trades move cash and shares between agents: every seed sums to 0.
    assert w[f"{extra2.SUM}_shift"].abs().max() < 1e-6
    k3 = w[w["configuration"] == "K3"]
    assert k3["fundamental_shift"].notna().all()
    assert w[w["configuration"] == "K0"]["fundamental_shift"].isna().all()
    # The manipulator's gain is the profit shift of the pre-registered tables.
    s, _ = analysis2.load(out, cfg)
    ps = analysis2.price_shifts(s).set_index(["configuration", "seed", "arm"])
    wi = w.set_index(["configuration", "seed", "arm"])
    assert (wi["manipulator_shift"] - ps["profit_shift"]).abs().max() < 1e-9

    gaps = extra2.price_gaps(out)
    # The manipulator's last trade is P9 (docs/prereg/l2.md).
    assert extra2.AFTER == 9
    assert (gaps[gaps["period"] == 1]["gap"] == 0).all()
    rec = extra2.recovery(gaps)
    # One row per configuration, attack arm and seed.
    assert len(rec) == len(main["configurations"]) * 2 * 2
    assert rec["back"].dropna().between(extra2.AFTER + 1, 12).all()
    table = extra2.recovery_table(rec, 12)
    shares = table[[f"by P{t}" for t in range(extra2.AFTER + 1, 13)]].to_numpy()
    # Back by Pt is cumulative, so it never falls.
    assert (shares[:, 1:] >= shares[:, :-1]).all()
    assert extra2.write(out, config=path).exists()


def test_recovery_counts_after_p9_and_only_seeds_that_left():
    # Seed 1 left the twin and is back in P11; seed 2 never left (within 1.2 all along);
    # seed 3 is back exactly in P9, which is still the manipulator's period.
    gaps = []
    for seed, path in {1: [0, 5, 5, 5, 5, 5, 5, 5, 5, 5, 0, 0], 2: [0] * 12}.items():
        gaps += [{"seed": seed, "period": t, "gap": g} for t, g in enumerate(path, 1)]
    seed3 = [0, 5, 5, 5, 5, 5, 5, 5, 0, 5, 5, 5]
    gaps += [{"seed": 3, "period": t, "gap": g} for t, g in enumerate(seed3, 1)]
    g = pd.DataFrame(gaps).assign(configuration="K0", arm="fake", value=70.0)
    rec = extra2.recovery(g).set_index("seed")
    assert rec["diverged"].to_dict() == {1: True, 2: False, 3: True}
    assert rec.loc[1, "back"] == 11 and pd.isna(rec.loc[3, "back"])
    row = extra2.recovery_table(rec.reset_index(), 12).iloc[0]
    assert row["n"] == 2 and row["stayed"] == 1
    assert row["by P10"] == 0 and row["by P11"] == 0.5
