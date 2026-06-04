"""P1+P4: Settlement contract — integer rounding, bracket mapping, flip risk.

All internal computation uses decimal (P1). The integer bracket for Polymarket
settlement is derived ONLY at the output layer. The `flip_risk` quantifies how
close a decimal value is to a .5°C boundary where 0.1°C flips the bracket (P4).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def integer_settlement(dec: float) -> int:
    """Commercial rounding (half-up): 14.5 → 15, -2.5 → -2."""
    return int(math.floor(dec + 0.5))


def bracket_for(dec: float) -> int:
    """The Polymarket bracket for a decimal temperature (P4)."""
    return integer_settlement(dec)


@dataclass
class FlipRisk:
    risk: float       # 0 (safe, on a .5 boundary) to 0.5 (max risk, at an integer)
    nearest_boundary: float
    direction: str    # "up", "down", "either", "stable"


def flip_risk(dec: float) -> FlipRisk:
    """How close `dec` is to flipping to a different integer bracket.

    0.0 = exactly on a .5 boundary (no risk — always rounds the same way).
    0.5 = exactly at an integer (max risk — 0.1°C changes the bracket).
    """
    settle = integer_settlement(dec)
    risk = round(0.5 - abs(dec - settle), 6)
    risk = max(0.0, risk)

    frac = dec - math.floor(dec)
    nearest_boundary = math.floor(dec) + 0.5

    if abs(frac - 0.5) < 1e-9:
        direction = "stable"
    elif abs(frac) < 1e-9:
        direction = "either"
    elif dec < settle:
        direction = "down"
    else:
        direction = "up"

    return FlipRisk(risk=risk, nearest_boundary=nearest_boundary, direction=direction)
