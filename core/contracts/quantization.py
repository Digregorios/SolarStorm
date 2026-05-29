"""Quantization Q(x) and inverse band B(k) (REQ-CON-1, contracts/quantization.md).

Q_VERSION = 1.0
"""

from __future__ import annotations

import math

Q_VERSION = "1.0"


def Q(x: float) -> int:
    """Round-half-up quantization: ``Q(x) = floor(x + 0.5)``.

    Property: ``Q(B(k)) == {k}`` for any integer k. ``18.5`` belongs to ``B(19)``.
    """
    if math.isnan(x):
        raise ValueError("Q called on NaN.")
    return int(math.floor(x + 0.5))


def B(k: int) -> tuple[float, float]:
    """Return the half-open inverse band ``[k - 0.5, k + 0.5)``."""
    return (k - 0.5, k + 0.5)


def in_band(x: float, k: int) -> bool:
    """Whether ``x`` falls inside ``B(k)``."""
    low, high = B(k)
    return low <= x < high


def distance_to_band(x: float, k: int) -> float:
    """Distance from ``x`` to ``B(k)``; 0 if inside."""
    low, high = B(k)
    if low <= x < high:
        return 0.0
    return max(low - x, x - high)


__all__ = ["Q_VERSION", "Q", "B", "in_band", "distance_to_band"]
