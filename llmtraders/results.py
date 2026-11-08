"""Where experiment output goes (results/) and the shared response cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import ROOT
from .llm.cache import ResponseCache
from .llm.client import LLMClient
from .llm.log import JsonlLogger

RESULTS = ROOT / "results"
CACHE = RESULTS / "cache.sqlite"


def make_client(out_dir: Path, cache_path: Path | None = None) -> LLMClient:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "calls.jsonl").unlink(missing_ok=True)
    return LLMClient(
        cache=ResponseCache(cache_path or CACHE),
        logger=JsonlLogger(out_dir / "calls.jsonl"),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
