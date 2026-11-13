import numpy as np
import pandas as pd

from llmtraders import analysis, codebook, judge


def test_cohen_kappa():
    a = np.array([1, 1, 0, 0])
    assert judge.cohen_kappa(a, a) == 1
    assert judge.cohen_kappa(a, 1 - a) == -1
    # One side constant: chance agreement is perfect, kappa is undefined.
    assert np.isnan(judge.cohen_kappa(np.ones(4, dtype=int), np.ones(4, dtype=int)))


def test_validate_judge_takes_only_booleans():
    validate = judge.validate_judge(["a", "b"])
    assert validate({"a": True, "b": False}) == (True, {"a": 1, "b": 0}, None)
    ok, parsed, _ = validate({"a": "false", "b": False})
    assert not ok and parsed is None


def test_judge_messages_carry_the_codebook():
    book = codebook.load_codebook()
    msgs = judge.judge_messages(book, "I buy.", "none")
    for name in book["codes"]:
        assert name in msgs[0]["content"]
    assert msgs[1]["content"] == "Official record: none\nRationale: I buy."


def test_judge_and_agreement_on_the_mock(client):
    names = codebook.codes()
    # The mock judge marks a code true when the rationale names it.
    rows = pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "text": ["official bayes_calc", "uses_chat", "official", "nothing"],
            "official_record": ["Period 4: GOOD", "none", "none", "none"],
        }
    )
    judged = judge.judge(rows, "mock-rational", client)
    assert judged["valid"].all()
    assert judged.set_index("id").loc[1, "official"] == 1
    ref = judged[["id", *names]].astype(int).copy()
    # The reference disagrees once on official.
    ref.loc[ref["id"] == 4, "official"] = 1
    table = judge.agreement(ref, judged, names).set_index("code")
    assert table.loc["uses_chat", "kappa"] == 1
    assert (
        table.loc["official", "ref_ones"] == 3
        and table.loc["official", "judge_ones"] == 2
    )
    assert table.loc["official", "precision"] == 1
    assert abs(table.loc["official", "recall"] - 2 / 3) < 1e-9
    assert np.isnan(table.loc["instruction", "kappa"])


def test_grid_rows_shares_and_summary_on_the_mock(tmp_path, client, mock_run):
    out = mock_run(["neutral", "official_news"])
    rows = judge.grid_rows(analysis.load([out]), quiz_dir=tmp_path / "quiz")
    # 2 conditions x 3 states x 10 paraphrases, one sample each.
    assert len(rows) == 60 and list(rows["id"]) == list(range(1, 61))
    official = rows[(rows["condition"] == "official_news") & (rows["state"] == "none")]
    assert (official["official_record"] == "Period 5: GOOD").all()
    judged = judge.judge(rows, "mock-rational", client)
    judged = rows.drop(columns=["text", "official_record"]).merge(judged, on="id")
    names = codebook.codes()
    shares = judge.grid_shares(judged, names)
    assert len(shares) == 2 and (shares["n"] == 30).all()
    assert shares[names].stack().between(0, 1).all()
    assert judge.write_grid(shares, judged, "mock-rational", tmp_path).exists()
