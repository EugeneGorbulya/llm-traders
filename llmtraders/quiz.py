"""Bayes quiz: competence gate before a model enters the robustness results."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from .agents import LLMTrader
from .bayes import posterior_high
from .core import N_PERIODS, DecisionContext, Observation, PricePoint
from .llm.config import get_model
from .prompts import PromptConfig
from .results import RESULTS, make_client

HISTORIES = [
    ("none", {}, 3, 0),
    ("good", {4: "good"}, 5, +1),
    ("bad", {4: "bad"}, 5, -1),
    ("good_good", {4: "good", 8: "good"}, 9, +1),
    ("bad_bad", {4: "bad", 8: "bad"}, 9, -1),
    ("good_bad", {4: "good", 8: "bad"}, 9, 0),
]


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r["valid"]]
    directional = [r for r in rows if r["direction"]]
    correct = [
        r
        for r in directional
        if r["valid"] and (r["p_high"] - 0.5) * r["direction"] > 0
    ]
    valid_share = len(valid) / len(rows) if rows else 0.0
    direction_share = len(correct) / len(directional) if directional else 0.0
    return {
        "valid_share": valid_share,
        "direction_share": direction_share,
        "mean_abs_err": statistics.fmean(abs(r["p_high"] - r["bayes_p"]) for r in valid)
        if valid
        else None,
        "passed": valid_share >= 0.95 and direction_share >= 0.80,
    }


def run(
    model: str,
    *,
    samples: int = 5,
    out_dir: Path | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    mcfg = get_model(model)
    out = Path(out_dir) if out_dir else RESULTS / "quiz" / model
    client = make_client(out, cache_path)
    rows = []
    for name, signals, period, direction in HISTORIES:
        obs = Observation(
            period=period,
            n_periods=N_PERIODS,
            cash=1000.0,
            shares=10,
            price_history=[PricePoint(t, None, 0) for t in range(1, period)],
            official=sorted(signals.items()),
            chat=[],
            ref_price=100.0,
            sees_chat=False,
        )
        for s in range(samples):
            trader = LLMTrader(
                agent_id="trader",
                cash=obs.cash,
                shares=obs.shares,
                model=mcfg,
                client=client,
                prompt_cfg=PromptConfig(),
                sample_idx=s,
            )
            ctx = DecisionContext(
                seed_parts=("quiz", name), tags={"quiz": name, "sample": s}
            )
            d = trader.decide(obs, ctx)
            rows.append(
                {
                    "model": model,
                    "history": name,
                    "sample": s,
                    "direction": direction,
                    "bayes_p": posterior_high(list(signals.values())),
                    "valid": d.valid,
                    "p_high": d.p_high,
                    "fair_value": d.fair_value,
                    "side": d.side,
                    "rationale": d.rationale,
                    "latency_ms": d.meta.get("latency_ms"),
                    "error": d.meta.get("error"),
                }
            )
    (out / "results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    res = {"model": model, **score(rows)}
    (out / "score.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res
