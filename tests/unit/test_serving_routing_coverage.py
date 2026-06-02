"""Unit tests for the coverage guard + calm guard in the serving-matrix router.

Targets ``scripts/evaluate_serving_candidate_matrix.compute_routing_recommendation``
(reviewer 2nd-pass A4): the real dataset has every candidate covering every fold, so the
exclusion / calm-unverifiable branches never execute in the integration run. These tests
drive them directly with synthetic per-fold metrics so a regression in the subset/coverage
logic (e.g. inverting the issubset check) is caught.

The router is imported the same way as tests/unit/test_postmortem_monthly.py: insert the repo
root on sys.path and import the top-level scripts module (no data is loaded at import time).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.evaluate_serving_candidate_matrix import compute_routing_recommendation

CP23 = "23:00"


def _cand(all_mae, all_rps, calm_mae=None):
    """One candidate's per-stratum metrics for a single fold/CP."""
    d = {"ALL": {"mae": all_mae, "rps": all_rps}}
    if calm_mae is not None:
        d["calm"] = {"mae": calm_mae}
    return d


def _split(name, cp23_candidates):
    """A walk-forward split dict shaped like the evaluator output (only CP23 populated)."""
    return {"split": name, "by_cp": {CP23: cp23_candidates}}


def test_partial_coverage_candidate_is_excluded_even_with_lowest_mae():
    """gfs_residual has the lowest MAE but covers only 2 of Ridge's 3 folds -> excluded."""
    strong = _cand(0.50, 0.50, calm_mae=0.50)   # would dominate if it were eligible
    ridge = _cand(1.00, 1.00, calm_mae=1.00)
    analog = _cand(1.20, 1.20, calm_mae=1.20)
    full_results = [
        _split("f0", {"ridge": ridge, "gfs_residual": strong, "analog_arm": analog}),
        _split("f1", {"ridge": ridge, "gfs_residual": strong, "analog_arm": analog}),
        _split("f2", {"ridge": ridge, "analog_arm": analog}),  # gfs_residual ABSENT here
    ]
    routing, detail = compute_routing_recommendation([], full_results)

    d = detail[CP23]
    assert d["coverage_ok"]["gfs_residual"] is False
    assert "gfs_residual" in d["coverage_excluded"]
    assert d["incumbent_folds"] == [0, 1, 2]
    # Excluded from ranking despite the lowest partial MAE -> cannot win the CP.
    assert routing[CP23] == "ridge"
    assert d["winner"] == "ridge"
    assert "gfs_residual" not in d["pooled_mae"]


def test_full_coverage_better_candidate_is_not_over_blocked():
    """Same shape but gfs_residual now covers all 3 folds with no calm degradation -> it wins.

    Proves the coverage guard excludes ONLY on missing coverage, not on merit.
    """
    strong = _cand(0.50, 0.50, calm_mae=0.50)
    ridge = _cand(1.00, 1.00, calm_mae=1.00)
    analog = _cand(1.20, 1.20, calm_mae=1.20)
    full_results = [
        _split("f0", {"ridge": ridge, "gfs_residual": strong, "analog_arm": analog}),
        _split("f1", {"ridge": ridge, "gfs_residual": strong, "analog_arm": analog}),
        _split("f2", {"ridge": ridge, "gfs_residual": strong, "analog_arm": analog}),
    ]
    routing, detail = compute_routing_recommendation([], full_results)

    d = detail[CP23]
    assert all(d["coverage_ok"].values())
    assert d["coverage_excluded"] == []
    assert routing[CP23] == "gfs_residual"
    assert d["winner"] == "gfs_residual"


def test_calm_unverifiable_candidate_is_kept_out():
    """gfs_residual wins ALL-MAE on all folds but has NO calm metric anywhere.

    Calm preservation cannot be verified, so the conservative calm guard (A6) keeps Ridge.
    Without the guard, calm_ok would default True and gfs would wrongly win.
    """
    strong_no_calm = _cand(0.50, 0.50, calm_mae=None)   # ALL only, no calm stratum
    ridge = _cand(1.00, 1.00, calm_mae=1.00)
    analog = _cand(1.20, 1.20, calm_mae=1.20)
    full_results = [
        _split("f0", {"ridge": ridge, "gfs_residual": strong_no_calm, "analog_arm": analog}),
        _split("f1", {"ridge": ridge, "gfs_residual": strong_no_calm, "analog_arm": analog}),
        _split("f2", {"ridge": ridge, "gfs_residual": strong_no_calm, "analog_arm": analog}),
    ]
    routing, detail = compute_routing_recommendation([], full_results)

    d = detail[CP23]
    assert d["coverage_ok"]["gfs_residual"] is True   # ALL-stratum coverage is fine
    assert d["best_by_mae"] == "gfs_residual"         # it does win on MAE
    assert d["calm_ok"] is False                      # but calm cannot be verified
    assert routing[CP23] == "ridge"                   # so Ridge is kept
    assert d["winner"] == "ridge"


def test_calm_partial_coverage_candidate_is_kept_out():
    """gfs_residual wins ALL-MAE on all 3 folds but has a calm stratum in only ONE of Ridge's folds.

    The single covered fold does NOT degrade, so the old intersection-only guard would have set
    calm_ok=True and promoted gfs. The calm-COVERAGE requirement (official reviewer residual P3)
    rejects it: calm is unverified in 2 of the incumbent's 3 folds, so calm_ok=False and Ridge stays.
    """
    full_results = [
        _split("f0", {
            "ridge": _cand(1.00, 1.00, calm_mae=1.00),
            "gfs_residual": _cand(0.50, 0.50, calm_mae=0.50),   # calm present here, non-degrading
            "analog_arm": _cand(1.20, 1.20, calm_mae=1.20),
        }),
        _split("f1", {
            "ridge": _cand(1.00, 1.00, calm_mae=1.00),
            "gfs_residual": _cand(0.50, 0.50, calm_mae=None),   # ALL only, NO calm stratum
            "analog_arm": _cand(1.20, 1.20, calm_mae=1.20),
        }),
        _split("f2", {
            "ridge": _cand(1.00, 1.00, calm_mae=1.00),
            "gfs_residual": _cand(0.50, 0.50, calm_mae=None),   # ALL only, NO calm stratum
            "analog_arm": _cand(1.20, 1.20, calm_mae=1.20),
        }),
    ]
    routing, detail = compute_routing_recommendation([], full_results)

    d = detail[CP23]
    assert d["coverage_ok"]["gfs_residual"] is True   # ALL-stratum coverage is complete
    assert d["best_by_mae"] == "gfs_residual"          # it does win on MAE
    assert d["calm_ok"] is False                       # but calm is unverified in 2 of 3 incumbent folds
    assert routing[CP23] == "ridge"                    # so Ridge is kept
    assert d["winner"] == "ridge"
