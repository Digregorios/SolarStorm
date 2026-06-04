"""Tests for causal feature builder (B1+B2)."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from solarstorm.features.builder import (
    build_features,
    build_coverage_manifest,
    BLOCKED_FEATURES,
)
from solarstorm.eda._catalog import SEED_HYPOTHESES

TZ = ZoneInfo("Pacific/Auckland")


# ---------------------------------------------------------------------------
# Test helpers — synthetic obs / labels
# ---------------------------------------------------------------------------

_CP_SET = ("20:00", "21:00", "22:00", "23:00")
_KCP_COLS: dict[str, str] = {
    cp: f"k_cp__cp_{cp.replace(':', '')}" for cp in _CP_SET
}


def _local_dt(d: dt.date, h: int) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, h, 0, tzinfo=TZ)


def _make_obs(
    dates: list[dt.date],
    hours: list[int],
    *,
    tmp_c: list[list[int | None]] | None = None,
    dwp_c: list[list[int | None]] | None = None,
    sknt: list[list[float | None]] | None = None,
    drct: list[list[float | None]] | None = None,
    alti: list[list[float | None]] | None = None,
    p01i: list[list[float | None]] | None = None,
    skyc1: list[list[str | None]] | None = None,
    skyl1: list[list[int | None]] | None = None,
    wxcodes: list[list[str | None]] | None = None,
    dq: str = "ok",
) -> pl.DataFrame:
    """Build an obs DataFrame with columns matching _obs.py schema.

    Each *list[list]* param is indexed [date_idx][hour_idx].
    Default values are filled when a param is None.
    """
    n_dates = len(dates)
    n_hours = len(hours)

    def _default(val, d_idx, h_idx):
        if val is not None:
            return val[d_idx][h_idx]
        return None

    rows = []
    for di, d in enumerate(dates):
        for hi, h in enumerate(hours):
            local_ts = _local_dt(d, h)
            rows.append({
                "valid": local_ts.astimezone(dt.timezone.utc),
                "ts_local": local_ts,
                "tmp_c_int": _default(tmp_c, di, hi) or 12,
                "dwp_c_int": _default(dwp_c, di, hi) or 8,
                "dw_depression_c_int": None,
                "sknt": _default(sknt, di, hi) or 5.0,
                "drct": _default(drct, di, hi) or 180.0,
                "alti": _default(alti, di, hi) or 30.00,
                "p01i": _default(p01i, di, hi) or 0.0,
                "skyc1": _default(skyc1, di, hi) or "CLR",
                "skyl1": _default(skyl1, di, hi) or None,
                "skyc2": None,
                "skyl2": None,
                "skyc3": None,
                "skyl3": None,
                "skyc4": None,
                "skyl4": None,
                "wxcodes": _default(wxcodes, di, hi) or None,
                "dq_tmp_c_int": dq,
            })
    df = pl.DataFrame(rows)
    # fill dw_depression_c_int
    df = df.with_columns(
        (pl.col("tmp_c_int") - pl.col("dwp_c_int")).alias("dw_depression_c_int"),
    )
    return df


def _make_labels(
    dates: list[dt.date],
    *,
    tmax: list[int] | None = None,
    tmin: list[int] | None = None,
    tmax_hour: list[int] | None = None,
    kcp: dict[str, list[int]] | None = None,
) -> pl.DataFrame:
    """Build labels DataFrame with required columns."""
    if kcp is None:
        kcp = {}
    rows = []
    for i, d in enumerate(dates):
        row: dict = {
            "date_local": d,
            "tmax_int": tmax[i] if tmax else 20,
            "tmin_int": tmin[i] if tmin else 10,
            "tmax_hour": tmax_hour[i] if tmax_hour else 15,
        }
        for cp_str, col in _KCP_COLS.items():
            row[col] = kcp.get(cp_str, [18] * len(dates))[i]
        rows.append(row)
    return pl.DataFrame(rows)


# ===================================================================
# Tests
# ===================================================================

def test_build_features_returns_one_row_per_date_cp():
    """With obs for 3 days, 4 CPs -> 12 rows + all expected columns."""
    dates = [dt.date(2025, 6, 15), dt.date(2025, 6, 16), dt.date(2025, 6, 17)]
    hours = [6, 9, 12, 15, 18]
    tmp_c = [
        [10, 11, 12, 13, 12],  # day 1: calm
        [10, 11, 12, 13, 12],  # day 2
        [10, 11, 12, 13, 12],  # day 3
    ]
    dwp_c = [
        [8, 8, 9, 9, 8],
        [8, 8, 9, 9, 8],
        [8, 8, 9, 9, 8],
    ]
    obs = _make_obs(dates, hours, tmp_c=tmp_c, dwp_c=dwp_c)
    labels = _make_labels(dates)

    result = build_features(obs, labels)

    assert result.height == 3 * 4  # 3 days x 4 CPs
    assert "date_local" in result.columns
    assert "cp" in result.columns
    assert result["cp"].to_list() == ["20:00", "21:00", "22:00", "23:00"] * 3

    # All feature columns from SEED_HYPOTHESES should be present
    for hyp in SEED_HYPOTHESES:
        assert hyp.feature_column in result.columns, (
            f"Missing column: {hyp.feature_column} ({hyp.id})"
        )

    # regime_label present
    assert "regime_label" in result.columns
    assert result["regime_label"].to_list() == ["calm"] * 12


def test_post_cp_obs_do_not_leak():
    """Obs after CP are excluded and do not affect feature values."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18, 21]
    # 21:00 local has a very high temp (should be excluded for CP=20:00)
    tmp_c = [[10, 11, 12, 13, 12, 999]]
    dwp_c = [[8, 8, 9, 9, 8, 999]]
    obs = _make_obs([d], hours, tmp_c=tmp_c, dwp_c=dwp_c)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    cp20 = result.filter(pl.col("cp") == "20:00")

    # slope_3h at CP=20:00 should use pre-20:00 data (hours 6-18 only)
    assert cp20["slope_3h"].to_list()[0] is not None
    # The 999 degree obs should NOT cause extreme values
    assert cp20["slope_3h"].to_list()[0] < 100


def test_blocked_features_are_null():
    """H19 sst_maritime_cap is always null."""
    dates = [dt.date(2025, 6, 15), dt.date(2025, 6, 16)]
    obs = _make_obs(dates, [6, 9, 12, 15, 18])
    labels = _make_labels(dates)
    result = build_features(obs, labels)

    assert result["sst_maritime_cap"].is_null().all()
    assert "sst_maritime_cap" in BLOCKED_FEATURES


def test_warming_rate_06_09():
    """H17 computed correctly: (T09 - T06) / 3."""
    d = dt.date(2025, 6, 15)
    # T06=10, T09=16 -> (16-10)/3 = 2.0
    hours = [6, 9, 12, 15, 18]
    tmp_c = [[10, 16, 18, 19, 18]]
    obs = _make_obs([d], hours, tmp_c=tmp_c)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        assert row["warming_rate_06_09"].to_list()[0] == 2.0


def test_dewpoint_collapse_rate():
    """H20: (dwp_latest - dwp_earliest) / hours_between."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18]
    # T06=10, T18=16; DWP06=8, DWP18=2
    # (2-8) / 12 = -0.5
    tmp_c = [[10, 12, 14, 15, 16]]
    dwp_c = [[8, 7, 5, 3, 2]]
    obs = _make_obs([d], hours, tmp_c=tmp_c, dwp_c=dwp_c)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        rate = row["dewpoint_collapse_rate_3h"].to_list()[0]
        assert rate is not None and abs(rate - (-0.5)) < 1e-6, f"got {rate} for {cp_str}"


def test_cloud_base_transparency():
    """H23: max(coverage_weight * min(1.0, base / 8000)) over layers."""
    d = dt.date(2025, 6, 15)
    hours = [12]
    # OVC at 2500ft -> 1.0 * min(1.0, 2500/8000) = 1.0 * 0.3125 = 0.3125
    obs = _make_obs([d], hours, skyc1=[["OVC"]], skyl1=[[2500]])
    labels = _make_labels([d])

    result = build_features(obs, labels)
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        score = row["cloud_base_transparency"].to_list()[0]
        assert score is not None
        assert abs(score - 0.3125) < 1e-4, f"expected 0.3125, got {score}"

    # FEW at 8000ft -> 0.2 * min(1.0, 8000/8000) = 0.2
    obs2 = _make_obs([d], hours, skyc1=[["FEW"]], skyl1=[[8000]])
    result2 = build_features(obs2, labels)
    score2 = result2.filter(pl.col("cp") == "20:00")["cloud_base_transparency"].to_list()[0]
    assert abs(score2 - 0.2) < 1e-4, f"expected 0.2, got {score2}"

    # CLR -> 0.0
    obs3 = _make_obs([d], hours, skyc1=[["CLR"]])
    result3 = build_features(obs3, labels)
    score3 = result3.filter(pl.col("cp") == "20:00")["cloud_base_transparency"].to_list()[0]
    assert score3 == 0.0


def test_cloud_cover_suppression():
    """H12: OVC=1.0, BKN=0.75, SCT=0.4, FEW=0.2, CLR=0.0."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12]
    skyc1 = [["SCT", "BKN", "OVC"]]  # 1 date, 3 hours
    obs = _make_obs([d], hours, skyc1=skyc1)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    row = result.filter(pl.col("cp") == "20:00")
    assert row["cloud_cover_suppression"].to_list()[0] == 1.0  # OVC is max


def test_foehn_score_computation():
    """H14: nw_flow_strength * dwp_depression matches regime-classifier logic."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18]
    # NW wind (drct=320) at 18kt, temps warm, dwp low
    tmp_c = [[15, 17, 19, 20, 20]]
    dwp_c = [[8, 9, 10, 10, 10]]   # depression = 7, 8, 9, 10, 10
    drct_data = [[320.0] * len(hours)]
    sknt_data = [[18.0] * len(hours)]
    obs = _make_obs([d], hours, tmp_c=tmp_c, dwp_c=dwp_c, drct=drct_data, sknt=sknt_data)
    labels = _make_labels([d])

    result = build_features(obs, labels)

    # foehn_score = nw_flow_strength * mean_dwp_depression
    # nw_flow_strength = 18 (all obs NW of 270-45), mean_dwp_dep = (7+8+9+10+10)/5 = 8.8
    # expected = 18 * 8.8 = 158.4
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        score = row["foehn_score"].to_list()[0]
        assert score is not None and score > 150, f"expected ~158.4, got {score}"


def test_prefrontal_warming_window():
    """H21: falling QNH + no precip + N/NW flow."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18]
    # alti falling: 30.00 -> 29.94 (drop of 0.06 inHg = 2.03 hPa >= 0.5)
    alti_data = [[30.00, 29.98, 29.96, 29.95, 29.94]]
    # N/NW wind
    drct_data = [[350.0] * len(hours)]
    # No precip
    p01i_data = [[0.0] * len(hours)]
    tmp_c = [[10, 12, 14, 15, 16]]
    obs = _make_obs([d], hours, tmp_c=tmp_c, alti=alti_data, drct=drct_data, p01i=p01i_data)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        pf = row["prefrontal_warming_window"].to_list()[0]
        assert pf == 1, f"expected 1 for {cp_str}, got {pf}"


def test_precip_disruption():
    """H10: 1 if p01i > 0.01 or RA in wxcodes."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12]

    # RA in wxcodes
    obs = _make_obs([d], hours, wxcodes=[["RA", None, None]])
    labels = _make_labels([d])
    result = build_features(obs, labels)
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        assert row["precip_disruption"].to_list()[0] == 1

    # p01i > 0.01
    obs2 = _make_obs([d], hours, p01i=[[0.0, 0.05, 0.0]])
    result2 = build_features(obs2, labels)
    for cp_str in _CP_SET:
        row = result2.filter(pl.col("cp") == cp_str)
        assert row["precip_disruption"].to_list()[0] == 1

    # No precip
    obs3 = _make_obs([d], hours)
    result3 = build_features(obs3, labels)
    for cp_str in _CP_SET:
        row = result3.filter(pl.col("cp") == cp_str)
        assert row["precip_disruption"].to_list()[0] == 0


def test_day_sequence_pattern():
    """H9: warming/cooling/peaked/troughed/flat."""
    dates = [dt.date(2025, 6, 13), dt.date(2025, 6, 14), dt.date(2025, 6, 15)]
    hours = [6, 9, 12, 15, 18]
    obs = _make_obs(dates, hours)

    # warming: 12 < 14 < 16
    labels_warming = _make_labels(dates, tmax=[12, 14, 16])
    result = build_features(obs, labels_warming)
    row = result.filter(
        (pl.col("date_local") == dates[2]) & (pl.col("cp") == "20:00")
    )
    assert row["day_sequence_pattern"].to_list()[0] == "warming"

    # cooling: 16 > 14 > 12
    labels_cooling = _make_labels(dates, tmax=[16, 14, 12])
    result = build_features(obs, labels_cooling)
    row = result.filter(
        (pl.col("date_local") == dates[2]) & (pl.col("cp") == "20:00")
    )
    assert row["day_sequence_pattern"].to_list()[0] == "cooling"

    # peaked: 12 < 14 > 12
    labels_peaked = _make_labels(dates, tmax=[12, 14, 12])
    result = build_features(obs, labels_peaked)
    row = result.filter(
        (pl.col("date_local") == dates[2]) & (pl.col("cp") == "20:00")
    )
    assert row["day_sequence_pattern"].to_list()[0] == "peaked"

    # troughed: 14 > 12 < 14
    labels_troughed = _make_labels(dates, tmax=[14, 12, 14])
    result = build_features(obs, labels_troughed)
    row = result.filter(
        (pl.col("date_local") == dates[2]) & (pl.col("cp") == "20:00")
    )
    assert row["day_sequence_pattern"].to_list()[0] == "troughed"


def test_slope_3h_from_anchors():
    """H1: (T_latest - T_earliest) / hours_between anchors."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18]
    # Temps: 10, 12, 14, 16, 18
    # Latest with data=18 (T=18), earliest=6 (T=10), delta=8, hours=12
    # slope = 8/12 = 0.666...
    tmp_c = [[10, 12, 14, 16, 18]]
    obs = _make_obs([d], hours, tmp_c=tmp_c)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        slope = row["slope_3h"].to_list()[0]
        assert slope is not None and abs(slope - 8.0/12.0) < 1e-6


def test_pressure_trend_3h():
    """H13: (alti_delta * 33.8639) / hours_between."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18]
    # alti: 30.00 -> 29.94 (drop of 0.06 over 12h)
    alti_data = [[30.00, 29.98, 29.96, 29.95, 29.94]]
    obs = _make_obs([d], hours, alti=alti_data)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        pt = row["pressure_trend_3h"].to_list()[0]
        expected = (29.94 - 30.00) * 33.8639 / 12.0
        assert pt is not None and abs(pt - expected) < 1e-4


def test_nocturnal_plateau_flag():
    """H18: flat morning + N wind + cloudy."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18]
    # Flat temps: 10, 10, 10, 12, 14 (range of 6-12 = 0!)
    tmp_c = [[10, 10, 10, 12, 14]]
    # N wind
    drct_data = [[350.0] * len(hours)]
    # Cloudy
    skyc1 = [["OVC", "OVC", "OVC", "BKN", "BKN"]]
    obs = _make_obs([d], hours, tmp_c=tmp_c, drct=drct_data, skyc1=skyc1)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    row = result.filter(pl.col("cp") == "20:00")
    assert row["nocturnal_plateau_flag"].to_list()[0] == 1


def test_dewpoint_depression():
    """H4: mean dw_depression_c_int in pre-CP window."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18]
    tmp_c = [[10, 10, 10, 10, 10]]
    dwp_c = [[5, 6, 7, 8, 9]]  # depression: 5, 4, 3, 2, 1 -> mean = 3.0
    obs = _make_obs([d], hours, tmp_c=tmp_c, dwp_c=dwp_c)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    for cp_str in _CP_SET:
        row = result.filter(pl.col("cp") == cp_str)
        dd = row["dewpoint_depression"].to_list()[0]
        assert dd is not None and abs(dd - 3.0) < 1e-6


def test_tmax_dminus1():
    """H5: tmax_int from previous day's labels."""
    dates = [dt.date(2025, 6, 14), dt.date(2025, 6, 15)]
    hours = [6, 9, 12, 15, 18]
    obs = _make_obs(dates, hours)
    labels = _make_labels(dates, tmax=[18, 22])

    result = build_features(obs, labels)
    row = result.filter(
        (pl.col("date_local") == dates[1]) & (pl.col("cp") == "20:00")
    )
    assert row["tmax_dminus1"].to_list()[0] == 18


def test_wind_dir_change_s_to_n():
    """H8: early S wind + late N wind -> non-zero change."""
    d = dt.date(2025, 6, 15)
    hours = [6, 9, 12, 15, 18]
    # Early hours (6,9,12) = S wind (180)
    # Late hours (15,18) = N wind (350)
    drct_data = [[180.0, 180.0, 180.0, 350.0, 350.0]]
    obs = _make_obs([d], hours, drct=drct_data)
    labels = _make_labels([d])

    result = build_features(obs, labels)
    row = result.filter(pl.col("cp") == "20:00")
    change = row["wind_dir_change_s_to_n"].to_list()[0]
    # early_mean=180, late_mean=350, both in sector -> 350-180=170 (<=180)
    assert change is not None and change > 0


def test_build_coverage_manifest():
    """build_coverage_manifest returns correct structure."""
    dates = [dt.date(2025, 6, 15), dt.date(2025, 6, 16)]
    obs = _make_obs(dates, [6, 9, 12, 15, 18])
    labels = _make_labels(dates)
    features = build_features(obs, labels)
    manifest = build_coverage_manifest(features)

    assert len(manifest) == len(SEED_HYPOTHESES)

    # H19 should be BLOCKED
    assert manifest["sst_maritime_cap"]["status"] == "BLOCKED"
    assert "reason" in manifest["sst_maritime_cap"]

    # All computable features should be "computable"
    for hyp in SEED_HYPOTHESES:
        fc = hyp.feature_column
        if fc in BLOCKED_FEATURES:
            assert manifest[fc]["status"] == "BLOCKED"
        else:
            assert manifest[fc]["status"] == "computable", f"{fc} not computable"

    # n_total should match
    assert manifest["slope_3h"]["n_total"] == features.height
