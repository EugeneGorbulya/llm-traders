"""query(): cache, backend call, JSON parsing, one retry, JSONL log."""

from __future__ import annotations

import json
import re
import urllib.error
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core import stable_int
from .backends import OLLAMA_URL, Backend, RawResponse, make_backend
from .cache import ResponseCache, make_key
from .config import ModelConfig
from .log import JsonlLogger

Validator = Callable[[dict[str, Any]], tuple[bool, dict[str, Any], str | None]]

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
MAX_SERVER_ERRORS_IN_A_ROW = 6


def extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.DOTALL)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = _JSON_OBJ.search(t)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


@dataclass
class CallResult:
    parsed: dict[str, Any] | None
    valid: bool
    error: str | None
    attempts: int
    cache_hits: int
    key: str
    latency_ms: float


@dataclass
class LLMClient:
    cache: ResponseCache | None = None
    logger: JsonlLogger = field(default_factory=JsonlLogger)
    max_retries: int = 1
    offline: bool = False
    _backends: dict[str, Backend] = field(default_factory=dict)
    stats: dict[str, int] = field(
        default_factory=lambda: {"calls": 0, "hits": 0, "invalid": 0}
    )
    _server_errors_in_a_row: int = field(default=0, init=False)

    def backend(self, cfg: ModelConfig) -> Backend:
        if cfg.backend not in self._backends:
            self._backends[cfg.backend] = make_backend(cfg.backend)
        return self._backends[cfg.backend]

    def query(
        self,
        cfg: ModelConfig,
        messages: list[dict[str, str]],
        schema: dict | None = None,
        validate: Validator | None = None,
        sample_idx: int = 0,
        seed_parts: tuple = (),
        prompt_version: str = "?",
        tags: dict[str, Any] | None = None,
    ) -> CallResult:
        be = self.backend(cfg)
        digest = be.digest(cfg)
        total_ms, hits = 0.0, 0
        last: RawResponse | None = None
        error: str | None = None
        key = ""
        for attempt in range(self.max_retries + 1):
            seed = stable_int("sample", cfg.name, *seed_parts, sample_idx, attempt)
            key = make_key(
                {
                    "model": cfg.cache_identity(),
                    "digest": digest,
                    "messages": messages,
                    "schema": schema,
                    "sample": sample_idx,
                    "attempt": attempt,
                    "seed": seed,
                }
            )
            rec = self.cache.get(key) if self.cache else None
            cache_hit = rec is not None
            if cache_hit:
                hits += 1
                last = RawResponse.from_record(rec["raw"])
            else:
                if self.offline:
                    raise RuntimeError(f"offline mode: cache miss for {cfg.name}")
                try:
                    last = be.generate(cfg, messages, schema, seed)
                    self._server_errors_in_a_row = 0
                except urllib.error.HTTPError as e:
                    # 4xx means a setup error (tag not pulled, bad request): stop, or
                    # the whole grid would be logged as invalid model answers. 5xx
                    # (out of memory, context overflow) is a failed answer: retry.
                    if e.code < 500:
                        raise RuntimeError(
                            f"{cfg.name}: HTTP {e.code} {e.reason}"
                        ) from e
                    # But a crashed llama-server answers every call with 500: after a
                    # run of them the model cannot run at all, so stop the run.
                    self._server_errors_in_a_row += 1
                    if self._server_errors_in_a_row >= MAX_SERVER_ERRORS_IN_A_ROW:
                        raise RuntimeError(
                            f"{cfg.name}: HTTP {e.code} {e.reason} "
                            f"{MAX_SERVER_ERRORS_IN_A_ROW} раз подряд"
                        ) from e
                    last = RawResponse(text="", error=repr(e))
                except TimeoutError as e:
                    last = RawResponse(text="", error=repr(e))
                except (urllib.error.URLError, ConnectionError) as e:
                    url = cfg.base_url or OLLAMA_URL
                    raise RuntimeError(f"Ollama не отвечает на {url}") from e
                # Failures are not cached, so a rerun asks the model again.
                if self.cache and last.error is None:
                    self.cache.put(key, cfg.name, {"raw": asdict(last)})
            total_ms += last.latency_ms or 0.0
            parsed = extract_json(last.text)
            if parsed is None:
                ok, norm, error = False, None, "invalid JSON"
            elif validate is None:
                ok, norm, error = True, parsed, None
            else:
                ok, norm, error = validate(parsed)
            if last.error is not None:
                ok, error = False, last.error
            self.stats["calls"] += 1
            self.stats["hits"] += int(cache_hit)
            self.logger.write(
                {
                    "kind": "llm_call",
                    "model": cfg.name,
                    "backend": cfg.backend,
                    "model_id": cfg.model,
                    "digest": digest,
                    "options": cfg.options,
                    "think": cfg.think,
                    "prompt_version": prompt_version,
                    "sample": sample_idx,
                    "attempt": attempt,
                    "seed": seed,
                    "key": key,
                    "cache_hit": cache_hit,
                    "messages": messages,
                    "raw": last.text,
                    "thinking": last.thinking,
                    "parsed": norm if ok else parsed,
                    "valid": ok,
                    "error": error,
                    "tokens_in": last.tokens_in,
                    "tokens_out": last.tokens_out,
                    "latency_ms": last.latency_ms,
                    "tags": tags or {},
                }
            )
            if ok:
                return CallResult(
                    parsed=norm,
                    valid=True,
                    error=None,
                    attempts=attempt + 1,
                    cache_hits=hits,
                    key=key,
                    latency_ms=total_ms,
                )
        self.stats["invalid"] += 1
        return CallResult(
            parsed=None,
            valid=False,
            error=error,
            attempts=self.max_retries + 1,
            cache_hits=hits,
            key=key,
            latency_ms=total_ms,
        )
