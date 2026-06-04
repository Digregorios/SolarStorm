import numpy as np
from solarstorm.eval._gates import GateResult, apply_all_gates


def test_g1_null_not_beaten_kills():
    result = apply_all_gates(
        model_mae=2.5, best_null_mae=2.0, cp="23:00",
        fallback_rate=0.0, p50_mode_share=0.1, corr_diff=0.30,
    )
    assert result["G1"].status == "KILL"
    assert not result["G1"].passed


def test_g1_passes_when_model_beats_null():
    result = apply_all_gates(
        model_mae=1.5, best_null_mae=2.0, cp="23:00",
        fallback_rate=0.0, p50_mode_share=0.1, corr_diff=0.30,
    )
    assert result["G1"].passed


def test_g2_fallback_dominance_fails():
    result = apply_all_gates(
        model_mae=1.5, best_null_mae=2.0, cp="23:00",
        fallback_rate=0.73, p50_mode_share=0.1, corr_diff=0.30,
    )
    assert result["G2"].status == "NOT_OPERATIONAL"
    assert not result["G2"].passed


def test_g3_p50_collapse_alerts():
    result = apply_all_gates(
        model_mae=1.5, best_null_mae=2.0, cp="23:00",
        fallback_rate=0.0, p50_mode_share=0.93, corr_diff=0.30,
    )
    assert result["G3"].status == "COLLAPSE_ALERT"


def test_g4_anti_nowcaster_fails():
    result = apply_all_gates(
        model_mae=1.5, best_null_mae=2.0, cp="23:00",
        fallback_rate=0.0, p50_mode_share=0.1, corr_diff=-0.01,
    )
    assert result["G4"].status == "NOWCAST_SUSPECT"
    assert not result["G4"].passed


def test_g4_corr_diff_requires_ci95_excludes_zero():
    """corr_diff must be > 0.05 AND CI95 must exclude zero."""
    result = apply_all_gates(
        model_mae=1.5, best_null_mae=2.0, cp="23:00",
        fallback_rate=0.0, p50_mode_share=0.1,
        corr_diff=0.08, corr_diff_ci95=(-0.01, 0.17),
    )
    # CI95 includes zero → fails
    assert not result["G4"].passed


def test_all_gates_pass_for_clean_model():
    result = apply_all_gates(
        model_mae=1.5, best_null_mae=2.0, cp="23:00",
        fallback_rate=0.1, p50_mode_share=0.2,
        corr_diff=0.25, corr_diff_ci95=(0.10, 0.40),
    )
    assert all(g.passed for g in result.values())


def test_g4_present_and_fails_when_corr_diff_missing():
    """G4 is non-demotable: a missing corr_diff must surface as a FAILING G4,
    never as a silently-absent gate (the old project's exact failure mode)."""
    result = apply_all_gates(
        model_mae=1.5, best_null_mae=2.0, cp="23:00",
        fallback_rate=0.1, p50_mode_share=0.2,
        corr_diff=None,
    )
    assert "G4" in result
    assert not result["G4"].passed
    assert result["G4"].status == "NOWCAST_SUSPECT"

