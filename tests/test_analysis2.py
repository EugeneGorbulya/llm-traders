import numpy as np
import pandas as pd
import yaml

from llmtraders import analysis2, level2
from llmtraders.market import CONTROL
from llmtraders.results import read_jsonl


def test_price_levels_carry_the_last_trade():
    levels = analysis2.price_levels([None, 104.0, None, 98.0])
    assert levels == [level2.PRIOR_VALUE, 104.0, 104.0, 98.0]


def test_strata_ci_resamples_within_each_value():
    # Each value holds one number, so every resample within the values has the same
    # mean; resampling across the values would move it.
    x = pd.Series([1.0, 1.0, 3.0, 3.0])
    strata = pd.Series([70.0, 70.0, 130.0, 130.0])
    assert analysis2.strata_ci(x, strata) == (2.0, 2.0)


def test_tables_on_a_gullible_market(tmp_path):
    cfg = level2.load_config()
    main = cfg["main"]
    main["seeds"] = {130: [201, 202], 70: [206, 207]}
    path = tmp_path / "level2.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = level2.run(
        "mock-gullible",
        config=path,
        out_dir=tmp_path / "out",
        cache_path=tmp_path / "c.sqlite",
    )
    res = analysis2.write(out, config=path)
    fake = main["attacks"][0]

    hyp = res["hypotheses"].set_index("hypothesis")
    assert len(hyp) == 5
    assert (hyp["n"] == 4).all()
    # The mock believes a fake 130 in the chat and ignores the price: the traders who
    # see the chat shift, the blind ones in S do not move at all.
    blind = hyp.loc["H4.2 the shift reaches blind traders through the price"]
    assert blind["mean"] == 0 and blind["verdict"] == "no"
    arms = res["by_arm"]
    seeing = arms[
        (arms["metric"] == "belief_shift_seeing")
        & (arms["configuration"] == "K0")
        & (arms["arm"] == fake)
        & (arms["value"] == "all")
    ].iloc[0]
    assert seeing["mean"] > 0.2 and seeing["verdict"] == "yes"
    assert len(res["topup"]) == len(main["configurations"])
    assert (out / "summary.md").exists()

    # The price shift of one seed recomputed by hand from the session records.
    recs = read_jsonl(out / "K0" / "seeds" / "sessions.jsonl")
    sessions = {
        r["arm"]: r for r in recs if r["kind"] == "session" and r["seed"] == 201
    }
    first, last = main["analysis"]["periods"]
    levels = {}
    for arm in (CONTROL, fake):
        series = analysis2.price_levels(sessions[arm]["prices"])
        levels[arm] = np.mean(series[first - 1 : last])
    by_hand = levels[fake] - levels[CONTROL]
    ps = pd.read_csv(out / "price_shifts.csv")
    row = ps[(ps["configuration"] == "K0") & (ps["arm"] == fake) & (ps["seed"] == 201)]
    assert abs(row["price_shift"].iloc[0] - by_hand) < 1e-9
