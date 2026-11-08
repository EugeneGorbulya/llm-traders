"""Message bank, neutral chat feed and manipulator insertions."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from .core import ROOT, ChatMessage, stable_int

DEFAULT_BANK = ROOT / "data" / "messages" / "bank_v1.yaml"
FROZEN_BANK = ROOT / "data" / "messages" / "bank_v1.frozen.json"
# claim_p_high for a message that claims one more official GOOD signal: the claim is
# the posterior with that signal added, so it depends on the market state.
PLUS_GOOD = "plus_good"


@dataclass
class MessageType:
    name: str
    claim_p_high: float | str | None
    paraphrases: list[str]


class MessageBank:
    def __init__(self, data: dict, source: str = "?") -> None:
        self.source = source
        self.ticker = data["ticker"]
        self.types: dict[str, MessageType] = {}
        for name, t in data["types"].items():
            claim = t.get("claim_p_high")
            is_number = isinstance(claim, (int, float))
            if not (claim is None or claim == PLUS_GOOD or is_number):
                raise ValueError(f"{name}: claim_p_high={claim!r}")
            self.types[name] = MessageType(name, claim, list(t["paraphrases"]))
        self.neutral: list[str] = list(data["neutral"])
        self.neutral_accounts: list[str] = list(data["accounts"]["neutral"])
        self.manip_accounts: list[str] = list(data["accounts"]["manipulator"])
        self.sha256 = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    @classmethod
    def load(cls, path: Path | None = None, prefer_frozen: bool = True) -> MessageBank:
        if path is None:
            path = (
                FROZEN_BANK
                if (prefer_frozen and FROZEN_BANK.exists())
                else DEFAULT_BANK
            )
        path = Path(path)
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(data, source=str(path))


def neutral_messages(
    bank: MessageBank, seed: int, period: int, n: int
) -> list[ChatMessage]:
    rng = random.Random(stable_int("neutral", seed, period))
    texts = rng.sample(bank.neutral, k=min(n, len(bank.neutral)))
    accounts = rng.sample(bank.neutral_accounts, k=min(n, len(bank.neutral_accounts)))
    return [
        ChatMessage(period, a, t, kind="neutral")
        for a, t in zip(accounts, texts, strict=False)
    ]


def manipulation_messages(
    bank: MessageBank,
    msg_type: str,
    period: int,
    paraphrase: int,
    n_accounts: int = 1,
    account_offset: int = 0,
) -> list[ChatMessage]:
    paraphrases = bank.types[msg_type].paraphrases
    out = []
    for j in range(n_accounts):
        acct = bank.manip_accounts[(account_offset + j) % len(bank.manip_accounts)]
        idx = (paraphrase + j) % len(paraphrases)
        out.append(
            ChatMessage(
                period,
                acct,
                paraphrases[idx],
                kind="manipulation",
                msg_type=msg_type,
                paraphrase=idx,
            )
        )
    return out


def insert_at(
    base: Sequence[ChatMessage], extra: Sequence[ChatMessage], position: int
) -> list[ChatMessage]:
    base = list(base)
    pos = max(0, min(position, len(base)))
    return base[:pos] + list(extra) + base[pos:]


def window(feed: Sequence[ChatMessage], period: int, k: int) -> list[ChatMessage]:
    return [m for m in feed if period - k < m.period <= period]
