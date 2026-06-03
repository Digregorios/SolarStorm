from __future__ import annotations

import numpy as np
import pytest

from core.models.mos_emos_lite import (
    MosEmosLiteConfig,
    calibrate_sigma,
    fit_mos_emos_lite,
    gaussian_discrete_dist,
    predict_dist,
    predict_int,
)


def test_gaussian_discrete_dist_normalises_and_centres_mode():
    pd = gaussian_discrete_dist(14.2, [12, 13, 14, 15, 16], sigma=1.1)

    assert sum(pd.values()) == pytest.approx(1.0)
    assert max(pd.items(), key=lambda kv: kv[1])[0] == 14


def test_fit_predict_dist_uses_train_only_scale_and_imputes_without_mutation():
    rng = np.random.default_rng(42)
    x = np.column_stack([
        np.linspace(0.0, 1.0, 140),
        rng.normal(0.0, 0.1, 140),
    ])
    y = np.rint(10.0 + 4.0 * x[:, 0]).astype(int)
    x[3, 1] = np.nan
    x_before = x.copy()

    model = fit_mos_emos_lite(
        x,
        y,
        config=MosEmosLiteConfig(feature_columns=("anchor", "noise"), min_sigma=0.75),
    )
    assert model.train_n == 140
    assert model.sigma >= 0.75
    np.testing.assert_array_equal(x, x_before)

    pred_int = predict_int(model, x[:5])
    assert pred_int.shape == (5,)

    dists = predict_dist(model, x[:2], [[8, 9, 10, 11, 12], [8, 9, 10, 11, 12]])
    assert len(dists) == 2
    for pd in dists:
        assert sum(pd.values()) == pytest.approx(1.0)

    calibrated = calibrate_sigma(
        model,
        x[-30:],
        y[-30:] + 2,
        config=MosEmosLiteConfig(feature_columns=("anchor", "noise"), min_sigma=0.75),
    )
    assert calibrated.sigma >= model.sigma
    assert calibrated.train_n == model.train_n


def test_fit_requires_minimum_rows():
    with pytest.raises(ValueError, match="Need >= 100"):
        fit_mos_emos_lite(
            np.ones((20, 2)),
            np.ones(20, dtype=int),
            config=MosEmosLiteConfig(feature_columns=("a", "b")),
        )


def _metric(n=20, mae=1.0, rps=1.0):
    return {
        "n": n,
        "mae": mae,
        "rmse": mae,
        "bracket_match": 0.5,
        "rps": rps,
        "ic80_coverage": 0.8,
        "ic80_mean_width": 3.0,
    }


def _fold(*, mos_mae, mos_rps, mos_calm_mae, mos_cov=1.0):
    return {
        "arms": {
            "served_v0": {
                "ALL": _metric(mae=1.0, rps=1.0), "calm": _metric(mae=1.0, rps=1.0),
                "coverage": 1.0, "engaged_n": 20,
            },
            "mos_ecmwf": {
                "ALL": _metric(mae=mos_mae, rps=mos_rps), "calm": _metric(mae=mos_calm_mae, rps=0.9),
                "coverage": mos_cov, "engaged_n": int(20 * mos_cov),
            },
            "emos2_lite": {
                "ALL": _metric(mae=1.2, rps=1.2), "calm": _metric(mae=1.2, rps=1.2),
                "coverage": 1.0, "engaged_n": 20,
            },
        }
    }


def test_track_c_decision_requires_all_fold_wins_and_calm_guard():
    from scripts.evaluate_mos_emos_lite_v0 import _decide

    ok = _decide({
        "20:00": [
            _fold(mos_mae=0.9, mos_rps=0.9, mos_calm_mae=1.04),
            _fold(mos_mae=0.8, mos_rps=0.8, mos_calm_mae=1.00),
        ]
    })
    assert ok["20:00"]["candidates"]["mos_ecmwf"]["eligible_for_followup_prereg"] is True

    loses_one_fold = _decide({
        "20:00": [
            _fold(mos_mae=0.9, mos_rps=0.9, mos_calm_mae=1.0),
            _fold(mos_mae=1.1, mos_rps=0.8, mos_calm_mae=1.0),
        ]
    })
    assert loses_one_fold["20:00"]["candidates"]["mos_ecmwf"]["eligible_for_followup_prereg"] is False

    calm_regresses = _decide({
        "20:00": [
            _fold(mos_mae=0.9, mos_rps=0.9, mos_calm_mae=1.06),
            _fold(mos_mae=0.8, mos_rps=0.8, mos_calm_mae=1.00),
        ]
    })
    assert calm_regresses["20:00"]["candidates"]["mos_ecmwf"]["eligible_for_followup_prereg"] is False


def test_track_c_decision_requires_min_coverage():
    from scripts.evaluate_mos_emos_lite_v0 import _decide

    # 1. High coverage -> eligible
    ok = _decide({
        "20:00": [
            _fold(mos_mae=0.9, mos_rps=0.9, mos_calm_mae=1.0, mos_cov=0.9),
            _fold(mos_mae=0.8, mos_rps=0.8, mos_calm_mae=1.0, mos_cov=0.8),
        ]
    })
    assert ok["20:00"]["candidates"]["mos_ecmwf"]["coverage_ok"] is True
    assert ok["20:00"]["candidates"]["mos_ecmwf"]["eligible_for_followup_prereg"] is True

    # 2. Low coverage on one fold -> coverage_ok is False -> not eligible
    low_cov = _decide({
        "20:00": [
            _fold(mos_mae=0.9, mos_rps=0.9, mos_calm_mae=1.0, mos_cov=0.9),
            _fold(mos_mae=0.8, mos_rps=0.8, mos_calm_mae=1.0, mos_cov=0.5), # 50% coverage < 70% threshold
        ]
    })
    assert low_cov["20:00"]["candidates"]["mos_ecmwf"]["coverage_ok"] is False
    assert low_cov["20:00"]["candidates"]["mos_ecmwf"]["eligible_for_followup_prereg"] is False
