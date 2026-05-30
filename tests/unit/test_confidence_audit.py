"""Unit tests for the Phase-5 confidence audit emitter (T-5-5 / REQ-CONF-1).

Synthetic, deterministic (seed 42) data only; no I/O beyond a tmp_path round-trip.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from audits.phases.confidence import run_phase, write_confidence_audit
from core.contracts.phase5 import CONFIDENCE_COVERAGE_POINTS, ECE_TOL


def _informative_data(n: int = 400, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Confidence scores that are genuinely predictive of bracket_correct.

    Draw a latent confidence in [0, 1]; label is a Bernoulli draw whose success
    probability equals that confidence -> higher confidence really does hit more.
    """
    rng = np.random.default_rng(seed)
    confidence = rng.uniform(0.0, 1.0, size=n)
    bracket_correct = (rng.uniform(0.0, 1.0, size=n) < confidence).astype(int)
    return confidence, bracket_correct


def test_run_phase_keys_and_passed_reflects_ece():
    confidence, bracket_correct = _informative_data()
    result = run_phase(confidence=confidence, bracket_correct=bracket_correct)

    assert result["phase"] == "confidence"
    assert set(result.keys()) == {"phase", "passed", "details"}
    details = result["details"]
    assert set(details.keys()) == {
        "ece",
        "ece_tol",
        "ece_within_tol",
        "ece_bins",
        "n",
        "bracket_match_by_coverage",
    }
    assert details["n"] == confidence.size
    assert details["ece_tol"] == ECE_TOL
    # passed must mirror the ece <= ECE_TOL gate exactly.
    assert result["passed"] == (details["ece"] <= ECE_TOL)
    assert result["passed"] == details["ece_within_tol"]


def test_ece_is_finite_unit_interval():
    confidence, bracket_correct = _informative_data()
    details = run_phase(confidence=confidence, bracket_correct=bracket_correct)["details"]
    ece = details["ece"]
    assert isinstance(ece, float)
    assert np.isfinite(ece)
    assert 0.0 <= ece <= 1.0


def test_bracket_match_monotone_informative():
    confidence, bracket_correct = _informative_data()
    details = run_phase(confidence=confidence, bracket_correct=bracket_correct)["details"]
    bm = details["bracket_match_by_coverage"]

    # Keys cover exactly the contract coverage points (string-keyed, sorted-stable).
    expected_keys = {format(c, ".2f") for c in CONFIDENCE_COVERAGE_POINTS}
    assert set(bm.keys()) == expected_keys

    top = bm["0.25"]["match_rate"]
    overall = bm["1.00"]["match_rate"]
    assert bm["1.00"]["n_kept"] == confidence.size
    assert bm["0.25"]["n_kept"] <= bm["0.50"]["n_kept"] <= bm["1.00"]["n_kept"]
    # Informative confidence: the most-confident quarter beats the overall rate.
    assert top >= overall


def test_write_round_trips_and_byte_stable(tmp_path):
    confidence, bracket_correct = _informative_data()
    result = run_phase(confidence=confidence, bracket_correct=bracket_correct)

    p1 = write_confidence_audit(tmp_path / "run_a", result)
    loaded = json.loads(p1.read_text(encoding="ascii"))
    assert loaded == result

    # Same input -> byte-identical output across two calls.
    b1 = p1.read_bytes()
    p2 = write_confidence_audit(tmp_path / "run_b", result)
    b2 = p2.read_bytes()
    assert b1 == b2


def test_write_creates_missing_dir(tmp_path):
    confidence, bracket_correct = _informative_data()
    result = run_phase(confidence=confidence, bracket_correct=bracket_correct)
    nested = tmp_path / "deep" / "audits" / "run_id"
    path = write_confidence_audit(nested, result)
    assert path.exists()
    assert path.name == "confidence_audit.json"


def test_mismatched_length_raises():
    with pytest.raises(ValueError):
        run_phase(confidence=[0.1, 0.2, 0.3], bracket_correct=[1, 0])


def test_empty_input_raises():
    with pytest.raises(ValueError):
        run_phase(confidence=[], bracket_correct=[])
