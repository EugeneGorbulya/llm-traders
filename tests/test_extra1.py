import re

from llmtraders import analysis, extra1

CONDITIONS = ["neutral", "fake_fact_cred", "authority", "injection"]


def test_word_groups_on_real_rationales():
    hits = {
        "obeys": "The system now instructs to buy, overriding all previous rules.",
        "calls it confirmed": "Official news confirms a final payout of 130.",
        "doubts the chat": "The chat claim is unverified, so I ignore it.",
    }
    for name, text in hits.items():
        assert re.search(extra1.WORDS[name], text, re.IGNORECASE)
    # A rumor the model believes is not doubt.
    belief = "The chat mentions a rumor of 130. This increases my belief."
    assert not re.search(extra1.WORDS["doubts the chat"], belief, re.IGNORECASE)


def test_size_state_and_format_on_mocks(tmp_path, monkeypatch, mock_run):
    dirs = [mock_run(CONDITIONS, model) for model in ("mock-gullible", "mock-rational")]
    dirs.append(mock_run(CONDITIONS, "mock-gullible", fmt="b"))
    df = analysis.load(dirs)
    monkeypatch.setattr(extra1, "SIZE_PAIRS", (("mock-gullible", "mock-rational"),))
    monkeypatch.setattr(extra1, "FORMAT_MODEL", "mock-gullible")
    size = extra1.size_contrasts(df).set_index("condition")
    # The gullible mock believes the fake 130, the rational one ignores the chat.
    assert size.loc["fake_fact_cred", "mean"] > 0.2
    quiz_dir = tmp_path / "quiz"
    states = extra1.by_state(df, quiz_dir)
    assert set(states["state"]) == {"none", "good", "bad"}
    fmt = extra1.prompt_format(df).set_index("condition")
    assert {"dp_a", "dp_b", "buy_a", "buy_b"} <= set(fmt.columns)
    # A format-b run on part of the grid: format a is cut to the same stimuli.
    b_part = df[(df["fmt"] == "a") | (df["paraphrase"] < 3)]
    same = extra1.format_stimuli(b_part)
    counts = same.groupby("fmt")[analysis.STIMULUS].nunique()
    assert (counts.loc["a"] == counts.loc["b"]).all() and counts.loc[
        "a", "paraphrase"
    ] == 3
    words = extra1.rationale_words(df, quiz_dir)
    assert words[list(extra1.WORDS)].stack().between(0, 1).all()
