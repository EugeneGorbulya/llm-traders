"""SQLite response cache: free re-runs and byte-identical twins."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def make_key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class ResponseCache:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " key TEXT PRIMARY KEY, model TEXT, created REAL, record TEXT)"
        )
        self._conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT record FROM responses WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, model: str, record: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO responses(key, model, created, record) VALUES (?,?,?,?)",
            (key, model, time.time(), json.dumps(record, ensure_ascii=False)),
        )
        self._conn.commit()
