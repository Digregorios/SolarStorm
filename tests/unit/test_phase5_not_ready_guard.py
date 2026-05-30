"""Phase 5 NOT-READY production guard: confidence stay-out must not gate trades (2026-05-30).

While Phase 5 is red, production_confidence_gate must PASS regardless of score, and the
config flag must default to False (fail-safe). The diagnostic confidence_gate is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from core.decision.engine import (
    NO_TRADE,
    PASS,
    confidence_gate,
    confidence_gate_enabled_in_production,
    production_confidence_gate,
)

REPO = Path(__file__).resolve().parents[2]


def test_production_gate_noops_when_disabled():
    # A very low score would stay out under the diagnostic gate ...
    assert confidence_gate(0.01, min_confidence=0.55).action == NO_TRADE
    # ... but the production gate PASSES when disabled (Phase 5 not green).
    d = production_confidence_gate(0.01, min_confidence=0.55, gate_enabled=False)
    assert d.action == PASS and d.reason is None


def test_production_gate_enforces_when_enabled():
    d = production_confidence_gate(0.01, min_confidence=0.55, gate_enabled=True)
    assert d.action == NO_TRADE
    assert production_confidence_gate(0.90, min_confidence=0.55, gate_enabled=True).action == PASS


def test_config_flag_is_failsafe_false_while_phase5_not_ready():
    cfg = REPO / "nzwn" / "config" / "model.yaml"
    assert confidence_gate_enabled_in_production(cfg) is False
