"""Message bank: embedding check and freezing."""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import combinations
from pathlib import Path

import numpy as np
import yaml

from .chat import DEFAULT_BANK, FROZEN_BANK, MessageBank
from .results import RESULTS

REPORT = RESULTS / "bank_check.md"
EMBED_MODEL = "sentence-transformers/all-mpnet-base-v2"
MIN_COS_TO_REF = 0.6
MAX_PAIR_COS = 0.95


def _encoder() -> Callable[[list[str]], np.ndarray]:
    from sentence_transformers import SentenceTransformer

    st = SentenceTransformer(EMBED_MODEL)
    return lambda texts: np.asarray(
        st.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    )


def check(
    bank_path: Path = DEFAULT_BANK,
    out: Path = REPORT,
    encode: Callable[[list[str]], np.ndarray] | None = None,
) -> Path:
    data = yaml.safe_load(Path(bank_path).read_text(encoding="utf-8"))
    encode = encode or _encoder()
    lines = [
        f"# Bank check: {Path(bank_path).name}",
        "",
        f"bank sha256: `{MessageBank(data).sha256}`",
        "",
        "| type | n | cos->ref min | cos->ref mean | pairwise mean |",
        "|---|---|---|---|---|",
    ]
    flags = []
    for name, t in data["types"].items():
        paras = t["paraphrases"]
        e = encode(paras)
        e = e / np.linalg.norm(e, axis=1, keepdims=True)
        to_ref = e[1:] @ e[0]
        pairs = [
            (i, j, float(e[i] @ e[j])) for i, j in combinations(range(len(paras)), 2)
        ]
        lines.append(
            f"| {name} | {len(paras)} | {to_ref.min():.2f} | {to_ref.mean():.2f} | "
            f"{np.mean([s for _, _, s in pairs]):.2f} |"
        )
        flags += [
            f"{name}[{k}] cos {s:.2f} to the reference - check the meaning: {paras[k]!r}"
            for k, s in enumerate(to_ref, start=1)
            if s < MIN_COS_TO_REF
        ]
        flags += [
            f"{name}[{i}] and [{j}] near-duplicates (cos {s:.2f})"
            for i, j, s in pairs
            if s > MAX_PAIR_COS
        ]
    lines += ["", "## Flags", ""] + ([f"- {f}" for f in flags] or ["None."])
    lines += [
        "",
        "## Manual review (before freeze)",
        "",
        "- [ ] Every paraphrase read; meaning equals the type's reference.",
        "- [ ] Fake facts stay inside the rules (70 or 130); only `impossible_150` is outside.",
        "- [ ] Neutral chat carries no price information.",
        "",
    ]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    return Path(out)


def freeze(bank_path: Path = DEFAULT_BANK, frozen: Path = FROZEN_BANK) -> str:
    frozen = Path(frozen)
    if frozen.exists():
        raise FileExistsError(f"{frozen.name} already exists: the bank is frozen")
    data = yaml.safe_load(Path(bank_path).read_text(encoding="utf-8"))
    frozen.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return MessageBank.load(frozen).sha256
