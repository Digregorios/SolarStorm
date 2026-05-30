"""Pre-registration with teeth (C3, design 29.4 step 5).

The committed ``contracts/phase4_preregistration.md`` MUST hash to the value pinned
in ``core/eval/preregistration.COMMITTED_SHA256``; ``phase4_evaluate`` refuses to run
otherwise. These tests assert: (a) the shipped contract matches the pin, (b) any
edit to the frozen block is detected, (c) the hash ignores CRLF/LF churn but not
substance, (d) the assertion raises on mismatch.
"""

from __future__ import annotations

import pytest

from core.eval.preregistration import (
    COMMITTED_SHA256,
    PHASE5_COMMITTED_SHA256,
    PHASE5_PREREG_PATH,
    PHASE5A_COMMITTED_SHA256,
    PHASE5A_PREREG_PATH,
    PHASE5A3_COMMITTED_SHA256,
    PHASE5A3_PREREG_PATH,
    PHASE5P_COMMITTED_SHA256,
    PHASE5P_PREREG_PATH,
    PHASE5PP_COMMITTED_SHA256,
    PHASE5PP_PREREG_PATH,
    PREREG_PATH,
    PreregistrationError,
    assert_phase5_preregistration_committed,
    assert_phase5a_preregistration_committed,
    assert_phase5a3_preregistration_committed,
    assert_phase5p_preregistration_committed,
    assert_phase5pp_preregistration_committed,
    assert_preregistration_committed,
    extract_canonical_block,
    phase5_preregistration_sha256,
    phase5a_preregistration_sha256,
    phase5a3_preregistration_sha256,
    phase5p_preregistration_sha256,
    phase5pp_preregistration_sha256,
    preregistration_sha256,
)


def test_shipped_preregistration_matches_committed_hash():
    """The real contract on disk must match the pinned hash (the evaluator's gate)."""
    assert preregistration_sha256() == COMMITTED_SHA256
    assert assert_preregistration_committed() == COMMITTED_SHA256


def test_committed_hash_is_not_placeholder():
    assert COMMITTED_SHA256 != "0" * 64
    assert len(COMMITTED_SHA256) == 64


def _doc(block_body: str) -> str:
    return f"intro prose\n<<<PREREG\n{block_body}\nPREREG>>>\ntrailing prose\n"


def test_extract_is_robust_to_line_endings():
    unix = _doc("criterion_version: 1.1\nseeds:\n  numpy: 42")
    crlf = unix.replace("\n", "\r\n")
    assert extract_canonical_block(unix) == extract_canonical_block(crlf)


def test_extract_ignores_prose_outside_markers():
    a = _doc("criterion_version: 1.1")
    b = a.replace("intro prose", "COMPLETELY DIFFERENT HEADER").replace(
        "trailing prose", "other footer"
    )
    assert extract_canonical_block(a) == extract_canonical_block(b)


def test_extract_detects_substance_change():
    a = _doc("gate.i_t_obs_max: 0.10")
    b = _doc("gate.i_t_obs_max: 0.20")  # loosened threshold -> different hash
    assert extract_canonical_block(a) != extract_canonical_block(b)


def test_missing_markers_raise():
    with pytest.raises(PreregistrationError, match="markers"):
        extract_canonical_block("no markers here")


def test_assert_raises_on_tampered_file(tmp_path):
    """A contract whose frozen block was edited must fail the committed-hash gate."""
    original = PREREG_PATH.read_text(encoding="ascii")
    tampered = original.replace("gate.i_t_obs_max: 0.10", "gate.i_t_obs_max: 0.50")
    assert tampered != original  # sanity: the threshold line exists
    p = tmp_path / "phase4_preregistration.md"
    p.write_text(tampered, encoding="ascii")
    with pytest.raises(PreregistrationError, match="hash mismatch"):
        assert_preregistration_committed(p)


# --- Phase 5 amendment pre-registration (criterion_version 1.0) ---------------


def test_shipped_phase5_preregistration_matches_committed_hash():
    """The Phase 5 amendment contract on disk must match its pinned hash."""
    assert phase5_preregistration_sha256() == PHASE5_COMMITTED_SHA256
    assert assert_phase5_preregistration_committed() == PHASE5_COMMITTED_SHA256


def test_phase5_committed_hash_is_not_placeholder():
    assert PHASE5_COMMITTED_SHA256 != "0" * 64
    assert len(PHASE5_COMMITTED_SHA256) == 64


def test_phase5_hash_differs_from_phase4():
    """The amendment must carry its own hash, not silently reuse the Phase 4 pin."""
    assert PHASE5_COMMITTED_SHA256 != COMMITTED_SHA256


def test_phase5_assert_raises_on_tampered_file(tmp_path):
    """Loosening a Phase 5 gate threshold must fail the committed-hash gate."""
    original = PHASE5_PREREG_PATH.read_text(encoding="ascii")
    tampered = original.replace(
        "gate.coverage_tol: 0.04", "gate.coverage_tol: 0.10"
    )
    assert tampered != original  # sanity: the threshold line exists in the block
    p = tmp_path / "phase5_preregistration.md"
    p.write_text(tampered, encoding="ascii")
    with pytest.raises(PreregistrationError, match="hash mismatch"):
        assert_phase5_preregistration_committed(p)


# --- Phase 5 Track A.A1 amendment (sigma winsorization) -----------------------


def test_shipped_phase5a_preregistration_matches_committed_hash():
    """The Track A.A1 amendment contract on disk must match its pinned hash."""
    assert phase5a_preregistration_sha256() == PHASE5A_COMMITTED_SHA256
    assert assert_phase5a_preregistration_committed() == PHASE5A_COMMITTED_SHA256


def test_phase5a_committed_hash_is_not_placeholder():
    assert PHASE5A_COMMITTED_SHA256 != "0" * 64
    assert len(PHASE5A_COMMITTED_SHA256) == 64


def test_phase5a_hash_distinct_from_other_phases():
    assert PHASE5A_COMMITTED_SHA256 != COMMITTED_SHA256
    assert PHASE5A_COMMITTED_SHA256 != PHASE5_COMMITTED_SHA256


def test_phase5a_assert_raises_on_tampered_winsor_percentile(tmp_path):
    """Re-tuning the winsorization percentile must fail the committed-hash gate."""
    original = PHASE5A_PREREG_PATH.read_text(encoding="ascii")
    tampered = original.replace(
        "sigma.winsorize_clip_hi_pctl: 95", "sigma.winsorize_clip_hi_pctl: 99"
    )
    assert tampered != original  # sanity: the percentile line exists in the block
    p = tmp_path / "phase5_amendment.md"
    p.write_text(tampered, encoding="ascii")
    with pytest.raises(PreregistrationError, match="hash mismatch"):
        assert_phase5a_preregistration_committed(p)


# --- Phase 5 Track A.A3 amendment (Mondrian conditional conformal) -------------


def test_shipped_phase5a3_preregistration_matches_committed_hash():
    """The Track A.A3 amendment contract on disk must match its pinned hash."""
    assert phase5a3_preregistration_sha256() == PHASE5A3_COMMITTED_SHA256
    assert assert_phase5a3_preregistration_committed() == PHASE5A3_COMMITTED_SHA256


def test_phase5a3_committed_hash_is_not_placeholder():
    assert PHASE5A3_COMMITTED_SHA256 != "0" * 64
    assert len(PHASE5A3_COMMITTED_SHA256) == 64


def test_phase5a3_hash_distinct_from_other_phases():
    assert PHASE5A3_COMMITTED_SHA256 != COMMITTED_SHA256
    assert PHASE5A3_COMMITTED_SHA256 != PHASE5_COMMITTED_SHA256
    assert PHASE5A3_COMMITTED_SHA256 != PHASE5A_COMMITTED_SHA256


def test_phase5a3_assert_raises_on_tampered_shrinkage_n0(tmp_path):
    """Re-tuning the shrinkage strength n0 must fail the committed-hash gate."""
    original = PHASE5A3_PREREG_PATH.read_text(encoding="ascii")
    tampered = original.replace("mondrian.shrinkage_n0: 200", "mondrian.shrinkage_n0: 50")
    assert tampered != original  # sanity: the n0 line exists in the block
    p = tmp_path / "phase5_amendment_trackA_a3.md"
    p.write_text(tampered, encoding="ascii")
    with pytest.raises(PreregistrationError, match="hash mismatch"):
        assert_phase5a3_preregistration_committed(p)


# --- Phase 5 Track P amendment (predictive-distribution uncertainty sigma) ------


def test_shipped_phase5p_preregistration_matches_committed_hash():
    """The Track P amendment contract on disk must match its pinned hash."""
    assert phase5p_preregistration_sha256() == PHASE5P_COMMITTED_SHA256
    assert assert_phase5p_preregistration_committed() == PHASE5P_COMMITTED_SHA256


def test_phase5p_committed_hash_is_not_placeholder():
    assert PHASE5P_COMMITTED_SHA256 != "0" * 64
    assert len(PHASE5P_COMMITTED_SHA256) == 64


def test_phase5p_hash_distinct_from_other_phases():
    assert PHASE5P_COMMITTED_SHA256 != COMMITTED_SHA256
    assert PHASE5P_COMMITTED_SHA256 != PHASE5_COMMITTED_SHA256
    assert PHASE5P_COMMITTED_SHA256 != PHASE5A_COMMITTED_SHA256
    assert PHASE5P_COMMITTED_SHA256 != PHASE5A3_COMMITTED_SHA256


def test_phase5p_assert_raises_on_tampered_monotonicity_threshold(tmp_path):
    """Loosening the binding sanity threshold must fail the committed-hash gate."""
    original = PHASE5P_PREREG_PATH.read_text(encoding="ascii")
    tampered = original.replace(
        "sanity.monotonicity_min_rho: 0.10", "sanity.monotonicity_min_rho: 0.00"
    )
    assert tampered != original  # sanity: the threshold line exists in the block
    p = tmp_path / "phase5_amendment_trackP_predictive_uncertainty.md"
    p.write_text(tampered, encoding="ascii")
    with pytest.raises(PreregistrationError, match="hash mismatch"):
        assert_phase5p_preregistration_committed(p)


# --- Phase 5 Track P' amendment (quantization margin / distance-to-threshold) ---


def test_shipped_phase5pp_preregistration_matches_committed_hash():
    """The Track P' amendment contract on disk must match its pinned hash."""
    assert phase5pp_preregistration_sha256() == PHASE5PP_COMMITTED_SHA256
    assert assert_phase5pp_preregistration_committed() == PHASE5PP_COMMITTED_SHA256


def test_phase5pp_committed_hash_is_not_placeholder():
    assert PHASE5PP_COMMITTED_SHA256 != "0" * 64
    assert len(PHASE5PP_COMMITTED_SHA256) == 64


def test_phase5pp_hash_distinct_from_other_phases():
    assert PHASE5PP_COMMITTED_SHA256 != COMMITTED_SHA256
    assert PHASE5PP_COMMITTED_SHA256 != PHASE5_COMMITTED_SHA256
    assert PHASE5PP_COMMITTED_SHA256 != PHASE5A_COMMITTED_SHA256
    assert PHASE5PP_COMMITTED_SHA256 != PHASE5A3_COMMITTED_SHA256
    assert PHASE5PP_COMMITTED_SHA256 != PHASE5P_COMMITTED_SHA256


def test_phase5pp_assert_raises_on_tampered_focus_threshold(tmp_path):
    """Loosening the binding FOCUS sanity threshold must fail the committed-hash gate."""
    original = PHASE5PP_PREREG_PATH.read_text(encoding="ascii")
    tampered = original.replace(
        "sanity.focus_monotonicity_min_rho: 0.10",
        "sanity.focus_monotonicity_min_rho: 0.00",
    )
    assert tampered != original  # sanity: the focus threshold line exists in the block
    p = tmp_path / "phase5_amendment_trackPprime_quantization_margin.md"
    p.write_text(tampered, encoding="ascii")
    with pytest.raises(PreregistrationError, match="hash mismatch"):
        assert_phase5pp_preregistration_committed(p)


def test_phase5pp_assert_raises_on_flipped_auxiliary_binding(tmp_path):
    """Promoting the auxiliary Kendall tau-b to binding must fail the committed-hash gate."""
    original = PHASE5PP_PREREG_PATH.read_text(encoding="ascii")
    tampered = original.replace(
        "sanity.focus_auxiliary_metric_binding: false",
        "sanity.focus_auxiliary_metric_binding: true",
    )
    assert tampered != original
    p = tmp_path / "phase5_amendment_trackPprime_quantization_margin.md"
    p.write_text(tampered, encoding="ascii")
    with pytest.raises(PreregistrationError, match="hash mismatch"):
        assert_phase5pp_preregistration_committed(p)
