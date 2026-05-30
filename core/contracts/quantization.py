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


# --- Track D.D1: randomized rounding Q_rand (q_version 1.1) -------------------
# Pre-registered in contracts/phase5_amendment_trackD_d1_randomized_Q.md. Standard
# (unbiased) randomized rounding: ceil with probability t = frac(x), else floor, so
# E[Q_rand(x)] = x and the hard tie at 0.5 is smoothed. The draw u is a deterministic
# function of (global_seed, row_id, endpoint_side[, split_name]) ONLY -- no dataframe
# index, no test statistic -- so the same row reproduces on every machine/run.

import hashlib

Q_RAND_VERSION = "1.1"


def row_id(station_id: str, day_local, cp_utc) -> str:
    """Deterministic per-row key: sha256(station_id|day_local|cp_utc) (hex).

    Uses only no-future, per-row-stable fields (NZWN literal, the panel date_local and
    cp_utc). NEVER the dataframe/panel row index. ``day_local``/``cp_utc`` are stringified
    via ``str`` (ISO for date/datetime), matching the contract's stable-key requirement.
    """
    key = f"{station_id}|{day_local}|{cp_utc}"
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def _uniform01(global_seed: int, row_id_hex: str, endpoint_side: str, split_name: str | None = None) -> float:
    """Deterministic u ~ Uniform(0,1) keyed by (global_seed, row_id, endpoint_side[, split])."""
    parts = [str(int(global_seed)), row_id_hex, endpoint_side]
    if split_name is not None:
        parts.append(split_name)
    h = hashlib.sha256("|".join(parts).encode("ascii")).digest()
    # Top 53 bits -> a uniform in [0,1) with full double precision.
    val = int.from_bytes(h[:8], "big") >> 11
    return val / float(1 << 53)


def Q_rand(
    x: float,
    *,
    global_seed: int,
    row_id_hex: str,
    endpoint_side: str,
    split_name: str | None = None,
) -> int:
    """Unbiased randomized rounding (Track D.D1). ``ceil if u < frac(x) else floor``.

    ``E[Q_rand(x)] = x``; reduces to the exact integer when ``frac(x) == 0`` (no draw),
    and to ``floor``/``ceil`` deterministically as ``frac(x) -> 0`` / ``-> 1``.
    """
    if math.isnan(x):
        raise ValueError("Q_rand called on NaN.")
    if endpoint_side not in ("lo", "hi"):
        raise ValueError(f"endpoint_side must be 'lo' or 'hi'; got {endpoint_side!r}")
    f = math.floor(x)
    t = x - f
    if t == 0.0:
        return int(f)
    u = _uniform01(global_seed, row_id_hex, endpoint_side, split_name)
    return int(f + 1) if u < t else int(f)


__all__ = [
    "Q_VERSION",
    "Q",
    "B",
    "in_band",
    "distance_to_band",
    "Q_RAND_VERSION",
    "row_id",
    "Q_rand",
]
