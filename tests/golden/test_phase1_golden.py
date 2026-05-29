"""Golden tests for Phase 1 (T-1-9, REQ-REP-2).

Compares current labels + per-CP features vs frozen fixtures in
``tests/golden/phase1/``. A diff means either a regression or an intentional
change that requires updating the golden file.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from core.contracts.station import load_station_config
from core.features.builder import build_cp_features
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels


GOLDEN = Path(__file__).resolve().parent / "phase1"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def pipeline_outputs():
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    return cfg, obs, labels


@pytest.mark.parametrize("name,d", [
    ("summer_2025_01_15", date(2025, 1, 15)),
    ("winter_2024_07_15", date(2024, 7, 15)),
    ("dst_end_2025_04_06", date(2025, 4, 6)),
])
def test_golden_matches(pipeline_outputs, name, d):
    cfg, obs, labels = pipeline_outputs
    fix_path = GOLDEN / f"{name}.json"
    if not fix_path.exists():
        pytest.skip(f"Golden missing: {fix_path}")
    with open(fix_path, encoding="ascii") as fh:
        fix = json.load(fh)
    row = labels.filter(labels["date_local"] == d)
    assert row.height == 1
    actual_label = row.row(0, named=True)
    # Compare key scalar fields
    for key in ("tmax_int", "tmin_int", "n_obs_total", "n_obs_valid", "day_complete", "max_gap_min", "quartile_ok"):
        expected = fix["label"][key]
        actual = actual_label[key]
        assert actual == expected, f"{name}/{key}: actual={actual} expected={expected}"
    # Compare per-CP features (k_cp, feature_max_ts <= cp_utc)
    for cp, expected_feats in fix["cp_features"].items():
        if "error" in expected_feats:
            continue
        f = build_cp_features(obs, date_local=d, cp_hhmm=cp, tz_name=cfg.tz, labels=labels)
        assert f.features.get("k_cp") == expected_feats["k_cp"]
        assert f.cp_utc.isoformat() == expected_feats["cp_utc"]
        assert f.feature_max_ts_utc.isoformat() == expected_feats["feature_max_ts_utc"]
        assert f.feature_max_ts_utc < f.cp_utc, "Causality violation in golden"
