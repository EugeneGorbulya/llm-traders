"""Market engine: sessions with twins (level 2) and a scripted-price world (1.5)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .agents import Agent, ScriptedManipulator
from .auction import AuctionResult, Order, clear
from .bayes import (
    ACCURACY,
    HIGH,
    LOW,
    PRIOR_HIGH,
    rational_price,
    value_from_p,
)
from .chat import MessageBank, insert_at, neutral_messages, window
from .core import (
    N_PERIODS,
    ChatMessage,
    Decision,
    DecisionContext,
    Observation,
    PricePoint,
    stable_int,
)
from .llm.log import JsonlLogger


@dataclass
class SessionConfig:
    seed: int
    n_periods: int = N_PERIODS
    low: float = LOW
    high: float = HIGH
    prior_high: float = PRIOR_HIGH
    accuracy: float = ACCURACY
    signal_periods: tuple[int, ...] = (4, 8)
    chat_window: int = 2
    neutral_per_period: int = 3
    value: float | None = None
    signals: dict[int, str] | None = None


def draw_world(cfg: SessionConfig) -> tuple[float, dict[int, str]]:
    rng = random.Random(stable_int("value", cfg.seed))
    if cfg.value is not None:
        value = cfg.value
    else:
        drawn_high = rng.random() < cfg.prior_high
        value = cfg.high if drawn_high else cfg.low
    if cfg.signals is not None:
        return value, dict(cfg.signals)
    sig = {}
    for p in cfg.signal_periods:
        r = random.Random(stable_int("signal", cfg.seed, p)).random()
        correct = r < cfg.accuracy
        good = (value == cfg.high) == correct
        sig[p] = "good" if good else "bad"
    return value, sig


def rational_path(cfg: SessionConfig, signals: dict[int, str]) -> list[float]:
    path = []
    for t in range(1, cfg.n_periods + 1):
        official = [s for p, s in sorted(signals.items()) if p <= t]
        price = rational_price(
            official, cfg.low, cfg.high, cfg.prior_high, cfg.accuracy
        )
        path.append(price)
    return path


def with_wealth(
    holdings: dict[str, dict[str, float]], value: float
) -> dict[str, dict[str, float]]:
    return {
        k: {**v, "wealth": v["cash"] + v["shares"] * value} for k, v in holdings.items()
    }


def insert_manip(
    period_msgs: list[ChatMessage], extra: list[ChatMessage], seed: int, t: int
) -> list[ChatMessage]:
    # The position depends on (seed, period) only, so the twins' feeds differ by the
    # inserted messages and nothing else.
    pos = random.Random(stable_int("pos", seed, t)).randint(0, len(period_msgs))
    return insert_at(period_msgs, extra, pos)


def clip_order(order: Order | None, cash: float, shares: int) -> Order | None:
    if order is None or order.qty <= 0:
        return None
    if order.side == "buy":
        q = min(order.qty, int(cash // order.limit))
    else:
        q = min(order.qty, shares)
    return Order(order.agent_id, order.side, order.limit, q) if q > 0 else None


@dataclass
class SessionResult:
    session_id: str
    arm: str
    value: float
    signals: dict[int, str]
    prices: list[float | None]
    volumes: list[int]
    rational: list[float]
    beliefs: dict[str, list[float | None]]
    final: dict[str, dict[str, float]]
    initial: dict[str, dict[str, float]]
    invalid: dict[str, int]
    chat: list[ChatMessage] = field(default_factory=list)

    def manip_profit(self, manip_id: str = "manip") -> float | None:
        if manip_id not in self.final:
            return None
        return self.final[manip_id]["wealth"] - self.initial[manip_id]["wealth"]


# для У2 (гейт 3)
def run_session(
    cfg: SessionConfig,
    agents: Sequence[Agent],
    bank: MessageBank,
    arm: str = "control",
    attack: dict[str, Any] | None = None,
    logger: JsonlLogger | None = None,
    session_id: str | None = None,
    tags: dict[str, Any] | None = None,
) -> SessionResult:
    logger = logger or JsonlLogger()
    sid = session_id or f"s{cfg.seed}"
    tags = {**(tags or {}), "session": sid, "arm": arm, "seed": cfg.seed}
    value, signals = draw_world(cfg)
    state = {
        a.agent_id: {"cash": float(a.cash), "shares": int(a.shares)} for a in agents
    }
    initial = with_wealth(state, value)
    history: list[PricePoint] = []
    feed: list[ChatMessage] = []
    beliefs: dict[str, list[float | None]] = {a.agent_id: [] for a in agents}
    invalid: dict[str, int] = {a.agent_id: 0 for a in agents}
    rational = rational_path(cfg, signals)
    prior_value = value_from_p(cfg.prior_high, cfg.low, cfg.high)

    for t in range(1, cfg.n_periods + 1):
        official = [(p, s) for p, s in sorted(signals.items()) if p <= t]
        ref = next(
            (pp.price for pp in reversed(history) if pp.price is not None), prior_value
        )

        period_msgs = neutral_messages(bank, cfg.seed, t, cfg.neutral_per_period)
        for a in agents:
            if isinstance(a, ScriptedManipulator):
                mobs = Observation(
                    t,
                    cfg.n_periods,
                    state[a.agent_id]["cash"],
                    state[a.agent_id]["shares"],
                    list(history),
                    official,
                    [],
                    ref,
                )
                extra = a.post(t, attack, mobs, DecisionContext(tags=tags))
                period_msgs = insert_manip(period_msgs, extra, cfg.seed, t)
        feed.extend(period_msgs)
        visible = window(feed, t, cfg.chat_window)

        decisions: dict[str, Decision] = {}
        for a in agents:
            s = state[a.agent_id]
            obs = Observation(
                t,
                cfg.n_periods,
                s["cash"],
                s["shares"],
                list(history),
                official,
                visible if a.sees_chat else [],
                ref,
                sees_chat=a.sees_chat,
                chat_window=cfg.chat_window,
            )
            # No arm in seed_parts: control and manipulation twins draw the same sampling
            # seeds, so they answer identically until their prompts differ and the effect
            # of text is a paired difference.
            decide_tags = {**tags, "agent": a.agent_id, "period": t}
            ctx = DecisionContext(
                seed_parts=(cfg.seed, a.agent_id, t), tags=decide_tags
            )
            d = a.decide(obs, ctx)
            decisions[a.agent_id] = d
            beliefs[a.agent_id].append(d.p_high)
            invalid[a.agent_id] += int(not d.valid)

        orders = [
            clip_order(d.order, state[k]["cash"], state[k]["shares"])
            for k, d in decisions.items()
        ]
        orders = [o for o in orders if o is not None]
        res: AuctionResult = clear(orders, ref_price=ref)
        if res.traded:
            for k, q in res.fills.items():
                state[k]["shares"] += q
                state[k]["cash"] -= q * res.price
        history.append(PricePoint(t, res.price, res.volume))

        logger.write(
            {
                "kind": "period",
                **tags,
                "period": t,
                "value": value,
                "official": official,
                "rational": rational[t - 1],
                "ref_price": ref,
                "chat": [m.__dict__ for m in period_msgs],
                "decisions": {k: d.to_log() for k, d in decisions.items()},
                "orders": [o.__dict__ for o in orders],
                "price": res.price,
                "volume": res.volume,
                "fills": res.fills,
                "holdings": {k: dict(v) for k, v in state.items()},
            }
        )

    final = with_wealth(state, value)
    result = SessionResult(
        sid,
        arm,
        value,
        signals,
        [pp.price for pp in history],
        [pp.volume for pp in history],
        rational,
        beliefs,
        final,
        initial,
        invalid,
        feed,
    )
    logger.write(
        {
            "kind": "session",
            **tags,
            "value": value,
            "signals": signals,
            "prices": result.prices,
            "volumes": result.volumes,
            "rational": rational,
            "final": final,
            "initial": initial,
            "invalid": invalid,
            "beliefs": beliefs,
        }
    )
    return result


# для У1.5 (гейт 2)
PUMP_PERIODS = (3, 4, 5, 6, 7)
PUMP = 0.20


# для У1.5 (гейт 2)
def pumped_path(
    rational: Sequence[float],
    periods: Sequence[int] = PUMP_PERIODS,
    pump: float = PUMP,
) -> list[float]:
    return [
        round(p * (1 + pump), 2) if (t in periods) else round(p, 2)
        for t, p in enumerate(rational, start=1)
    ]


# для У1.5 (гейт 2)
def run_scripted(
    cfg: SessionConfig,
    agent: Agent,
    bank: MessageBank,
    price_mode: str = "rational",
    attack: dict[str, Any] | None = None,
    manipulator: ScriptedManipulator | None = None,
    logger: JsonlLogger | None = None,
    session_id: str | None = None,
    tags: dict[str, Any] | None = None,
    pump_periods: Sequence[int] = PUMP_PERIODS,
    pump: float = PUMP,
    scripted_volume: int = 8,
) -> SessionResult:
    logger = logger or JsonlLogger()
    sid = session_id or f"l15-s{cfg.seed}"
    arm = f"{price_mode}|{'manip' if attack else 'neutral'}"
    tags = {**(tags or {}), "session": sid, "arm": arm, "seed": cfg.seed}
    value, signals = draw_world(cfg)
    rational = rational_path(cfg, signals)
    if price_mode == "pumped":
        path = pumped_path(rational, pump_periods, pump)
    else:
        path = [round(x, 2) for x in rational]
    s = {"cash": float(agent.cash), "shares": int(agent.shares)}
    initial = with_wealth({agent.agent_id: s}, value)
    history: list[PricePoint] = []
    feed: list[ChatMessage] = []
    beliefs: list[float | None] = []
    invalid = 0
    prior_value = value_from_p(cfg.prior_high, cfg.low, cfg.high)
    for t in range(1, cfg.n_periods + 1):
        official = [(p, sg) for p, sg in sorted(signals.items()) if p <= t]
        ref = history[-1].price if history else prior_value
        period_msgs = neutral_messages(bank, cfg.seed, t, cfg.neutral_per_period)
        if manipulator is not None:
            # The manipulator does not trade here, so it sees its fixed holdings.
            mobs = Observation(
                t,
                cfg.n_periods,
                manipulator.cash,
                manipulator.shares,
                list(history),
                official,
                [],
                ref,
            )
            extra = manipulator.post(t, attack, mobs, DecisionContext(tags=tags))
            period_msgs = insert_manip(period_msgs, extra, cfg.seed, t)
        feed.extend(period_msgs)
        obs = Observation(
            t,
            cfg.n_periods,
            s["cash"],
            s["shares"],
            list(history),
            official,
            window(feed, t, cfg.chat_window) if agent.sees_chat else [],
            ref,
            sees_chat=agent.sees_chat,
            chat_window=cfg.chat_window,
        )
        decide_tags = {**tags, "agent": agent.agent_id, "period": t}
        ctx = DecisionContext(
            seed_parts=(cfg.seed, agent.agent_id, t, price_mode), tags=decide_tags
        )
        d = agent.decide(obs, ctx)
        beliefs.append(d.p_high)
        invalid += int(not d.valid)
        price = path[t - 1]
        o = clip_order(d.order, s["cash"], s["shares"])
        filled = 0
        if o is not None:
            if o.side == "buy" and o.limit >= price:
                filled = min(o.qty, int(s["cash"] // price))
            elif o.side == "sell" and o.limit <= price:
                filled = -min(o.qty, s["shares"])
        s["shares"] += filled
        s["cash"] -= filled * price
        history.append(PricePoint(t, price, scripted_volume))
        logger.write(
            {
                "kind": "period",
                **tags,
                "period": t,
                "value": value,
                "official": official,
                "rational": rational[t - 1],
                "price": price,
                "chat": [m.__dict__ for m in period_msgs],
                "decisions": {agent.agent_id: d.to_log()},
                "fill": filled,
                "holdings": dict(s),
            }
        )
    final = with_wealth({agent.agent_id: s}, value)
    res = SessionResult(
        sid,
        arm,
        value,
        signals,
        path,
        [pp.volume for pp in history],
        rational,
        {agent.agent_id: beliefs},
        final,
        initial,
        {agent.agent_id: invalid},
        feed,
    )
    logger.write(
        {
            "kind": "session",
            **tags,
            "value": value,
            "signals": signals,
            "prices": path,
            "rational": rational,
            "beliefs": {agent.agent_id: beliefs},
            "final": final,
        }
    )
    return res
