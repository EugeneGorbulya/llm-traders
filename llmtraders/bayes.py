"""Rational benchmark: p(value = 130 | official signals) and the rational price."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

LOW = 70.0
HIGH = 130.0
PRIOR_HIGH = 0.5
ACCURACY = 0.7


def posterior_high(
    signals: Iterable[str],
    prior: float = PRIOR_HIGH,
    accuracy: float = ACCURACY,
) -> float:
    p = prior
    for s in signals:
        s = s.lower()
        if s == "good":
            lh_high, lh_low = accuracy, 1 - accuracy
        elif s == "bad":
            lh_high, lh_low = 1 - accuracy, accuracy
        else:
            raise ValueError(f"unknown signal {s!r}")
        num = p * lh_high
        p = num / (num + (1 - p) * lh_low)
    return p


def value_from_p(p_high: float, low: float = LOW, high: float = HIGH) -> float:
    return low + (high - low) * p_high


def rational_price(
    signals: Sequence[str],
    low: float = LOW,
    high: float = HIGH,
    prior: float = PRIOR_HIGH,
    accuracy: float = ACCURACY,
) -> float:
    return value_from_p(posterior_high(signals, prior, accuracy), low, high)
