"""Single-price call auction that clears all limit orders of one period."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Order:
    agent_id: str
    side: str
    limit: float
    qty: int

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError(f"bad side {self.side!r}")
        if self.qty < 0:
            raise ValueError("negative qty")
        if not (self.limit > 0 and math.isfinite(self.limit)):
            raise ValueError("limit must be positive and finite")


@dataclass
class AuctionResult:
    price: float | None
    volume: int
    fills: dict[str, int] = field(default_factory=dict)

    @property
    def traded(self) -> bool:
        return self.volume > 0


def _demand(orders: Sequence[Order], p: float) -> int:
    return sum(o.qty for o in orders if o.side == "buy" and o.limit >= p)


def _supply(orders: Sequence[Order], p: float) -> int:
    return sum(o.qty for o in orders if o.side == "sell" and o.limit <= p)


def _ration(
    orders: list[Order], volume: int, best_first_key: Callable[[float], float]
) -> dict[str, int]:
    # Price priority first (better limits fill first), then pro rata inside one
    # price level. Largest-remainder rounding gives whole shares that sum exactly
    # to the volume; ties go by agent id, so twin runs allocate identically.
    alloc: dict[str, int] = {}
    remaining = volume
    levels: dict[float, list[Order]] = {}
    for o in orders:
        levels.setdefault(o.limit, []).append(o)
    for lvl in sorted(levels, key=best_first_key):
        group = sorted(levels[lvl], key=lambda o: o.agent_id)
        want = sum(o.qty for o in group)
        if remaining <= 0:
            break
        if want <= remaining:
            for o in group:
                alloc[o.agent_id] = alloc.get(o.agent_id, 0) + o.qty
            remaining -= want
            continue
        shares = [remaining * o.qty / want for o in group]
        base = [math.floor(s) for s in shares]
        left = remaining - sum(base)
        order_idx = sorted(
            range(len(group)), key=lambda i: (-(shares[i] - base[i]), group[i].agent_id)
        )
        for i in order_idx[:left]:
            base[i] += 1
        for o, b in zip(group, base, strict=True):
            if b:
                alloc[o.agent_id] = alloc.get(o.agent_id, 0) + b
        remaining = 0
    return alloc


def clear(orders: Sequence[Order], ref_price: float | None = None) -> AuctionResult:
    live = [o for o in orders if o.qty > 0]
    buys = [o for o in live if o.side == "buy"]
    sells = [o for o in live if o.side == "sell"]
    if not buys or not sells:
        return AuctionResult(price=None, volume=0)

    # Clearing price, in this order: (1) maximise executed volume, the standard
    # call-auction rule; (2) among ties, minimise |demand - supply|; (3) then the
    # price nearest the reference (last trade, else the middle of the tied range),
    # so a flat range of equal prices does not make the price jump; (4) then the
    # lower price, so the choice is deterministic.
    candidates = sorted({o.limit for o in live})
    scored = []
    for p in candidates:
        d, s = _demand(live, p), _supply(live, p)
        scored.append((p, min(d, s), abs(d - s)))
    best_v = max(v for _, v, _ in scored)
    if best_v == 0:
        return AuctionResult(price=None, volume=0)
    tied = [t for t in scored if t[1] == best_v]
    best_imb = min(t[2] for t in tied)
    tied = [t for t in tied if t[2] == best_imb]
    prices = [t[0] for t in tied]
    target = ref_price if ref_price is not None else (min(prices) + max(prices)) / 2
    p_star, v, _ = min(tied, key=lambda t: (abs(t[0] - target), t[0]))

    elig_buys = [o for o in buys if o.limit >= p_star]
    elig_sells = [o for o in sells if o.limit <= p_star]
    buy_alloc = _ration(elig_buys, v, best_first_key=lambda lvl: -lvl)
    sell_alloc = _ration(elig_sells, v, best_first_key=lambda lvl: lvl)

    fills: dict[str, int] = {}
    for a, q in buy_alloc.items():
        fills[a] = fills.get(a, 0) + q
    for a, q in sell_alloc.items():
        fills[a] = fills.get(a, 0) - q
    return AuctionResult(
        price=round(p_star, 2),
        volume=v,
        fills=fills,
    )
