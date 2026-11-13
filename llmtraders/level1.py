"""Level-1 grid: one agent, one market snapshot, one chat condition per call."""

from __future__ import annotations

import json
import random
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import LLMTrader
from .bayes import posterior_high
from .chat import (
    PLUS_GOOD,
    MessageBank,
    insert_at,
    manipulation_messages,
    neutral_messages,
)
from .core import (
    ROOT,
    ChatMessage,
    DecisionContext,
    Observation,
    PricePoint,
    stable_int,
)
from .llm.config import get_model
from .prompts import PROMPT_VERSION, PromptConfig
from .results import RESULTS, load_yaml, make_client

CONFIG = ROOT / "configs" / "level1.yaml"
RUNS = RESULTS / "level1"
FINBERT_DIR = RUNS / "finbert"
TASK_KINDS = ("no_chat", "neutral", "official", "attack")


def run_dirs() -> list[Path]:
    """The level-1 runs of the LLM traders (FinBERT keeps another schema)."""
    found = []
    for d in sorted(RUNS.iterdir()):
        if (d / "results.jsonl").exists() and d != FINBERT_DIR:
            found.append(d)
    return found


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return load_yaml(path)


@dataclass(frozen=True)
class Task:
    condition: str
    kind: str
    msg_type: str | None
    n_accounts: int
    paraphrase: int
    state: str
    state_idx: int
    sample: int
    position: int

    @property
    def group(self) -> tuple[int, str, int]:
        return (self.paraphrase, self.state, self.sample)


def build_tasks(
    cfg: dict[str, Any], conditions: Sequence[str] | None = None
) -> list[Task]:
    n_slots = cfg["snapshot"]["neutral_per_period"] + 1
    tasks = []
    for c in cfg["conditions"]:
        # An unknown kind would run as a neutral feed under the condition's name.
        if c["kind"] not in TASK_KINDS:
            raise ValueError(f"{c['name']}: kind {c['kind']!r}, expected {TASK_KINDS}")
        named = bool(conditions) and c["name"] in conditions
        if conditions and not named:
            continue
        # An extra condition is outside the main grid: it runs only when named.
        if c.get("extra") and not named:
            continue
        paras = [0] if c["kind"] == "no_chat" else range(cfg["paraphrases"])
        for si, state in enumerate(cfg["states"]):
            for i in paras:
                for s in range(cfg["samples"]):
                    tasks.append(
                        Task(
                            c["name"],
                            c["kind"],
                            c.get("type"),
                            int(c.get("n_accounts", 1)),
                            i,
                            state,
                            si,
                            s,
                            (i + si) % n_slots,
                        )
                    )
    return tasks


def subset(tasks: list[Task], limit: int) -> list[Task]:
    per_group = Counter(t.group for t in tasks if t.kind != "no_chat")
    groups = sorted(per_group)
    random.Random(0).shuffle(groups)
    chosen, n = set(), 0
    for g in groups:
        if chosen and n + per_group[g] > limit:
            break
        chosen.add(g)
        n += per_group[g]
    state_samples = {(st, sm) for _, st, sm in chosen}

    def keep(t: Task) -> bool:
        # no_chat has a single paraphrase, so it follows the chosen (state, sample).
        if t.kind == "no_chat":
            return (t.state, t.sample) in state_samples
        return t.group in chosen

    return [t for t in tasks if keep(t)]


def plan(
    conditions: Sequence[str] | None = None,
    samples: int | None = None,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[Task]]:
    cfg = load_config()
    if samples:
        cfg["samples"] = samples
    tasks = build_tasks(cfg, conditions)
    if limit:
        tasks = subset(tasks, limit)
    return cfg, tasks


def official_signals(
    cfg: dict[str, Any], state: str, condition: str
) -> list[tuple[int, str]]:
    """The official record of a snapshot: the signals of its state, plus one more in
    the snapshot period for an official-news condition."""
    official = [(int(p), s) for p, s in cfg["states"][state]["signals"]]
    cond = next(c for c in cfg["conditions"] if c["name"] == condition)
    if cond["kind"] == "official":
        official.append((int(cfg["snapshot"]["period"]), cond.get("signal", "good")))
    return official


def build_observation(
    task: Task, cfg: dict[str, Any], bank: MessageBank
) -> tuple[Observation, dict[str, Any]]:
    snap, st = cfg["snapshot"], cfg["states"][task.state]
    period, window = int(snap["period"]), int(snap["chat_window"])
    base = [s for _, s in st["signals"]]
    official = official_signals(cfg, task.state, task.condition)
    history = [
        PricePoint(t, float(p), int(snap["volume"]))
        for t, p in enumerate(st["prices"], start=1)
    ]

    # The neutral feed depends only on the paraphrase index: every condition with
    # paraphrase i, including its neutral twin, sees the same neutral messages.
    feed_seed = stable_int("l1-feed", task.paraphrase)
    feed: list[ChatMessage] = []
    attack: list[ChatMessage] = []
    for t in range(period - window + 1, period + 1):
        msgs = neutral_messages(bank, feed_seed, t, int(snap["neutral_per_period"]))
        if t == period and task.kind == "attack":
            attack = manipulation_messages(
                bank,
                task.msg_type,
                period,
                task.paraphrase,
                n_accounts=task.n_accounts,
                account_offset=task.paraphrase % len(bank.manip_accounts),
            )
            # position = (paraphrase + state index) mod slots, set in build_tasks: the same
            # for every condition of a group and rotating across groups, so the position
            # is balanced and not tied to one message.
            msgs = insert_at(msgs, attack, task.position)
        feed.extend(msgs)

    sees_chat = task.kind != "no_chat"
    obs = Observation(
        period=period,
        n_periods=int(snap["n_periods"]),
        cash=float(snap["cash"]),
        shares=int(snap["shares"]),
        price_history=history,
        official=official,
        chat=feed if sees_chat else [],
        ref_price=history[-1].price,
        sees_chat=sees_chat,
        chat_window=window,
    )

    claim = None
    if task.kind == "official":
        claim = posterior_high(base + ["good"])
    elif task.msg_type:
        c = bank.types[task.msg_type].claim_p_high
        if c == PLUS_GOOD:
            claim = posterior_high(base + ["good"])
        elif c is not None:
            claim = float(c)
    info = {
        "rational_p": posterior_high([s for _, s in official]),
        "claim_p": claim,
        "ref_price": obs.ref_price,
        "attack_texts": [m.text for m in attack],
    }
    return obs, info


def out_dir_for(model: str, defenses: Sequence[str] = (), fmt: str = "a") -> Path:
    name = model
    if defenses:
        name += "_" + "+".join(defenses)
    if fmt != "a":
        name += "_fmt" + fmt
    return RUNS / name


def run(
    model: str,
    *,
    limit: int | None = None,
    conditions: Sequence[str] | None = None,
    defenses: Sequence[str] = (),
    samples: int | None = None,
    fmt: str = "a",
    out_dir: Path | None = None,
    cache_path: Path | None = None,
    quiet: bool = False,
) -> Path:
    cfg, tasks = plan(conditions, samples, limit)
    bank = MessageBank.load()
    mcfg = get_model(model)
    pcfg = PromptConfig(
        ticker=bank.ticker,
        n_periods=int(cfg["snapshot"]["n_periods"]),
        signal_periods=None,
        defenses=tuple(defenses),
        fmt=fmt,
    )
    out = Path(out_dir) if out_dir else out_dir_for(model, defenses, fmt)
    client = make_client(out, cache_path)
    t0 = time.time()
    with (out / "results.jsonl").open("w", encoding="utf-8") as f:
        for k, task in enumerate(tasks, start=1):
            obs, info = build_observation(task, cfg, bank)
            trader = LLMTrader(
                agent_id="trader",
                cash=obs.cash,
                shares=obs.shares,
                model=mcfg,
                client=client,
                prompt_cfg=pcfg,
                sample_idx=task.sample,
            )
            ctx = DecisionContext(
                # No condition in seed_parts: all conditions of a (paraphrase, state)
                # group sample with the same seed, so dp vs the neutral twin is paired.
                seed_parts=("l1", task.paraphrase, task.state),
                tags={
                    "condition": task.condition,
                    "paraphrase": task.paraphrase,
                    "state": task.state,
                    "sample": task.sample,
                },
            )
            d = trader.decide(obs, ctx)
            row = {
                "version": cfg["version"],
                "prompt_version": PROMPT_VERSION,
                "bank_sha256": bank.sha256,
                "model": model,
                "defenses": "+".join(defenses),
                "fmt": fmt,
                **task.__dict__,
                **info,
                "valid": d.valid,
                "p_high": d.p_high,
                "fair_value": d.fair_value,
                "side": d.side,
                "limit_price": d.order.limit if d.order else None,
                "quantity": d.order.qty if d.order else 0,
                "p_rescaled": d.p_rescaled,
                "rationale": d.rationale,
                "attempts": d.meta.get("attempts"),
                "latency_ms": d.meta.get("latency_ms"),
                "error": d.meta.get("error"),
                "filter": d.meta.get("filter"),
                # An invalid filter answer flags nothing, so D4 then passes the whole feed.
                "filter_valid": d.meta.get("filter_valid"),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if not quiet and (k % 25 == 0 or k == len(tasks)):
                print(
                    f"[level1 {model}] {k}/{len(tasks)}  {(time.time() - t0) / k:.1f} s/call  "
                    f"cache hits {client.stats['hits']}  invalid {client.stats['invalid']}",
                    flush=True,
                )
    return out
