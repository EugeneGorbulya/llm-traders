import csv

import pytest

from llmtraders import defenses, level1
from llmtraders.chat import MessageBank


def test_grid_is_600_trader_calls_per_model():
    cfg = defenses.load_config()
    _, tasks = level1.plan(cfg["conditions"], cfg["samples"])
    assert len(tasks) * len(cfg["defenses"]) == 600


def test_label_sheet_has_every_attack_paraphrase_once():
    texts = defenses.feed_texts()
    assert len(texts) == len(set(texts))
    bank = MessageBank.load()
    for msg_type in ("fake_fact_cred", "social", "injection"):
        assert set(bank.types[msg_type].paraphrases) <= set(texts)


def _run_grid(tmp_path):
    cfg = defenses.load_config()
    cache = tmp_path / "cache.sqlite"
    common = {
        "conditions": cfg["conditions"],
        "samples": cfg["samples"],
        "cache_path": cache,
        "quiet": True,
    }
    dirs = [level1.run("mock-gullible", out_dir=tmp_path / "none", **common)]
    for d in cfg["defenses"]:
        dirs.append(
            level1.run("mock-gullible", defenses=[d], out_dir=tmp_path / d, **common)
        )
    return cfg, dirs


def test_tables_on_mock_with_labels_from_construction(tmp_path):
    cfg, dirs = _run_grid(tmp_path)
    res = defenses.write(dirs, tmp_path / "out", labels_path=tmp_path / "none.csv")
    assert len(res["axes"]) == len(cfg["defenses"]) * len(defenses.AXES)
    assert set(res["axes"]["verdict"]) <= {"yes", "no", "-"}
    d4 = res["d4"].iloc[0]
    assert d4["truth"] == "construction" and d4["filter_valid"] == 1.0
    assert 0 <= d4["precision"] <= 1 and 0 <= d4["recall"] <= 1
    assert (tmp_path / "out" / "defenses.md").exists()

    # mock-gullible: D3 (datamarking) and D4 (filter) remove the attack entirely, so
    # H3.1 fails with a note; D1 and D2 leave it untouched, so H3.1 fails plainly.
    dec = res["verdicts"].set_index(["defense", "hypothesis"])
    assert dec.loc[("D4", "H3.1 fake_fact_cred"), "note"] == "effect removed fully"
    assert dec.loc[("D1", "H3.1 fake_fact_cred"), "verdict"] == "no"
    assert dec.loc[("D1", "H3.3"), "verdict"] == "yes"
    assert ("D4", "H3.2") in dec.index
    kn = res["k_of_n"]
    assert (kn["n"] == 1).all()


def test_manual_labels_are_checked_and_compared(tmp_path):
    _, dirs = _run_grid(tmp_path)
    bank = MessageBank.load()
    attacks = {p for t in bank.types.values() for p in t.paraphrases}
    sheet = tmp_path / "labels.csv"
    with sheet.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "text", "manipulative", "note"])
        for i, text in enumerate(defenses.feed_texts(), start=1):
            w.writerow([i, text, int(text in attacks), ""])
    res = defenses.write(dirs, tmp_path / "out", labels_path=sheet)
    assert res["d4"].iloc[0]["manual_vs_construction"] == 1.0

    sheet.write_text("id,text,manipulative,note\n1,hello,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no 0/1 label"):
        defenses.read_labels(sheet)
