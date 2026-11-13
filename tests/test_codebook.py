import csv

import pandas as pd
import pytest

from llmtraders import analysis, codebook, level1


def _df(tmp_path, mock_run):
    conditions = ["neutral", "official_news", "injection"]
    dirs = [mock_run(conditions, model) for model in ("mock-gullible", "mock-rational")]
    dirs.append(mock_run(conditions, "mock-rational", name="qwen-mock"))
    df = analysis.load(dirs[:2])
    # A third model whose name has the remainder prefix: a copy of the rational mock.
    qwen = analysis.load(dirs[2:]).assign(model="qwen-mock")
    return pd.concat([df, qwen], ignore_index=True), tmp_path / "quiz"


def _book(quotas):
    book = codebook.load_codebook()
    book["sample"] = {"seed": 0, "remainder_first": "qwen", "quotas": quotas}
    return book


def test_codebook_codes_have_examples():
    book = codebook.load_codebook()
    for name, code in book["codes"].items():
        assert {"definition", "example_1", "example_0"} <= set(code), name


def test_official_record_follows_the_snapshot():
    grid = level1.load_config()
    assert codebook.official_record("neutral", "none", grid) == "none"
    assert codebook.official_record("neutral", "good", grid) == "Period 4: GOOD"
    both = codebook.official_record("official_news", "good", grid)
    assert both == "Period 4: GOOD; Period 5: GOOD"


def test_sample_follows_the_quotas_and_repeats(tmp_path, mock_run):
    df, quiz_dir = _df(tmp_path, mock_run)
    book = _book({"injection": 4, "official_news": 2})
    rows = codebook.sample_rationales(df, book, quiz_dir)
    assert rows.equals(codebook.sample_rationales(df, book, quiz_dir))
    assert list(rows["id"]) == list(range(1, 7))
    assert rows.groupby("condition").size().to_dict() == {
        "injection": 4,
        "official_news": 2,
    }
    # 4 over 3 models: the remainder goes to the qwen model first.
    injection = rows[rows["condition"] == "injection"]["model"].value_counts()
    assert injection["qwen-mock"] == 2
    assert (rows["official_record"] != "").all()


def test_sheet_is_never_overwritten_and_labels_are_checked(tmp_path, mock_run):
    df, quiz_dir = _df(tmp_path, mock_run)
    rows = codebook.sample_rationales(df, _book({"injection": 3}), quiz_dir)
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.csv"
    codebook.write_sheet(rows, sheet, key)
    with pytest.raises(FileExistsError):
        codebook.write_sheet(rows, sheet, key)
    with pytest.raises(ValueError):
        codebook.read_labels(sheet)
    names = codebook.codes()
    with sheet.open(encoding="utf-8", newline="") as f:
        filled = list(csv.DictReader(f))
    for r in filled:
        r.update(dict.fromkeys(names, "0"))
    with sheet.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filled[0]))
        w.writeheader()
        w.writerows(filled)
    labels = codebook.read_labels(sheet)
    assert len(labels) == 3 and (labels[names] == 0).all().all()
    assert codebook.read_labels(tmp_path / "missing.csv") is None
