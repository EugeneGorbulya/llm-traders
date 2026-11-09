"""Model backends: Ollama, OpenAI-compatible, Anthropic."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, fields
from typing import Any

from .config import ModelConfig


@dataclass
class RawResponse:
    text: str
    thinking: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> RawResponse:
        # The cache is kept in git and outlives code changes: fields that this
        # version no longer has are dropped instead of breaking every cache hit.
        known = {f.name for f in fields(cls)}
        kept = {k: v for k, v in rec.items() if k in known}
        return cls(**kept)


class Backend:
    def digest(self, cfg: ModelConfig) -> str:
        return cfg.model

    def generate(
        self,
        cfg: ModelConfig,
        messages: list[dict[str, str]],
        schema: dict | None,
        seed: int | None,
    ) -> RawResponse:
        raise NotImplementedError


class OllamaBackend(Backend):
    def __init__(self) -> None:
        self._digests: dict[str, str] = {}

    def _url(self, cfg: ModelConfig, path: str) -> str:
        return cfg.base_url.rstrip("/") + path

    def _request(
        self, url: str, payload: dict | None = None, timeout: float = 900
    ) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def digest(self, cfg: ModelConfig) -> str:
        if cfg.model not in self._digests:
            tags = self._request(self._url(cfg, "/api/tags"), timeout=10)
            for m in tags.get("models", []):
                self._digests[m["name"]] = m.get("digest", "?")
                self._digests.setdefault(
                    m.get("model", m["name"]), m.get("digest", "?")
                )
        if cfg.model not in self._digests:
            raise RuntimeError(f"{cfg.model} is not pulled: ollama pull {cfg.model}")
        return self._digests[cfg.model]

    def generate(
        self,
        cfg: ModelConfig,
        messages: list[dict[str, str]],
        schema: dict | None,
        seed: int | None,
    ) -> RawResponse:
        options = dict(cfg.options)
        if seed is not None:
            options["seed"] = seed
        options.setdefault("num_ctx", 8192)
        if cfg.max_tokens:
            options["num_predict"] = cfg.max_tokens
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": cfg.extra.get("keep_alive", "30m"),
        }
        if schema is not None:
            payload["format"] = schema
        if cfg.think is not None:
            payload["think"] = cfg.think
        t0 = time.perf_counter()
        r = self._request(self._url(cfg, "/api/chat"), payload)
        dt = (time.perf_counter() - t0) * 1000
        msg = r.get("message", {})
        return RawResponse(
            text=msg.get("content", ""),
            thinking=msg.get("thinking"),
            tokens_in=r.get("prompt_eval_count"),
            tokens_out=r.get("eval_count"),
            latency_ms=dt,
            extra={"done_reason": r.get("done_reason")},
        )


# для API-моделей (гейт 1, если будет доступ)
class OpenAICompatBackend(Backend):
    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def _client(self, cfg: ModelConfig):
        key = f"{cfg.base_url}|{cfg.api_key_env}"
        if key not in self._clients:
            from openai import OpenAI

            api_key = os.environ.get(cfg.api_key_env or "OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    f"set {cfg.api_key_env or 'OPENAI_API_KEY'} for model {cfg.name}"
                )
            self._clients[key] = (
                OpenAI(api_key=api_key, base_url=cfg.base_url)
                if cfg.base_url
                else OpenAI(api_key=api_key)
            )
        return self._clients[key]

    def generate(
        self,
        cfg: ModelConfig,
        messages: list[dict[str, str]],
        schema: dict | None,
        seed: int | None,
    ) -> RawResponse:
        kwargs: dict[str, Any] = {"model": cfg.model, "messages": messages}
        for k in ("temperature", "top_p"):
            if k in cfg.options:
                kwargs[k] = cfg.options[k]
        if seed is not None and cfg.extra.get("send_seed", True):
            kwargs["seed"] = seed
        if cfg.max_tokens:
            kwargs["max_tokens"] = cfg.max_tokens
        if cfg.think in ("low", "medium", "high"):
            kwargs["reasoning_effort"] = cfg.think
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": schema, "strict": True},
            }
        kwargs.update(cfg.extra.get("request", {}))
        t0 = time.perf_counter()
        r = self._client(cfg).chat.completions.create(**kwargs)
        dt = (time.perf_counter() - t0) * 1000
        u = getattr(r, "usage", None)
        return RawResponse(
            text=r.choices[0].message.content or "",
            tokens_in=getattr(u, "prompt_tokens", None),
            tokens_out=getattr(u, "completion_tokens", None),
            latency_ms=dt,
            extra={"system_fingerprint": getattr(r, "system_fingerprint", None)},
        )


# API models of gate 1: claude-haiku-5.5 and claude-sonnet-5.5 on the level-1 grid.
class AnthropicBackend(Backend):
    def __init__(self) -> None:
        self._client = None

    def generate(
        self,
        cfg: ModelConfig,
        messages: list[dict[str, str]],
        schema: dict | None,
        seed: int | None,
    ) -> RawResponse:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=os.environ.get(cfg.api_key_env or "ANTHROPIC_API_KEY")
            )
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        conv = [m for m in messages if m["role"] != "system"]
        # No sampling options and no seed: Haiku 5.5 and Sonnet 5.5 answer 400 to
        # non-default sampling, so the API models run with the default one.
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens or 1024,
            "system": system,
            "messages": conv,
        }
        # Thinking is set per model: "disabled" on Haiku 5.5, "between_tools" on
        # Sonnet 5.5, which rejects "disabled".
        if "thinking" in cfg.extra:
            kwargs["thinking"] = cfg.extra["thinking"]
        # JSON outputs instead of a forced tool call: Sonnet 5.5 rejects forced tool use.
        if schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }
        t0 = time.perf_counter()
        r = self._client.messages.create(**kwargs)
        dt = (time.perf_counter() - t0) * 1000
        text = "".join(b.text for b in r.content if b.type == "text")
        thinking_text = next(
            (b.thinking for b in r.content if b.type == "thinking"), None
        )
        return RawResponse(
            text=text,
            thinking=thinking_text or None,
            tokens_in=r.usage.input_tokens,
            tokens_out=r.usage.output_tokens,
            latency_ms=dt,
            extra={"stop_reason": r.stop_reason},
        )


def make_backend(name: str) -> Backend:
    if name == "ollama":
        return OllamaBackend()
    if name == "openai_compat":
        return OpenAICompatBackend()
    if name == "anthropic":
        return AnthropicBackend()
    if name == "mock":
        from .mock import MockBackend

        return MockBackend()
    raise ValueError(f"unknown backend {name!r}")
