"""Integration test for the decision-engine confidence stay-out (T-5-6, REQ-CONF-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.contracts.phase5 import MIN_CONFIDENCE_DEFAULT
from core.decision.engine import (
    NO_TRADE,
    PASS,
    Decision,
    confidence_gate,
    load_min_confidence,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_YAML = REPO_ROOT / "nzwn" / "config" / "model.yaml"


def test_below_threshold_stays_out() -> None:
    d = confidence_gate(0.40, min_confidence=0.55)
    assert isinstance(d, Decision)
    assert d.action == NO_TRADE
    assert d.reason == "low_confidence"
    assert d.confidence == 0.40
    assert d.min_confidence == 0.55


def test_at_threshold_passes() -> None:
    d = confidence_gate(0.55, min_confidence=0.55)
    assert d.action == PASS
    assert d.reason is None


def test_above_threshold_passes() -> None:
    d = confidence_gate(0.90, min_confidence=0.55)
    assert d.action == PASS
    assert d.reason is None


def test_load_min_confidence_from_real_model_yaml() -> None:
    assert load_min_confidence(MODEL_YAML) == 0.55


def test_load_min_confidence_missing_key_falls_back(tmp_path: Path) -> None:
    p = tmp_path / "model.yaml"
    p.write_text("seeds:\n  numpy: 42\n", encoding="ascii")
    assert load_min_confidence(p) == MIN_CONFIDENCE_DEFAULT


@pytest.mark.parametrize("bad", [1.5, -0.1])
def test_out_of_range_confidence_raises(bad: float) -> None:
    with pytest.raises(ValueError):
        confidence_gate(bad, min_confidence=0.55)
