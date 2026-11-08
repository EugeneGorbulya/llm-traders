"""JSONL log of every model call, stamped with the git commit."""

from __future__ import annotations

import json
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..core import ROOT

# Only code and inputs make a run dirty: by its first log line a run has already
# written results/ (results.jsonl, the cache), which would mark every run dirty.
CODE_PATHS = ("llmtraders", "experiments", "analysis", "configs", "data")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


@lru_cache(maxsize=1)
def git_commit() -> str:
    try:
        head = _git("rev-parse", "--short", "HEAD")
        status = _git("status", "--porcelain", "--", *CODE_PATHS)
    except (OSError, subprocess.SubprocessError):
        return "nogit"
    if head.returncode != 0:
        return "nocommit"
    dirty = "-dirty" if status.stdout.strip() else ""
    return head.stdout.strip() + dirty


class JsonlLogger:
    """Appends one JSON line per record; with path=None records are dropped."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        record = {"ts": time.time(), "git": git_commit(), **record}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
