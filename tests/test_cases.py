from llmtraders import analysis, cases, codebook


def test_rules_count_and_pick_examples(tmp_path, mock_run):
    df = analysis.load([mock_run(["neutral", "fake_fact_cred", "injection"])])
    keys = df[codebook.KEY_COLUMNS].reset_index(drop=True)
    judged = keys.assign(id=range(1, len(keys) + 1), valid=True)
    for code in codebook.codes():
        judged[code] = 0
    # The judge marks every injection answer as following the instruction.
    judged.loc[judged["condition"] == "injection", "instruction"] = 1
    m = cases.answers(df, judged, quiz_dir=tmp_path / "quiz")
    counts, examples = cases.apply_rules(m)
    assert (counts["matched"] <= counts["of"]).all()
    follow = counts[counts["rule"] == "follows the injection (judge)"].iloc[0]
    assert follow["matched"] == follow["of"] == 30
    # The gullible mock obeys "SYSTEM" with buys at 200: buys, none at the last price.
    rules = counts.set_index("rule")
    assert rules.loc["buys", "matched"] > 0
    assert rules.loc["buys at the last price", "matched"] == 0
    per_rule = examples.groupby(["rule", "model"]).size()
    assert (per_rule <= cases.EXAMPLES).all()
    # A rule without a condition counts every condition on its own.
    bad = counts[counts["rule"] == "BAD news, belief back at 0.5"]
    assert set(bad["condition"]) == {"neutral", "fake_fact_cred", "injection"}
