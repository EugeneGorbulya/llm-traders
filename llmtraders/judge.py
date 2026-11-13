"""LLM judge for the traders' rationales by the codebook, and its agreement with the reference labels."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import analysis, codebook, level1
from .analysis import fmt_ci, fnum
from .llm.client import LLMClient, Validator
from .llm.config import get_model
from .results import RESULTS

JUDGE_VERSION = "judge_v1"
OUT = RESULTS / "codebook"
# The judge run on the whole level-1 grid (13.11, experiments.judge --grid).
GRID_MODEL = "claude-haiku-5.5"


def judge_schema(names: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {n: {"type": "boolean"} for n in names},
        "required": list(names),
        "additionalProperties": False,
    }


def judge_messages(
    book: dict[str, Any], rationale: str, record: str
) -> list[dict[str, str]]:
    """The codebook as the system prompt; the rationale and its official record."""
    lines = [
        "You code short rationales written by traders in a research market simulation.",
        "",
        book["game"],
        "",
        "Codes, each true or false:",
    ]
    for name, code in book["codes"].items():
        lines += [
            f"- {name}: {code['definition']}",
            f'  true example: "{code["example_1"]}"',
            f'  false example: "{code["example_0"]}"',
        ]
    lines += [
        "",
        "Decide every code from the rationale and the official record alone. Reply with",
        "JSON: one true or false per code.",
    ]
    user = f"Official record: {record}\nRationale: {rationale}"
    return [
        {"role": "system", "content": "\n".join(lines)},
        {"role": "user", "content": user},
    ]


def validate_judge(names: Sequence[str]) -> Validator:
    def validate(obj: dict[str, Any]) -> tuple[bool, dict[str, int] | None, str | None]:
        # A string "false" would read as True, so only real JSON booleans pass.
        missing = [n for n in names if not isinstance(obj.get(n), bool)]
        if missing:
            return False, None, f"no boolean for {', '.join(missing)}"
        return True, {n: int(obj[n]) for n in names}, None

    return validate


def judge(
    rows: pd.DataFrame,
    model: str,
    client: LLMClient,
    config: Path = codebook.CONFIG,
    progress: int | None = None,
) -> pd.DataFrame:
    """Codes of the judge per row (columns id, text, official_record); an invalid answer
    after the retry leaves the codes empty and valid = False. With `progress`, prints a
    line every that many rows (a long run goes to a log)."""
    book = codebook.load_codebook(config)
    names = list(book["codes"])
    cfg = get_model(model)
    schema = judge_schema(names)
    validate = validate_judge(names)
    version = f"{JUDGE_VERSION}/{book['version']}"
    out = []
    for k, (_, r) in enumerate(rows.iterrows(), start=1):
        if progress and k % progress == 0:
            print(f"[judge {model}] {k}/{len(rows)}", flush=True)
        res = client.query(
            cfg,
            judge_messages(book, r["text"], r["official_record"]),
            schema=schema,
            validate=validate,
            seed_parts=("judge",),
            prompt_version=version,
            tags={"role": "judge", "id": int(r["id"])},
        )
        codes = res.parsed if res.valid else dict.fromkeys(names, np.nan)
        out.append({"id": int(r["id"]), "valid": res.valid, **codes})
    return pd.DataFrame(out)


def grid_rows(df: pd.DataFrame, quiz_dir: Path = analysis.QUIZ_DIR) -> pd.DataFrame:
    """Every valid rationale of the full level-1 runs, with its official record and an
    id; the key columns say which run and stimulus it is."""
    rows = codebook.rationale_pool(df, quiz_dir)
    rows = rows.sort_values(codebook.KEY_COLUMNS).reset_index(drop=True)
    records = codebook.official_records(rows)
    out = rows[codebook.KEY_COLUMNS].assign(
        text=rows["rationale"], official_record=records
    )
    out.insert(0, "id", range(1, len(out) + 1))
    return out


def read_grid(model: str = GRID_MODEL) -> pd.DataFrame:
    """The judge's codes on the whole grid, ready to join the level-1 rows."""
    path = OUT / model / "grid" / "judge_grid.csv"
    # "" stays "" (no defense, as in the level-1 rows); the codes become numbers, NaN
    # where an invalid answer left them empty, so a rule "== 1" still means a 1.
    judged = pd.read_csv(path, keep_default_na=False)
    for name in codebook.codes():
        judged[name] = pd.to_numeric(judged[name], errors="coerce")
    judged["valid"] = judged["valid"].astype(str) == "True"
    return judged


def grid_shares(judged: pd.DataFrame, names: Sequence[str]) -> pd.DataFrame:
    """Share of rationales with each code per model and condition (valid answers)."""
    valid = judged[judged["valid"]]
    shares = valid.groupby(["model", "condition"], sort=False)[list(names)].mean()
    shares["n"] = valid.groupby(["model", "condition"], sort=False).size()
    return shares.reset_index()


def write_grid(
    shares: pd.DataFrame, judged: pd.DataFrame, model: str, out: Path
) -> Path:
    """One table per code: conditions x models, the share of rationales with the code."""
    order = [c["name"] for c in level1.load_config()["conditions"]]
    conditions = [c for c in order if c in set(shares["condition"])]
    names = [c for c in shares.columns if c not in ("model", "condition", "n")]
    lines = [
        f"# LLM judge on the level-1 grid: {model}, {JUDGE_VERSION}",
        "",
        f"Valid judge answers: {int(judged['valid'].sum())} of {len(judged)}. Shares of",
        "rationales with a code, per condition and model. Agreement with the reference",
        "labels: ../agreement.md (the reference was made by a model).",
    ]
    for name in names:
        wide = shares.pivot(index="condition", columns="model", values=name)
        wide = wide.reindex(conditions)
        models = list(wide.columns)
        lines += ["", f"## {name}", "", "| condition | " + " | ".join(models) + " |"]
        lines.append("|---|" + "---|" * len(models))
        for cond, r in wide.iterrows():
            cells = " | ".join(fnum(r[m]) for m in models)
            lines.append(f"| {cond} | {cells} |")
    path = out / "grid.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cohen_kappa(a: np.ndarray, b: np.ndarray) -> float:
    """Kappa of two 0/1 vectors; NaN when chance agreement is perfect (one constant)."""
    po = (a == b).mean()
    pa, pb = a.mean(), b.mean()
    pe = pa * pb + (1 - pa) * (1 - pb)
    return float("nan") if pe == 1 else float((po - pe) / (1 - pe))


def agreement(
    ref: pd.DataFrame, judged: pd.DataFrame, names: Sequence[str]
) -> pd.DataFrame:
    """Per code: prevalence on both sides, kappa with a 95% bootstrap over items, and
    the judge's precision and recall against the reference."""
    m = ref.merge(judged[judged["valid"]], on="id", suffixes=("_ref", "_judge"))
    rng = np.random.default_rng(analysis.BOOT_SEED)
    picks = rng.integers(0, len(m), size=(analysis.N_BOOT, len(m)))
    rows = []
    for name in names:
        a = m[f"{name}_ref"].to_numpy(dtype=int)
        b = m[f"{name}_judge"].to_numpy(dtype=int)
        boots = np.array([cohen_kappa(a[p], b[p]) for p in picks])
        # A code constant on both sides has no kappa in any resample.
        if np.isnan(boots).all():
            lo = hi = float("nan")
        else:
            lo, hi = np.nanpercentile(boots, [2.5, 97.5])
        both = int((a & b).sum())
        rows.append(
            {
                "code": name,
                "n": len(m),
                "ref_ones": int(a.sum()),
                "judge_ones": int(b.sum()),
                "agree": float((a == b).mean()),
                "kappa": cohen_kappa(a, b),
                "lo": float(lo),
                "hi": float(hi),
                "precision": both / b.sum() if b.sum() else float("nan"),
                "recall": both / a.sum() if a.sum() else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def write_agreement(
    table: pd.DataFrame, judged: pd.DataFrame, model: str, out: Path
) -> Path:
    lines = [
        f"# LLM judge against the reference labels: {model}, {JUDGE_VERSION}",
        "",
        "The reference labels of 100 rationales were made by a model, not by people: the",
        "kappa is the judge's agreement with that reference (docs/report/codebook.md).",
        f"Valid judge answers: {int(judged['valid'].sum())} of {len(judged)}.",
        "[lo, hi] = 95% bootstrap over rationales. Target kappa >= 0.6.",
        "",
        "| code | reference 1s | judge 1s | agreement | kappa [lo, hi] | precision | recall |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in table.iterrows():
        lines.append(
            f"| {r['code']} | {r['ref_ones']} | {r['judge_ones']} | {fnum(r['agree'])} | "
            f"{fmt_ci(r, 2, point='kappa')} | "
            f"{fnum(r['precision'])} | {fnum(r['recall'])} |"
        )
    path = out / "agreement.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
