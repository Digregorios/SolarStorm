"""Causal firewall (P1) + contractual constants (P2 exception).

The causal invariant: every feature used at a checkpoint must be computed
from observations with ts_utc < cp_utc (strictly before the checkpoint).
Any violation is a RuntimeError — no silent fallback.
"""
from __future__ import annotations

import datetime as dt


def require_causal(
    *,
    feature_max_ts: dt.datetime,
    cp_utc: dt.datetime,
    label: str = "",
) -> None:
    """Raise RuntimeError if any feature timestamp reaches or exceeds cp_utc.

    Args:
        feature_max_ts: The latest observation timestamp used by any feature.
        cp_utc: The checkpoint UTC timestamp.
        label: Optional human-readable context for the error message.
    """
    if feature_max_ts >= cp_utc:
        ctx = f" [{label}]" if label else ""
        raise RuntimeError(
            f"Causality violation (causality firewall){ctx}: "
            f"feature_max_ts={feature_max_ts.isoformat()} "
            f">= cp_utc={cp_utc.isoformat()}"
        )


def ensure_closed_left(window_start: dt.datetime, window_end: dt.datetime) -> None:
    """Validate that a temporal window uses closed='left' semantics (start inclusive, end exclusive)."""
    if window_start >= window_end:
        raise ValueError(
            f"Invalid window: start={window_start.isoformat()} >= end={window_end.isoformat()}"
        )
