"""Codebook for the traders' rationales: the hand-label sheet of level-1 rationales and its reading."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import analysis, level1
from .core import ROOT
from .results import load_yaml

CONFIG = ROOT / "configs" / "codebook.yaml"
SHEET = ROOT / "data" / "labels" / "rationales.csv"
# id -> the run and stimulus of each rationale; kept apart so the labeler does not see
# the model or the condition.
KEY = ROOT / "data" / "labels" / "rationales_key.csv"
KEY_COLUMNS = [*analysis.KEY, "condition", *analysis.STIMULUS]


def load_codebook(path: Path = CONFIG) -> dict[str, Any]:
    return load_yaml(path)


def codes(path: Path = CONFIG) -> list[str]:
    return list(load_codebook(path)["codes"])


def official_record(condition: str, state: str, cfg: dict[str, Any]) -> str:
    """The official signals the trader had seen, as shown to the labeler and the judge."""
    signals = level1.official_signals(cfg, state, condition)
    return "; ".join(f"Period {p}: {s.upper()}" for p, s in signals) or "none"


def sample_rationales(
    df: pd.DataFrame,
    book: dict[str, Any] | None = None,
    quiz_dir: Path = analysis.QUIZ_DIR,
) -> pd.DataFrame:
    """Valid rationales of the full level-1 runs by the quotas of the codebook, shuffled.
    Columns: id, KEY_COLUMNS, rationale, official_record."""
    book = book or load_codebook()
    plan = book["sample"]
    pool = rationale_pool(df, quiz_dir)
    first = plan["remainder_first"]
    # The models of the remainder prefix first, then the rest; alphabetical within each.
    models = sorted(set(pool["model"]), key=lambda m: (not m.startswith(first), m))
    rng = np.random.default_rng(plan["seed"])
    picked = []
    for cond, quota in plan["quotas"].items():
        per_model = [quota // len(models)] * len(models)
        for i in range(quota % len(models)):
            per_model[i] += 1
        for model, k in zip(models, per_model, strict=True):
            cell = pool.index[(pool["model"] == model) & (pool["condition"] == cond)]
            picked += list(rng.choice(cell, size=k, replace=False))
    rows = pool.loc[picked, [*KEY_COLUMNS, "rationale"]]
    rows = rows.iloc[rng.permutation(len(rows))].reset_index(drop=True)
    rows["official_record"] = official_records(rows)
    rows.insert(0, "id", range(1, len(rows) + 1))
    return rows


def rationale_pool(
    df: pd.DataFrame, quiz_dir: Path = analysis.QUIZ_DIR
) -> pd.DataFrame:
    """Valid, non-empty rationales of the full level-1 runs, in the order of df."""
    pool = df.merge(analysis.full_runs(df, quiz_dir), on=analysis.KEY)
    return pool[pool["valid"] & (pool["rationale"].fillna("").str.strip() != "")]


def official_records(rows: pd.DataFrame) -> list[str]:
    """The official record each rationale's model saw (condition, state)."""
    grid = level1.load_config()
    return [
        official_record(c, s, grid) for c, s in zip(rows["condition"], rows["state"])
    ]


def write_sheet(
    rows: pd.DataFrame, sheet: Path = SHEET, key: Path = KEY, config: Path = CONFIG
) -> None:
    """The blank sheet (id, text, official record, one column per code, note) and the
    key; an existing sheet is never overwritten, it may hold labels."""
    sheet, key = Path(sheet), Path(key)
    if sheet.exists():
        raise FileExistsError(f"{sheet} already exists: labels are never overwritten")
    sheet.parent.mkdir(parents=True, exist_ok=True)
    names = codes(config)
    with sheet.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "text", "official_record", *names, "note"])
        for _, r in rows.iterrows():
            blank = [""] * len(names)
            w.writerow([r["id"], r["rationale"], r["official_record"], *blank, ""])
    rows[["id", *KEY_COLUMNS]].to_csv(key, index=False)


def read_labels(sheet: Path = SHEET, config: Path = CONFIG) -> pd.DataFrame | None:
    """id and 0/1 per code from the filled sheet; None while there is no sheet."""
    sheet = Path(sheet)
    if not sheet.exists():
        return None
    names = codes(config)
    with sheet.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    bad = [r["id"] for r in rows if any(r[c].strip() not in ("0", "1") for c in names)]
    if bad:
        raise ValueError(f"{sheet}: not 0/1 in every code for ids {', '.join(bad)}")
    labels = pd.DataFrame(rows)[["id", *names]]
    return labels.astype(int)
