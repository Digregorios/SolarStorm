"""T-11-8 Phase 4: CQR LightGBM quantile IC80 evaluation (honest GO/KILL).

Prereg: contracts/cqr_lightgbm_quantile_v0_prereg.md (prereg_version 1.0, FROZEN).

What this does
--------------
Per split, per CP: fit two LightGBM quantile boosters q_lo=q(0.10)/q_hi=q(0.90) on a
TRAIN-FIT slice, CQR-conformalize the bounds on a DISJOINT CALIB slice (the most-recent
``CALIB_FRAC`` of the train window), and emit the integer IC80 on the held-out TEST slice
(``core.models.quantile_lgbm``). Train/calib/test are disjoint by construction and the
quantile levels are FROZEN (no per-split tuning) -- prereg gate condition 6.

The FROZEN gate (conditions 1-6) is applied to the PRIMARY arm only:

  PRIMARY = obs + GFS features, walk-forward 2023/24/25 (3 folds).

GFS is the best feature set that spans the full 2023-2025 walk-forward (ECMWF only exists
from 2024-03), so the prereg's "best available set" reduces to obs+GFS for the gate; ECMWF
and the |GFS-ECMWF| two-model spread enter as ABLATIONS on the 2-fold overlap window only
(they cannot drive the 3-fold gate). Feature sets are fixed BEFORE the run (anti-gaming).

Baselines on IDENTICAL rows
---------------------------
- ``ridge_conformal_minimal`` (core.models.ridge_conformal): the WIDTH baseline (gate 3).
  Same TRAIN-FIT/CALIB/TEST rows; Ridge owns the center p50, IC80 = 80% conformal quantile
  of its own integer abs-residuals. CQR mean width must NOT exceed this.
- Ridge-band center RPS: the POINT/RPS guardrail proxy for the v1.0 baseline (gate 4). RPS
  is a property of the CENTER prob_dist; the v1.0 center is the Ridge band, so CQR's q(0.50)
  prob_dist RPS is compared against the Ridge band prob_dist RPS on identical rows. Labelled
  a proxy in the report (the full Phase-5 signed-conformal object is not reconstructed; it is
  FORBIDDEN scope and would not change the CENTER's RPS anyway).

L1/L2/width diagnostic (reported BEFORE any verdict): global IC80 coverage (L1),
per-width-quartile coverage / REQ-AUD-5 het gate (L2), mean-width ratio vs the baseline.

Determinism: seed 42, lightgbm deterministic=True, num_threads=1 (REQ-MOD-6).
Scope: this file + core/models/quantile_lgbm.py + reports/calibration/cqr_lightgbm_quantile_v0.*.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from core.baselines.climatology import fit_climatology, fit_tmax_hour_climatology
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.gates_phase5 import heteroscedasticity_gate
from core.eval.metrics import rps
from core.features.training_panel import (
    FEATURE_COLUMNS,
    NWP_FEATURE_COLUMNS,
    build_training_panel,
)
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import (
    build_features as build_risk_features,
    fit_risk_model,
    predict_risk,
)
from core.models.loss import latent_to_prob_dist
from core.models.quantile_lgbm import (
    QuantileLgbmConfig,
    conformalize,
    fit_quantile_lgbm,
    predict_interval_int,
    predict_median,
)
from core.models.ridge_band import (
    RidgeBandConfig,
    fit_ridge_band,
    predict_latent as predict_ridge_latent,
)
from core.models.ridge_conformal import fit_cp_abs_conformal, interval

REPO = Path(__file__).resolve().parents[1]
SEED = 42
np.random.seed(SEED)

ECMWF_START = date(2024, 3, 1)
ECMWF_END = date(2025, 12, 31)

# Primary gate: 3 walk-forward folds (obs+GFS spans this whole range).
FULL_SPLITS = [
    ("full-2023", date(2020, 1, 1), date(2022, 12, 31), date(2023, 1, 1), date(2023, 12, 31)),
    ("full-2024", date(2020, 1, 1), date(2023, 12, 31), date(2024, 1, 1), date(2024, 12, 31)),
    ("full-2025", date(2020, 1, 1), date(2024, 12, 31), date(2025, 1, 1), date(2025, 12, 31)),
]
# Ablation window: 2 folds where ECMWF (and thus the two-model spread) exists.
ECMWF_SPLITS = [
    ("ecmwf-2025H1", ECMWF_START, date(2024, 12, 31), date(2025, 1, 1), date(2025, 6, 30)),
    ("ecmwf-2025H2", ECMWF_START, date(2025, 6, 30), date(2025, 7, 1), date(2025, 12, 31)),
]

OBS_GFS_FEATURES = tuple(FEATURE_COLUMNS) + tuple(NWP_FEATURE_COLUMNS)
SPREAD_COL = "nwp_t2m_at_cp_spread_c"  # = std across NWP models = the |GFS-ECMWF| spread
NO_SPREAD_FEATURES = tuple(c for c in OBS_GFS_FEATURES if c != SPREAD_COL)

CPS = ["20:00", "21:00", "22:00", "23:00"]
LATE_CP = "23:00"  # the "late-CP" stratum (gate condition 5)
N_ESTIMATORS = 500  # production default; eval == serving (no tuning)
CALIB_FRAC = 0.20  # most-recent fraction of TRAIN reserved for CQR / ridge conformalization
COVERAGE = 0.80
COV_LOW, COV_HIGH = 0.78, 0.86  # gate condition 1 band
RPS_REL_TOL = 0.02  # gate condition 4: <= +2% relative
NEED_SPLITS = 2  # ">= 2/3 splits" applied uniformly to conditions 1-5
_CLIM_IDX = list(FEATURE_COLUMNS).index("clim_tmax_c_dec")


# --------------------------------------------------------------------------- #
# small helpers                                                               #
# --------------------------------------------------------------------------- #
def _arrays(panel: pl.DataFrame, columns) -> tuple[np.ndarray, np.ndarray]:
    X = np.column_stack([panel[c].to_numpy().astype(float) for c in columns])
    y = panel["target_tmax_int"].to_numpy().astype(int)
    return X, y


def _clim_vec(climo, dates) -> np.ndarray:
    return np.array([float(climo.tmax_dec_for(d)) for d in dates], dtype=float)


def _q_int(latent: np.ndarray) -> np.ndarray:
    return np.array([Q(float(v)) for v in latent], dtype=np.int32)


def _rps_mean(latent, y_int, climo, dates, tau, mode, tmp_min, tmp_max) -> float:
    vals = []
    for i, d in enumerate(dates):
        p10, p90 = climo.percentiles_for(d)
        sk = support_K(p10, p90, tmp_min=tmp_min, tmp_max=tmp_max)
        pd_ = latent_to_prob_dist(float(latent[i]), sk, tau=tau, mode=mode)
        vals.append(rps(pd_, int(y_int[i])))
    return float(np.mean(vals)) if vals else float("nan")


def _causal_climo(labels: pl.DataFrame, tr_end: date):
    sub = labels.filter(pl.col("date_local") <= tr_end).select(
        ["date_local", "tmax_int", "day_complete"]
    )
    return fit_climatology(sub, train_start=date(2020, 1, 1), train_end=tr_end)


def _regime_masks(tr_start, tr_end, test_dates, risk_df_full):
    """Ex-ante non_calm / high_delta_06 masks aligned to ``test_dates`` (train-only thresholds)."""
    risk_train = risk_df_full.filter(
        (pl.col("date_local") >= tr_start) & (pl.col("date_local") <= tr_end)
    )
    risk_test = risk_df_full.filter(pl.col("date_local").is_in(test_dates))
    n = len(test_dates)
    if risk_train.height < 100:
        return np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)

    risk_model = fit_risk_model(risk_train, seed=SEED)
    c30 = float(np.percentile(predict_risk(risk_model, risk_train), 30))
    risk_map = {}
    if risk_test.height:
        for d, p in zip(risk_test["date_local"].to_list(), predict_risk(risk_model, risk_test)):
            risk_map[d] = float(p)
    non_calm = np.array([risk_map.get(d, 0.0) >= c30 for d in test_dates])

    delta_train = [
        v for v in risk_train["delta_06_to_cp"].to_list()
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]
    delta_p50 = float(np.median(delta_train)) if delta_train else 0.0
    delta_map = {row["date_local"]: row.get("delta_06_to_cp") for row in risk_test.iter_rows(named=True)}

    def _hi(d):
        v = delta_map.get(d)
        return v is not None and not (isinstance(v, float) and math.isnan(v)) and v >= delta_p50

    high_delta = np.array([_hi(d) for d in test_dates])
    return non_calm, high_delta


# --------------------------------------------------------------------------- #
# per-CP evaluation: CQR + identical-rows ridge_conformal_minimal baseline    #
# --------------------------------------------------------------------------- #
def _eval_one_cp(
    panel, cp, tr_start, tr_end, te_start, te_end, feature_cols,
    climo, cfg_ridge, risk_df_full, tau, mode, tmp_min, tmp_max, n_estimators,
):
    """Return per-row arrays for one (split, CP, feature set), or None if too thin."""
    sub = panel.filter((panel["cp"] == cp) & pl.col("nwp_t2m_maxtraj_c").is_not_null())
    tr = sub.filter((pl.col("date_local") >= tr_start) & (pl.col("date_local") <= tr_end)).sort("date_local")
    te = sub.filter((pl.col("date_local") >= te_start) & (pl.col("date_local") <= te_end)).sort("date_local")
    if te.height < 20:
        return None, f"test thin ({te.height})"
    n_calib = max(30, int(round(tr.height * CALIB_FRAC)))
    if tr.height - n_calib < 100:
        return None, f"train-fit thin ({tr.height - n_calib})"
    fit_df, cal_df = tr.head(tr.height - n_calib), tr.tail(n_calib)

    fit_dates = fit_df["date_local"].to_list()
    cal_dates = cal_df["date_local"].to_list()
    te_dates = te["date_local"].to_list()

    # CQR on the requested feature set (clim feature overwritten with the causal climo).
    X_fit, y_fit = _arrays(fit_df, feature_cols)
    X_cal, y_cal = _arrays(cal_df, feature_cols)
    X_te, y_te = _arrays(te, feature_cols)
    X_fit[:, _CLIM_IDX] = _clim_vec(climo, fit_dates)
    X_cal[:, _CLIM_IDX] = _clim_vec(climo, cal_dates)
    X_te[:, _CLIM_IDX] = _clim_vec(climo, te_dates)

    cqr_cfg = QuantileLgbmConfig(
        feature_columns=tuple(feature_cols), coverage=COVERAGE,
        n_estimators=n_estimators, fit_median=True, tau=tau, mode=mode,
    )
    model = fit_quantile_lgbm(X_fit, y_fit, config=cqr_cfg)
    cal = conformalize(model, X_cal, y_cal)
    cqr_lo, cqr_hi = predict_interval_int(model, cal, X_te)
    cqr_center = predict_median(model, X_te)

    # ridge_conformal_minimal on the SAME rows (obs-only ridge center + own abs-residual IC80).
    Xo_fit, _ = _arrays(fit_df, FEATURE_COLUMNS)
    Xo_cal, _ = _arrays(cal_df, FEATURE_COLUMNS)
    Xo_te, _ = _arrays(te, FEATURE_COLUMNS)
    clim_fit = _clim_vec(climo, fit_dates)
    Xo_fit[:, _CLIM_IDX] = clim_fit
    Xo_cal[:, _CLIM_IDX] = _clim_vec(climo, cal_dates)
    Xo_te[:, _CLIM_IDX] = _clim_vec(climo, te_dates)
    ridge = fit_ridge_band(Xo_fit, y_fit, config=cfg_ridge, clim_train=clim_fit)
    p50_cal = _q_int(predict_ridge_latent(ridge, Xo_cal, clim=_clim_vec(climo, cal_dates)))
    abs_resid = np.abs(y_cal - p50_cal).astype(int)
    rc = fit_cp_abs_conformal(abs_resid.tolist(), [cp] * len(abs_resid), coverage=COVERAGE, n_min=30)
    ridge_latent = predict_ridge_latent(ridge, Xo_te, clim=_clim_vec(climo, te_dates))
    p50_te = _q_int(ridge_latent)
    r_lo, r_hi = [], []
    for p in p50_te:
        lo, hi, _ = interval(rc, int(p), cp)
        r_lo.append(lo)
        r_hi.append(hi)

    non_calm, high_delta = _regime_masks(tr_start, tr_end, te_dates, risk_df_full)

    return {
        "cp": cp,
        "dates": te_dates,
        "y": y_te.astype(int),
        "cqr_lo": np.asarray(cqr_lo, dtype=int),
        "cqr_hi": np.asarray(cqr_hi, dtype=int),
        "cqr_center": np.asarray(cqr_center, dtype=float),
        "ridge_lo": np.asarray(r_lo, dtype=int),
        "ridge_hi": np.asarray(r_hi, dtype=int),
        "ridge_center": np.asarray(ridge_latent, dtype=float),
        "non_calm": non_calm,
        "high_delta": high_delta,
        "e_correction": float(cal.e_correction),
        "certified": bool(cal.certified),
        "n_calib": int(cal.n_calib),
    }, "ok"


def _coverage(lo, hi, y) -> float:
    if len(y) == 0:
        return float("nan")
    return float(np.mean((lo <= y) & (y <= hi)))


def _mean_width(lo, hi) -> float:
    if len(lo) == 0:
        return float("nan")
    return float(np.mean(hi - lo + 1))


def _stratum_block(lo, hi, y, mask) -> dict:
    if mask is None:
        m = np.ones(len(y), dtype=bool)
    else:
        m = mask
    n = int(m.sum())
    if n < 5:
        return {"n": n, "coverage": None, "mean_width": None}
    return {
        "n": n,
        "coverage": round(_coverage(lo[m], hi[m], y[m]), 4),
        "mean_width": round(_mean_width(lo[m], hi[m]), 4),
    }


# --------------------------------------------------------------------------- #
# PRIMARY arm: obs+GFS, 3 folds, frozen gate                                  #
# --------------------------------------------------------------------------- #
def run_primary(panel_gfs, labels, risk_df_full, cfg_ridge, tau, mode, tmp_min, tmp_max, n_estimators):
    split_summaries = []
    for split_name, tr_s, tr_e, te_s, te_e in FULL_SPLITS:
        print(f"[primary] {split_name}")
        climo = _causal_climo(labels, tr_e)
        per_cp = {}
        pooled = {k: [] for k in ("cqr_lo", "cqr_hi", "cqr_center", "ridge_lo", "ridge_hi",
                                  "ridge_center", "y", "non_calm", "high_delta")}
        pooled_dates = []
        cp_of_row = []
        for cp in CPS:
            res, status = _eval_one_cp(
                panel_gfs, cp, tr_s, tr_e, te_s, te_e, OBS_GFS_FEATURES,
                climo, cfg_ridge, risk_df_full, tau, mode, tmp_min, tmp_max, n_estimators,
            )
            if res is None:
                per_cp[cp] = {"status": status}
                continue
            per_cp[cp] = {
                "status": "ok",
                "n_test": len(res["y"]),
                "cqr": _stratum_block(res["cqr_lo"], res["cqr_hi"], res["y"], None),
                "ridge_conformal_minimal": _stratum_block(res["ridge_lo"], res["ridge_hi"], res["y"], None),
                "e_correction": round(res["e_correction"], 4),
                "certified": res["certified"],
                "n_calib": res["n_calib"],
            }
            for k in pooled:
                pooled[k].append(res[k])
            pooled_dates.extend(res["dates"])
            cp_of_row.extend([cp] * len(res["y"]))

        if not pooled["y"]:
            split_summaries.append({"split": split_name, "status": "no_cp_evaluated"})
            continue

        agg = {k: np.concatenate(v) for k, v in pooled.items()}
        cp_arr = np.array(cp_of_row, dtype=object)
        late_mask = cp_arr == LATE_CP

        het = heteroscedasticity_gate(agg["cqr_lo"], agg["cqr_hi"], agg["y"])
        cqr_rps = _rps_mean(agg["cqr_center"], agg["y"], climo, pooled_dates, tau, mode, tmp_min, tmp_max)
        ridge_rps = _rps_mean(agg["ridge_center"], agg["y"], climo, pooled_dates, tau, mode, tmp_min, tmp_max)

        strata = {
            "ALL": None,
            "calm": ~agg["non_calm"],
            "non_calm": agg["non_calm"],
            "high_delta_06": agg["high_delta"],
            "late_cp_23": late_mask,
        }
        cqr_strata = {s: _stratum_block(agg["cqr_lo"], agg["cqr_hi"], agg["y"], m) for s, m in strata.items()}
        ridge_strata = {s: _stratum_block(agg["ridge_lo"], agg["ridge_hi"], agg["y"], m) for s, m in strata.items()}

        split_summaries.append({
            "split": split_name,
            "status": "ok",
            "n_test_pooled": int(len(agg["y"])),
            "global_coverage": round(_coverage(agg["cqr_lo"], agg["cqr_hi"], agg["y"]), 4),
            "het_passed": bool(het.passed),
            "het_mixed_in_and_out": bool(het.mixed_in_and_out),
            "het_bins": [
                {"width_lo": b.width_lo, "width_hi": b.width_hi, "coverage": round(b.coverage, 4),
                 "mean_width": round(b.mean_width, 4), "n": b.n}
                for b in het.bins
            ],
            "cqr_mean_width": round(_mean_width(agg["cqr_lo"], agg["cqr_hi"]), 4),
            "ridge_mean_width": round(_mean_width(agg["ridge_lo"], agg["ridge_hi"]), 4),
            "cqr_rps": round(cqr_rps, 4),
            "ridge_rps": round(ridge_rps, 4),
            "rps_rel_delta": round((cqr_rps - ridge_rps) / ridge_rps, 4) if ridge_rps else None,
            "cqr_strata": cqr_strata,
            "ridge_strata": ridge_strata,
            "by_cp": per_cp,
        })
    return split_summaries


def apply_frozen_gate(split_summaries):
    """Apply the FROZEN prereg gate (conditions 1-6). >= 2/3 splits for conditions 1-5."""
    ok_splits = [s for s in split_summaries if s.get("status") == "ok"]
    n_ok = len(ok_splits)

    c1 = [COV_LOW <= s["global_coverage"] <= COV_HIGH for s in ok_splits]
    c2 = [s["het_passed"] for s in ok_splits]
    c3 = [s["cqr_mean_width"] <= s["ridge_mean_width"] for s in ok_splits]
    c4 = [
        (s["rps_rel_delta"] is not None and s["rps_rel_delta"] <= RPS_REL_TOL)
        for s in ok_splits
    ]

    def _hard_strata_ok(s):
        # condition 5: no IC80 regression in late-CP / non_calm / high-delta -> require
        # CQR coverage within [0.78,0.86] there (the adaptivity must show up where it matters).
        out = []
        for st in ("late_cp_23", "non_calm", "high_delta_06"):
            blk = s["cqr_strata"].get(st, {})
            cov = blk.get("coverage")
            if cov is None:
                continue
            out.append(COV_LOW <= cov <= COV_HIGH)
        return bool(out) and all(out)

    c5 = [_hard_strata_ok(s) for s in ok_splits]

    cond = {
        "c1_global_coverage_in_band": {"per_split": c1, "n_pass": sum(c1), "need": NEED_SPLITS, "pass": sum(c1) >= NEED_SPLITS},
        "c2_het_gate": {"per_split": c2, "n_pass": sum(c2), "need": NEED_SPLITS, "pass": sum(c2) >= NEED_SPLITS},
        "c3_width_not_exceed_ridge": {"per_split": c3, "n_pass": sum(c3), "need": NEED_SPLITS, "pass": sum(c3) >= NEED_SPLITS},
        "c4_rps_not_worse_2pct": {"per_split": c4, "n_pass": sum(c4), "need": NEED_SPLITS, "pass": sum(c4) >= NEED_SPLITS},
        "c5_no_hard_strata_regression": {"per_split": c5, "n_pass": sum(c5), "need": NEED_SPLITS, "pass": sum(c5) >= NEED_SPLITS},
        "c6_disjoint_deterministic_no_tuning": {"pass": True, "note": "train/calib/test disjoint by construction; seed 42 deterministic; quantile levels frozen in prereg"},
    }
    go = bool(n_ok >= NEED_SPLITS and all(cond[k]["pass"] for k in cond))
    verdict = "GO" if go else "KILL"

    failed = [k for k in cond if not cond[k]["pass"]]
    return {
        "verdict": verdict,
        "n_ok_splits": n_ok,
        "aggregation_rule": ">= 2/3 splits satisfy each of conditions 1-5; condition 6 structural",
        "conditions": cond,
        "failed_conditions": failed,
    }


# --------------------------------------------------------------------------- #
# ablations on the ECMWF overlap window (ECMWF add; spread on/off)            #
# --------------------------------------------------------------------------- #
def _ablation_arm(panel, feature_cols, labels, risk_df_full, cfg_ridge, tau, mode, tmp_min, tmp_max, n_estimators):
    rows = {k: [] for k in ("cqr_lo", "cqr_hi", "cqr_center", "y", "non_calm", "high_delta")}
    dates = []
    for split_name, tr_s, tr_e, te_s, te_e in ECMWF_SPLITS:
        climo = _causal_climo(labels, tr_e)
        for cp in CPS:
            res, _ = _eval_one_cp(
                panel, cp, tr_s, tr_e, te_s, te_e, feature_cols,
                climo, cfg_ridge, risk_df_full, tau, mode, tmp_min, tmp_max, n_estimators,
            )
            if res is None:
                continue
            for k in rows:
                rows[k].append(res[k])
            dates.extend(res["dates"])
    if not rows["y"]:
        return None
    agg = {k: np.concatenate(v) for k, v in rows.items()}
    strata = {"ALL": None, "calm": ~agg["non_calm"], "non_calm": agg["non_calm"], "high_delta_06": agg["high_delta"]}
    return {
        "global_coverage": round(_coverage(agg["cqr_lo"], agg["cqr_hi"], agg["y"]), 4),
        "mean_width": round(_mean_width(agg["cqr_lo"], agg["cqr_hi"]), 4),
        "het_passed": bool(heteroscedasticity_gate(agg["cqr_lo"], agg["cqr_hi"], agg["y"]).passed),
        "n": int(len(agg["y"])),
        "by_regime": {s: _stratum_block(agg["cqr_lo"], agg["cqr_hi"], agg["y"], m) for s, m in strata.items()},
    }


def run_ablations(panel_gfs_ecmwf_window, panel_ens, labels, risk_df_full, cfg_ridge, tau, mode, tmp_min, tmp_max, n_estimators):
    print("[ablation] obs+GFS (ECMWF window)")
    arm_gfs = _ablation_arm(panel_gfs_ecmwf_window, OBS_GFS_FEATURES, labels, risk_df_full, cfg_ridge, tau, mode, tmp_min, tmp_max, n_estimators)
    print("[ablation] obs+GFS+ECMWF with spread")
    arm_with = _ablation_arm(panel_ens, OBS_GFS_FEATURES, labels, risk_df_full, cfg_ridge, tau, mode, tmp_min, tmp_max, n_estimators)
    print("[ablation] obs+GFS+ECMWF without spread")
    arm_without = _ablation_arm(panel_ens, NO_SPREAD_FEATURES, labels, risk_df_full, cfg_ridge, tau, mode, tmp_min, tmp_max, n_estimators)
    return {
        "window": "ecmwf_overlap_2024_03..2025_12_2folds",
        "note": ("Single station (NZWN); spread ablation interacted with REGIME only (no cross-station "
                 "interaction possible). The spread ablation (with vs without) is SAME-ROWS (both on the "
                 "GFS+ECMWF ensemble panel). The ECMWF-add arms (obs_gfs vs obs_gfs_ecmwf) are rough "
                 "context only: the GFS panel and ensemble panel can differ in date coverage, so it is "
                 "NOT a strict same-rows comparison."),
        "ecmwf_add": {"obs_gfs": arm_gfs, "obs_gfs_ecmwf": arm_with},
        "spread_ablation": {"with_spread": arm_with, "without_spread": arm_without},
    }


# --------------------------------------------------------------------------- #
# reporting                                                                   #
# --------------------------------------------------------------------------- #
def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def write_reports(primary, gate, ablations, n_estimators):
    out_dir = REPO / "reports" / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "task": "T-11-8",
        "prereg": "contracts/cqr_lightgbm_quantile_v0_prereg.md",
        "prereg_version": "1.0",
        "git_sha": _git_sha(),
        "seed": SEED,
        "deterministic": True,
        "num_threads": 1,
        "n_estimators": n_estimators,
        "calib_frac": CALIB_FRAC,
        "coverage_target": COVERAGE,
        "primary_feature_set": "obs+GFS (best set spanning the 3-fold walk-forward; ECMWF/spread are ablations only)",
        "gate": gate,
        "primary_splits": primary,
        "ablations": ablations,
    }
    (out_dir / "cqr_lightgbm_quantile_v0.json").write_text(
        json.dumps(report, default=str, ensure_ascii=True, indent=2), encoding="ascii"
    )
    (out_dir / "cqr_lightgbm_quantile_v0.md").write_text(_render_md(report), encoding="ascii")
    print(f"\n[DONE] reports -> {out_dir}/cqr_lightgbm_quantile_v0.(json|md)")


def _render_md(r) -> str:
    g = r["gate"]
    L = [
        "# T-11-8: CQR LightGBM Quantile IC80 -- Phase 4 Evaluation",
        "",
        f"**Verdict: {g['verdict']}**  (prereg {r['prereg']} v{r['prereg_version']}, frozen gate)",
        "",
        f"- git_sha: `{r['git_sha']}`  seed: {r['seed']}  deterministic: {r['deterministic']}  num_threads: {r['num_threads']}",
        f"- n_estimators: {r['n_estimators']}  calib_frac: {r['calib_frac']}  coverage_target: {r['coverage_target']}",
        f"- Primary feature set: {r['primary_feature_set']}",
        f"- Gate aggregation: {g['aggregation_rule']}",
        "",
        "## Gate (frozen conditions 1-6)",
        "",
        "| # | Condition | per-split | pass |",
        "|---|-----------|-----------|------|",
    ]
    labels = {
        "c1_global_coverage_in_band": "1. global IC80 in [0.78,0.86]",
        "c2_het_gate": "2. REQ-AUD-5 het gate",
        "c3_width_not_exceed_ridge": "3. width <= ridge_conformal_minimal",
        "c4_rps_not_worse_2pct": "4. RPS <= +2% vs ridge center (v1.0 proxy)",
        "c5_no_hard_strata_regression": "5. hard-strata IC80 in band",
        "c6_disjoint_deterministic_no_tuning": "6. disjoint/deterministic/no-tuning",
    }
    for k, lab in labels.items():
        c = g["conditions"][k]
        ps = c.get("per_split", "structural")
        L.append(f"| {lab} | {ps} | {'PASS' if c['pass'] else 'FAIL'} |")
    if g["failed_conditions"]:
        L += ["", f"**Failed:** {', '.join(g['failed_conditions'])}"]

    L += ["", "## L1/L2/width diagnostic per split (primary obs+GFS)", "",
          "| split | n | global cov (L1) | het pass (L2) | CQR width | ridge width | CQR RPS | ridge RPS | RPS rel |",
          "|-------|---|-----------------|---------------|-----------|-------------|---------|-----------|---------|"]
    for s in r["primary_splits"]:
        if s.get("status") != "ok":
            L.append(f"| {s['split']} | - | {s.get('status')} | - | - | - | - | - | - |")
            continue
        L.append(
            f"| {s['split']} | {s['n_test_pooled']} | {s['global_coverage']} | {s['het_passed']} | "
            f"{s['cqr_mean_width']} | {s['ridge_mean_width']} | {s['cqr_rps']} | {s['ridge_rps']} | {s['rps_rel_delta']} |"
        )

    L += ["", "## Per-stratum CQR IC80 coverage (primary)", "",
          "| split | stratum | n | coverage | mean width |",
          "|-------|---------|---|----------|------------|"]
    for s in r["primary_splits"]:
        if s.get("status") != "ok":
            continue
        for st, blk in s["cqr_strata"].items():
            L.append(f"| {s['split']} | {st} | {blk['n']} | {blk['coverage']} | {blk['mean_width']} |")

    ab = r["ablations"]
    L += ["", "## Ablations (ECMWF overlap window, 2 folds)", "", f"_{ab['note']}_", ""]
    L += ["### ECMWF add (does ECMWF help over obs+GFS?)", "",
          "| arm | global cov | mean width | het pass | n |",
          "|-----|-----------|------------|----------|---|"]
    for name, arm in ab["ecmwf_add"].items():
        if arm:
            L.append(f"| {name} | {arm['global_coverage']} | {arm['mean_width']} | {arm['het_passed']} | {arm['n']} |")
    L += ["", "### |GFS-ECMWF| spread ablation (with vs without the spread feature)", "",
          "| arm | global cov | mean width | het pass | n |",
          "|-----|-----------|------------|----------|---|"]
    for name, arm in ab["spread_ablation"].items():
        if arm:
            L.append(f"| {name} | {arm['global_coverage']} | {arm['mean_width']} | {arm['het_passed']} | {arm['n']} |")
    L += ["", "#### spread ablation x regime (coverage / mean width)", "",
          "| arm | regime | n | coverage | mean width |",
          "|-----|--------|---|----------|------------|"]
    for name, arm in ab["spread_ablation"].items():
        if not arm:
            continue
        for reg, blk in arm["by_regime"].items():
            L.append(f"| {name} | {reg} | {blk['n']} | {blk['coverage']} | {blk['mean_width']} |")

    L += ["", "## Notes", "",
          "- CALIBRATION-ONLY evaluation (IC80 interval). No execution, no Polymarket, no decision wiring.",
          "- ridge_conformal_minimal computed on the SAME GFS-present rows as CQR (identical-rows width comparison).",
          "- RPS baseline is the Ridge-band CENTER prob_dist (v1.0 center proxy); the full Phase-5 signed-conformal",
          "  object is out of scope and would not change the CENTER's RPS.",
          "- Conditions 1-5 require >= 2/3 splits; condition 6 is structural (disjoint/deterministic/frozen levels).",
          ""]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
def main() -> int:
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="1 fold / 1 CP / small trees plumbing check (NOT the gate run)")
    args = parser.parse_args()

    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        model_cfg = yaml.safe_load(fh)
    tau = float(model_cfg["prob_dist"]["tau"])
    mode = str(model_cfg["prob_dist"]["mode"])
    tmp_min = cfg.tmp_c_int_plausibility.min
    tmp_max = cfg.tmp_c_int_plausibility.max
    cp_op = cfg.cp_operational_utc
    tz = cfg.tz

    n_estimators = 60 if args.smoke else N_ESTIMATORS
    print("=== T-11-8: CQR LightGBM Quantile IC80 Evaluation ===")
    print(f"  seed={SEED} deterministic=True num_threads=1 n_estimators={n_estimators} smoke={args.smoke}")

    print("[0] load obs + labels ...")
    obs, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=tmp_min, tmp_max_c=tmp_max)
    labels = build_tmax_labels(obs, tz_name=tz, cp_set_utc=cfg.cp_set_utc)
    risk_df_full = build_risk_features(obs, labels, tz, cp_op)

    print("[1] climatologies + NWP snapshots ...")
    climo_broad = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))
    thc = fit_tmax_hour_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=tz)
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    gfs_snaps = read_snapshots(station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root)
    ecmwf_snaps = read_snapshots(station=cfg.icao, model=ECMWF_IFS_HRES, endpoint="single_runs", out_root=nwp_root)
    ensemble_snaps = pl.concat([gfs_snaps, ecmwf_snaps], how="vertical_relaxed")

    cp_set = cfg.cp_set_utc
    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=tau, mode=mode, use_climatology_anchor=True,
    )

    print("[2] build full-window obs+GFS panel ...")
    all_dates_full = sorted(d for d in labels["date_local"].unique().to_list()
                            if d is not None and date(2020, 1, 1) <= d <= ECMWF_END)
    panel_gfs = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set, dates=all_dates_full,
        nwp_snapshots=gfs_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc,
    )

    global FULL_SPLITS, CPS
    if args.smoke:
        FULL_SPLITS = FULL_SPLITS[-1:]
        CPS = [LATE_CP]

    print("[3] PRIMARY arm (obs+GFS, frozen gate) ...")
    primary = run_primary(panel_gfs, labels, risk_df_full, cfg_ridge, tau, mode, tmp_min, tmp_max, n_estimators)
    gate = apply_frozen_gate(primary)
    print(f"  VERDICT: {gate['verdict']}  failed={gate['failed_conditions']}")

    if args.smoke:
        print("[smoke] skipping ablations + report write")
        print(json.dumps(primary, default=str, indent=2)[:2000])
        return 0

    print("[4] ablations (ECMWF window: ECMWF add + spread on/off) ...")
    ecmwf_dates = sorted(d for d in labels["date_local"].unique().to_list()
                         if d is not None and ECMWF_START <= d <= ECMWF_END)
    panel_ens = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set, dates=ecmwf_dates,
        nwp_snapshots=ensemble_snaps, nwp_models=(NCEP_GFS.id, ECMWF_IFS_HRES.id), tmax_hour_climo=thc,
    )
    ablations = run_ablations(panel_gfs, panel_ens, labels, risk_df_full, cfg_ridge, tau, mode, tmp_min, tmp_max, n_estimators)

    write_reports(primary, gate, ablations, n_estimators)
    print(f"\n=== VERDICT: {gate['verdict']} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
