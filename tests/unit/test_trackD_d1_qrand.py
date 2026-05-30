"""Track D.D1 randomized quantization Q_rand: determinism, no-leak, invariants, unbiasedness.

Pre-registered minimal checklist (contracts/phase5_amendment_trackD_d1_randomized_Q.md;
update.txt 2026-05-30). Q_rand is unbiased standard randomized rounding (ceil w.p. frac(x)),
keyed deterministically by (global_seed, row_id, endpoint_side[, split_name]).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pytest

from core.calibration.conformal import (
    NormalizedConformalConfig,
    apply_normalized_conformal,
    apply_normalized_conformal_qrand,
    fit_normalized_conformal,
)
from core.contracts.quantization import Q_rand, row_id

SEED = 20260530


def test_qrand_deterministic_same_inputs_same_output():
    rid = row_id("NZWN", date(2025, 1, 1), datetime(2025, 1, 1, 23, tzinfo=timezone.utc))
    a = Q_rand(10.37, global_seed=SEED, row_id_hex=rid, endpoint_side="lo")
    b = Q_rand(10.37, global_seed=SEED, row_id_hex=rid, endpoint_side="lo")
    assert a == b
    # endpoint_side decorrelates: lo vs hi may differ in draw but stay in {10, 11}
    assert Q_rand(10.37, global_seed=SEED, row_id_hex=rid, endpoint_side="hi") in (10, 11)
    assert a in (10, 11)


def test_qrand_reduces_to_exact_integer_and_extremes():
    rid = row_id("NZWN", date(2025, 1, 1), "23:00")
    assert Q_rand(12.0, global_seed=SEED, row_id_hex=rid, endpoint_side="lo") == 12  # frac 0 -> exact
    # frac -> 0 means ceil only if u < ~0; floor dominates. frac -> 1 means ceil dominates.
    lows = [Q_rand(5.0001, global_seed=SEED, row_id_hex=row_id("NZWN", d, "23:00"),
                    endpoint_side="lo") for d in _dates(200)]
    assert set(lows) <= {5, 6} and lows.count(5) > lows.count(6)  # almost always floor


def test_row_id_no_leak_keys_only():
    # row_id depends ONLY on (station, day_local, cp_utc) - not index/label/features.
    r1 = row_id("NZWN", date(2025, 3, 4), "23:00")
    r2 = row_id("NZWN", date(2025, 3, 4), "23:00")
    r3 = row_id("NZWN", date(2025, 3, 5), "23:00")
    assert r1 == r2 and r1 != r3
    assert len(r1) == 64  # sha256 hex


def _dates(n: int):
    from datetime import timedelta
    return [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]


def _fit_cal(n=400, seed=0):
    rng = np.random.default_rng(seed)
    yp = rng.normal(15.0, 3.0, n)
    yt = np.array([int(round(v + rng.normal(0, 1.5))) for v in yp])
    sig = np.abs(rng.normal(2.0, 0.5, n))  # p50_var-like variance proxy
    cfg = NormalizedConformalConfig()
    return fit_normalized_conformal(yt, yp, sig.tolist(), config=cfg), yp, sig


def test_qrand_apply_invariants_hi_ge_lo_and_int_dtype():
    cal, yp, sig = _fit_cal()
    rids = [row_id("NZWN", d, "23:00") for d in _dates(len(yp))]
    lo, hi = apply_normalized_conformal_qrand(
        cal, yp, sig.tolist(), rids, global_seed=SEED, split_name="2025"
    )
    assert lo.dtype == np.int32 and hi.dtype == np.int32
    assert np.all(hi >= lo)


def test_qrand_apply_is_deterministic_run_to_run():
    cal, yp, sig = _fit_cal()
    rids = [row_id("NZWN", d, "23:00") for d in _dates(len(yp))]
    lo1, hi1 = apply_normalized_conformal_qrand(cal, yp, sig.tolist(), rids, global_seed=SEED)
    lo2, hi2 = apply_normalized_conformal_qrand(cal, yp, sig.tolist(), rids, global_seed=SEED)
    assert np.array_equal(lo1, lo2) and np.array_equal(hi1, hi2)


def test_qrand_unbiased_on_grid():
    # E[Q_rand(x)] ~= x averaged over many distinct row_ids (read-only sanity).
    xs = [3.1, 7.5, 10.25, 12.8, 0.5, 19.99]
    for x in xs:
        draws = [
            Q_rand(x, global_seed=SEED, row_id_hex=row_id("NZWN", d, "23:00"), endpoint_side="lo")
            for d in _dates(4000)
        ]
        assert abs(np.mean(draws) - x) < 0.05  # predefined tolerance


def test_ab_seed_changes_assignment_but_keeps_invariants():
    cal, yp, sig = _fit_cal()
    rids = [row_id("NZWN", d, "23:00") for d in _dates(len(yp))]
    loA, hiA = apply_normalized_conformal_qrand(cal, yp, sig.tolist(), rids, global_seed=SEED)
    loB, hiB = apply_normalized_conformal_qrand(cal, yp, sig.tolist(), rids, global_seed=SEED + 1)
    assert np.all(hiA >= loA) and np.all(hiB >= loB)  # invariants hold for both
    assert not (np.array_equal(loA, loB) and np.array_equal(hiA, hiB))  # assignment changes
    # aggregate coverage on a constructed truth stays close between seeds (read-only)
    yt = np.array([int(round(v)) for v in yp])
    covA = float(((loA <= yt) & (yt <= hiA)).mean())
    covB = float(((loB <= yt) & (yt <= hiB)).mean())
    assert abs(covA - covB) < 0.05
