"""Shared types: what an agent sees (Observation) and returns (Decision)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .auction import Order

ROOT = Path(__file__).resolve().parents[1]
N_PERIODS = 12
SIGNAL_PERIODS = (4, 8)
CHAT_WINDOW = 2

Side = Literal["buy", "sell", "hold"]


def stable_int(*parts: Any) -> int:
    h = hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode()
    ).hexdigest()
    return int(h[:16], 16) % (2**31)


@dataclass(frozen=True)
class ChatMessage:
    period: int
    account: str
    text: str
    kind: str = "neutral"
    msg_type: str | None = None
    paraphrase: int | None = None


@dataclass
class PricePoint:
    period: int
    price: float | None
    volume: int


@dataclass
class Observation:
    period: int
    n_periods: int
    cash: float
    shares: int
    price_history: list[PricePoint]
    official: list[tuple[int, str]]
    chat: list[ChatMessage]
    ref_price: float
    sees_chat: bool = True
    chat_window: int = CHAT_WINDOW

    def signals(self) -> list[str]:
        return [s for _, s in self.official]

    def max_affordable(self) -> int:
        if self.ref_price <= 0:
            return 0
        return int(self.cash // self.ref_price)


@dataclass(frozen=True)
class DecisionContext:
    """Per-call inputs that are not part of what the agent sees."""

    seed_parts: tuple[Any, ...] = ()
    tags: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    order: Order | None
    p_high: float | None = None
    fair_value: float | None = None
    rationale: str | None = None
    valid: bool = True
    side: Side | None = None
    p_rescaled: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_log(self) -> dict[str, Any]:
        d = {
            "order": asdict(self.order) if self.order else None,
            "p_high": self.p_high,
            "fair_value": self.fair_value,
            "rationale": self.rationale,
            "valid": self.valid,
            "side": self.side,
            "p_rescaled": self.p_rescaled,
        }
        d.update({k: v for k, v in self.meta.items() if k not in d})
        return d
