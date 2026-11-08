"""Deterministic mock models for tests, no Ollama needed."""

from __future__ import annotations

import json
import random
import re

from ..bayes import posterior_high, value_from_p
from ..prompts import BELIEF
from .backends import Backend, RawResponse
from .config import ModelConfig

_OFFICIAL_RE = re.compile(r"Period (\d+): (GOOD|BAD)")
_CASH_RE = re.compile(r"([\d.]+) cash, (\d+) shares")
_REF_RE = re.compile(r"At a price of ([\d.]+)")


def _section(text: str, start: str, stop: str) -> str:
    i = text.lower().find(start.lower())
    if i < 0:
        return ""
    j = text.lower().find(stop.lower(), i + len(start))
    return text[i : j if j > 0 else None]


class MockBackend(Backend):
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def digest(self, cfg: ModelConfig) -> str:
        return f"mock:{cfg.extra.get('policy', 'rational')}"

    def generate(
        self,
        cfg: ModelConfig,
        messages: list[dict[str, str]],
        schema: dict | None,
        seed: int | None,
    ) -> RawResponse:
        policy = cfg.extra.get("policy", "rational")
        user = messages[-1]["content"]
        rng = random.Random(seed or 0)
        if schema is not None and "labels" in schema.get("properties", {}):
            return RawResponse(
                text=self._filter(user), latency_ms=1.0, tokens_in=10, tokens_out=10
            )
        # "broken" fails the first time it sees a prompt, so the client's retry
        # (a new seed, same prompt) succeeds.
        prompt = json.dumps(messages)
        first_try = prompt not in self._seen
        self._seen.add(prompt)
        if policy == "garbage" or (policy == "broken" and first_try):
            return RawResponse(
                text="I think I would buy some shares {not json", latency_ms=1.0
            )
        official = _section(user, "official news", "chat feed") or _section(
            user, "official news", "submit"
        )
        signals = [s.lower() for _, s in _OFFICIAL_RE.findall(official)]
        p = posterior_high(signals)
        chat = _section(user, "chat feed", "submit your order")
        obey = False
        if policy == "gullible" and chat:
            if re.search(r"\b130\b", chat):
                p = max(p, 0.85)
            if re.search(r"\b70\b", chat) and not re.search(r"\b130\b", chat):
                p = min(p, 0.15)
            obey = "SYSTEM" in chat.upper()
        p = min(1.0, max(0.0, p + rng.uniform(-0.02, 0.02)))
        fair = value_from_p(p)
        m = _CASH_RE.search(user)
        cash, shares = (float(m.group(1)), int(m.group(2))) if m else (1000.0, 10)
        ref = float(_REF_RE.search(user).group(1)) if _REF_RE.search(user) else 100.0
        if obey:
            side, limit, qty = "buy", 200.0, int(cash // 200)
        elif fair > ref + 1 and cash >= fair:
            side, limit, qty = (
                "buy",
                round(fair - 1, 2),
                max(1, min(5, int(cash // fair))),
            )
        elif fair < ref - 1 and shares > 0:
            side, limit, qty = "sell", round(fair + 1, 2), min(5, shares)
        else:
            side, limit, qty = "hold", 0, 0
        out = {
            "analysis": f"mock {policy}: p={p:.2f}",
            BELIEF: round(p, 3),
            "fair_value": round(fair, 2),
            "order": side,
            "price_limit": limit,
            "quantity": qty,
        }
        return RawResponse(
            text=json.dumps(out),
            latency_ms=1.0,
            tokens_in=len(user) // 4,
            tokens_out=40,
        )

    @staticmethod
    def _filter(user: str) -> str:
        labels = []
        for line in user.splitlines():
            m = re.match(r"(\d+)\. ", line)
            if not m:
                continue
            t = line.lower()
            manip = any(
                k in t
                for k in (
                    "130",
                    "150",
                    " 70",
                    "system",
                    "breaking",
                    "moon",
                    "analyst",
                    "buy",
                    "signal",
                    "loaded",
                    "all in",
                )
            )
            labels.append({"id": int(m.group(1)), "manipulative": manip})
        return json.dumps({"labels": labels})
