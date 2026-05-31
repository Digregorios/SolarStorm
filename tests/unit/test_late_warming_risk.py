"""late_warming_risk_model_v0: causality (no post-CP leak), determinism, prob range, bucket."""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import polars as pl
import pytest

from core.models.late_warming_risk import (
    FEATURE_NAMES, build_features, fit_risk_model, predict_risk, risk_bucket,
)

_TZ = "Pacific/Auckland"


def _obs(rows):
    return pl.DataFrame(
        {
            "ts_utc": pl.Series([r[0] for r in rows], dtype=pl.Datetime("us", time_zone="UTC")),
            "tmp_c_int": pl.Series([r[1] for r in rows], dtype=pl.Int32),
            "dq_tmp_c_int": ["ok"] * len(rows),
            "drct": pl.Series([r[2] for r in rows], dtype=pl.Float64),
            "wxcodes": [r[3] for r in rows],
            "p01i": pl.Series([r[4] for r in rows], dtype=pl.Float64),
        }
    )


def _labels(d, tmax):
    return pl.DataFrame(
        {"date_local": [d], "tmax_int": [tmax], "day_complete": [True]},
        schema={"date_local": pl.Date, "tmax_int": pl.Int32, "day_complete": pl.Boolean},
    )


def _winter_day_rows():
    # 2024-07-10 NZST=UTC+12; CP 23:00 UTC = 2024-07-09 23:00 UTC (~11:00 local).
    # obs across the local morning, all BEFORE cp_utc (2024-07-09 23:00Z).
    base = datetime(2024, 7, 9, 12, 0, tzinfo=timezone.utc)  # 00:00 local
    rows = []
    for k in range(0, 11):  # 12:00Z..22:00Z = 00:00..10:00 local
        rows.append((base.replace(hour=12 + k), 8 + k % 4, 200.0, None, 0.0))
    return rows


def test_features_built_and_target_present():
    d = date(2024, 7, 10)
    df = build_features(_obs(_winter_day_rows()), _labels(d, 14), _TZ, "23:00")
    assert df.height == 1
    assert set(FEATURE_NAMES).issubset(df.columns) and "target" in df.columns


def test_no_leak_post_cp_obs_do_not_change_features():
    d = date(2024, 7, 10)
    rows = _winter_day_rows()
    df_before = build_features(_obs(rows), _labels(d, 14), _TZ, "23:00")
    # append a hot, northerly afternoon obs AFTER cp_utc (2024-07-10 02:00Z = 14:00 local)
    rows_after = rows + [(datetime(2024, 7, 10, 2, 0, tzinfo=timezone.utc), 20, 10.0, None, 0.0)]
    df_after = build_features(_obs(rows_after), _labels(d, 20), _TZ, "23:00")
    for c in FEATURE_NAMES:
        assert df_before[c][0] == df_after[c][0], f"feature {c} leaked post-CP info"


def _synthetic_panel(n=400, seed=0):
    rng = np.random.default_rng(seed)
    delta = rng.normal(2.0, 1.5, n)
    south = rng.integers(0, 2, n)
    rain = rng.integers(0, 2, n)
    # target driven by the precursors + noise (enhance on delta, suppress on south/rain)
    logit = 0.4 * (delta - 2.0) - 0.8 * south - 1.0 * rain + rng.normal(0, 0.5, n)
    y = (1 / (1 + np.exp(-logit)) > 0.5).astype(int)
    m = rng.integers(1, 13, n)
    return pl.DataFrame({
        "delta_06_to_cp": delta, "southerly_at_cp": south, "rain_persistence_path": rain,
        "month_sin": np.sin(2 * np.pi * m / 12), "month_cos": np.cos(2 * np.pi * m / 12),
        "target": y, "month": m,
    })


def test_fit_predict_deterministic_and_in_range():
    tr = _synthetic_panel(400, 0)
    te = _synthetic_panel(120, 1)
    m1 = fit_risk_model(tr)
    m2 = fit_risk_model(tr)
    p1 = predict_risk(m1, te)
    p2 = predict_risk(m2, te)
    assert np.allclose(p1, p2)                      # deterministic
    assert np.all((p1 >= 0) & (p1 <= 1))            # valid probabilities


def test_isotonic_calibration_path_runs():
    tr = _synthetic_panel(400, 0)
    cal = _synthetic_panel(120, 2)
    te = _synthetic_panel(120, 3)
    m = fit_risk_model(tr, calib=cal)
    assert m.isotonic is not None
    p = predict_risk(m, te)
    assert p.shape == (te.height,)


def test_risk_bucket_thresholds():
    assert risk_bucket(0.10) == "low"
    assert risk_bucket(0.40) == "mid"
    assert risk_bucket(0.60) == "high"
