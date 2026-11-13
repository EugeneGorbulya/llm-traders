"""Level 1.5: one agent over 12 periods, scripted price x chat (2x2 design)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import LLMTrader, ScriptedManipulator
from .bayes import posterior_high
from .chat import MessageBank
from .core import ROOT
from .llm.config import get_model
from .market import SessionConfig, run_scripted
from .prompts import PROMPT_VERSION, PromptConfig
from .results import (
    RESULTS,
    load_yaml,
    make_client,
    read_jsonl,
    session_log,
    write_jsonl,
)

CONFIG = ROOT / "configs" / "level15.yaml"
NEUTRAL = "neutral"


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return load_yaml(path)


@dataclass(frozen=True)
class Session:
    value: float
    seed: int
    price_mode: str
    chat: str

    @property
    def session_id(self) -> str:
        return f"v{int(self.value)}-s{self.seed}-{self.price_mode}-{self.chat}"


def plan(cfg: dict[str, Any], seeds: int | None = None) -> list[Session]:
    # The neutral-chat cells do not depend on the attack type: each runs once and is
    # the twin of both attacks, so a seed needs 6 sessions instead of 8.
    chats = [NEUTRAL, *cfg["attacks"]]
    sessions = []
    for value, value_seeds in cfg["seeds"].items():
        chosen = value_seeds[:seeds] if seeds else value_seeds
        for seed in chosen:
            for mode in cfg["price_modes"]:
                for chat in chats:
                    sessions.append(Session(float(value), seed, mode, chat))
    return sessions


def full_runs(root: Path = RESULTS / "level15") -> list[Path]:
    """Run directories with every seed of the config (a smoke run has fewer)."""
    seeds = {s for value_seeds in load_config()["seeds"].values() for s in value_seeds}
    out = []
    for path in sorted(Path(root).glob("*/sessions.jsonl")):
        done = {r["seed"] for r in read_jsonl(path) if r["kind"] == "session"}
        if seeds <= done:
            out.append(path.parent)
    return out


def run(
    model: str,
    *,
    seeds: int | None = None,
    out_dir: Path | None = None,
    cache_path: Path | None = None,
) -> Path:
    cfg = load_config()
    bank = MessageBank.load()
    mcfg = get_model(model)
    out = Path(out_dir) if out_dir else RESULTS / "level15" / model
    client = make_client(out, cache_path)
    logger = session_log(out)
    pcfg = PromptConfig(ticker=bank.ticker)
    rows = []
    for s in plan(cfg, seeds):
        agent = LLMTrader(
            agent_id="trader",
            cash=float(cfg["cash"]),
            shares=int(cfg["shares"]),
            model=mcfg,
            client=client,
            prompt_cfg=pcfg,
        )
        attack = None
        manipulator = None
        if s.chat != NEUTRAL:
            attack = {"type": s.chat}
            manipulator = ScriptedManipulator(
                agent_id="manip",
                cash=0,
                shares=0,
                bank=bank,
                seed=s.seed,
                msg_periods=tuple(cfg["msg_periods"]),
            )
        res = run_scripted(
            SessionConfig(seed=s.seed, value=s.value),
            agent,
            bank,
            price_mode=s.price_mode,
            attack=attack,
            manipulator=manipulator,
            logger=logger,
            session_id=s.session_id,
            tags={"model": model, "chat": s.chat},
            pump_periods=tuple(cfg["pump_periods"]),
            pump=float(cfg["pump"]),
        )
        beliefs = res.beliefs["trader"]
        for t, p in enumerate(beliefs, start=1):
            official = [
                sig for period, sig in sorted(res.signals.items()) if period <= t
            ]
            rows.append(
                {
                    "version": cfg["version"],
                    "prompt_version": PROMPT_VERSION,
                    "bank_sha256": bank.sha256,
                    "model": model,
                    "session": s.session_id,
                    "value": s.value,
                    "seed": s.seed,
                    "price_mode": s.price_mode,
                    "chat": s.chat,
                    "period": t,
                    "p_high": p,
                    "rational_p": posterior_high(official),
                    "price": res.prices[t - 1],
                    "rational_price": res.rational[t - 1],
                    "valid": p is not None,
                }
            )
    write_jsonl(out / "results.jsonl", rows)
    return out
