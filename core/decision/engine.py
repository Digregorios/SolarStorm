"""Decision-engine confidence stay-out gate (T-5-6, REQ-CONF-3).

Phase 5 adds ONLY the confidence stay-out: if the model's confidence score is
below the configured ``min_confidence`` bar, the engine returns
``NO_TRADE("low_confidence")``; otherwise it ``PASS``-es the gate. PASS means the
confidence gate is cleared -- the actual trade / no-trade decision on edge,
price, etc. is a LATER phase (pre-registered for Phase 8) and is NOT built here.

The ``min_confidence`` bar read by ``load_min_confidence`` is the config DEFAULT
(``MIN_CONFIDENCE_DEFAULT`` = 0.55) used until the LEARNED operational cutoff
(REQ-DEC-3) exists. This module does NOT learn it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from core.contracts.phase5 import MIN_CONFIDENCE_DEFAULT

# Action constants. PASS clears the confidence gate; NO_TRADE is the stay-out.
NO_TRADE = "NO_TRADE"
PASS = "PASS"

# Reason string for the confidence stay-out (REQ-CONF-3).
REASON_LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True)
class Decision:
    """Outcome of the confidence gate.

    ``action`` is :data:`NO_TRADE` or :data:`PASS`; ``reason`` is the stay-out
    reason string when staying out, else ``None``.
    """

    action: str
    reason: str | None
    confidence: float
    min_confidence: float


def confidence_gate(confidence_score: float, *, min_confidence: float) -> Decision:
    """Apply the confidence stay-out gate (REQ-CONF-3).

    Boundary semantics are ``>=``: a ``confidence_score`` exactly equal to
    ``min_confidence`` PASSES (only scores strictly below the bar stay out).

    ``confidence_score`` must lie in [0, 1]; otherwise ``ValueError`` is raised.
    """
    if not 0.0 <= confidence_score <= 1.0:
        raise ValueError(
            f"confidence_score must be in [0, 1], got {confidence_score!r}"
        )
    if confidence_score < min_confidence:
        return Decision(
            action=NO_TRADE,
            reason=REASON_LOW_CONFIDENCE,
            confidence=confidence_score,
            min_confidence=min_confidence,
        )
    return Decision(
        action=PASS,
        reason=None,
        confidence=confidence_score,
        min_confidence=min_confidence,
    )


def load_min_confidence(model_yaml_path: str | Path) -> float:
    """Read ``confidence.min_confidence_default`` from the model YAML.

    Returns :data:`MIN_CONFIDENCE_DEFAULT` if the key (or its parent section) is
    absent. This is the DEFAULT bar used until the LEARNED cutoff (REQ-DEC-3, a
    later phase) exists; this module does NOT learn it.
    """
    p = Path(model_yaml_path)
    with open(p, encoding="ascii") as fh:
        raw = yaml.safe_load(fh) or {}
    confidence = raw.get("confidence") or {}
    return float(confidence.get("min_confidence_default", MIN_CONFIDENCE_DEFAULT))


def confidence_gate_enabled_in_production(model_yaml_path: str | Path) -> bool:
    """Whether the confidence stay-out may gate trades in production.

    Phase 5 closed NOT READY (2026-05-30): calibration never passed REQ-AUD-5, so the
    stay-out is DIAGNOSTIC only until Phase 5 is green. Defaults to ``False`` when the
    key is absent (fail-safe: an un-validated gate never blocks trades silently).
    """
    p = Path(model_yaml_path)
    with open(p, encoding="ascii") as fh:
        raw = yaml.safe_load(fh) or {}
    confidence = raw.get("confidence") or {}
    return bool(confidence.get("gate_enabled_in_production", False))


def production_confidence_gate(
    confidence_score: float, *, min_confidence: float, gate_enabled: bool
) -> Decision:
    """Production wrapper: apply the stay-out ONLY when ``gate_enabled`` is True.

    When disabled (Phase 5 not green), always returns ``PASS`` so an un-validated
    calibration cannot block trades; the score is still carried for diagnostics.
    """
    if not gate_enabled:
        return Decision(
            action=PASS, reason=None,
            confidence=confidence_score, min_confidence=min_confidence,
        )
    return confidence_gate(confidence_score, min_confidence=min_confidence)


__all__ = [
    "NO_TRADE",
    "PASS",
    "REASON_LOW_CONFIDENCE",
    "Decision",
    "confidence_gate",
    "production_confidence_gate",
    "load_min_confidence",
    "confidence_gate_enabled_in_production",
    "Thresholds",
    "ForecastRow",
    "EngineDecision",
    "decide",
    "BLOCK_BUY_NO_LATE_SPIKE",
    "NO_TRADE_RESOLVED",
    "OPPORTUNITY_ASSYMETRIC",
    "BUY_NO",
    "REASON_NO_EDGE",
]


# --- Full decision engine (T-8-3, design 10; REQ-DEC-1/2) --------------------
# The confidence stay-out above is the Phase-5 fragment; this is the full decision
# tree over a forecast + a market snapshot. States are pre-registered (REQ-DEC-2);
# operational thresholds are LEARNED later (REQ-DEC-3 nested walk-forward), never
# tuned here. p_yes comes from the bracket distribution via core.decision.market_map.

from core.decision.market_map import ContractRange, p_yes  # noqa: E402

# Decision states (REQ-DEC-2). NO_TRADE (above) is reused for the stay-out states.
BLOCK_BUY_NO_LATE_SPIKE = "BLOCK_BUY_NO_LATE_SPIKE"
NO_TRADE_RESOLVED = "NO_TRADE_RESOLVED"
OPPORTUNITY_ASSYMETRIC = "OPPORTUNITY_ASSYMETRIC"
BUY_NO = "BUY_NO"
REASON_NO_EDGE = "no_edge"


@dataclass(frozen=True)
class Thresholds:
    """Operational thresholds (LEARNED via REQ-DEC-3; defaults are placeholders)."""

    min_confidence: float = MIN_CONFIDENCE_DEFAULT
    spike_block: float = 0.30
    no_too_expensive: float = 0.95
    min_edge_yes: float = 0.05
    min_edge_no: float = 0.05


@dataclass(frozen=True)
class ForecastRow:
    """Forecast inputs the engine consumes (design 4.6 subset)."""

    prob_dist: dict[int, float]
    confidence_score: float
    spike_risk: float = 0.0  # Phase 7; 0.0 when the spike model is absent


@dataclass(frozen=True)
class EngineDecision:
    """Outcome of the full decision tree."""

    state: str
    side: str | None = None
    reason: str | None = None
    edge_yes: float | None = None
    edge_no: float | None = None
    p_yes: float | None = None


def decide(
    forecast: ForecastRow,
    contract: ContractRange,
    price_yes: float,
    price_no: float,
    thresholds: Thresholds,
) -> EngineDecision:
    """Classify one (forecast, market) into exactly one state (design 10, REQ-DEC-1/2).

    Order is pre-registered and fixed: confidence stay-out, late-spike block, resolved
    (NO too expensive), YES asymmetric edge, BUY NO edge (only when spike is low), else
    no-edge stay-out. Thresholds are inputs (learned upstream), never tuned here.
    """
    py = p_yes(forecast.prob_dist, contract)
    edge_yes = py - price_yes
    edge_no = (1.0 - py) - price_no

    if forecast.confidence_score < thresholds.min_confidence:
        return EngineDecision(state=NO_TRADE, reason=REASON_LOW_CONFIDENCE, p_yes=py,
                              edge_yes=edge_yes, edge_no=edge_no)
    if forecast.spike_risk >= thresholds.spike_block:
        return EngineDecision(state=BLOCK_BUY_NO_LATE_SPIKE, p_yes=py,
                              edge_yes=edge_yes, edge_no=edge_no)
    if price_no >= thresholds.no_too_expensive:
        return EngineDecision(state=NO_TRADE_RESOLVED, p_yes=py,
                              edge_yes=edge_yes, edge_no=edge_no)
    if edge_yes >= thresholds.min_edge_yes:
        return EngineDecision(state=OPPORTUNITY_ASSYMETRIC, side="BUY_YES", p_yes=py,
                              edge_yes=edge_yes, edge_no=edge_no)
    if edge_no >= thresholds.min_edge_no and forecast.spike_risk < thresholds.spike_block:
        return EngineDecision(state=BUY_NO, side="BUY_NO", p_yes=py,
                              edge_yes=edge_yes, edge_no=edge_no)
    return EngineDecision(state=NO_TRADE, reason=REASON_NO_EDGE, p_yes=py,
                          edge_yes=edge_yes, edge_no=edge_no)
