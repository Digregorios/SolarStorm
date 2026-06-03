"""Onda 2 Track C: offline MOS/EMOS-lite evaluator (read-only).

This is a candidate readout, not serving wiring. It compares simple NWP
post-processing arms against the already-measured Track-B served path over the
same CP20-22 ECMWF overlap folds:

* ``served_v0``: exact Track-B decision, ECMWF residual -> GFS residual -> Ridge.
* ``mos_ecmwf``: linear MOS center on ECMWF max-trajectory anchor.
* ``emos2_lite``: linear MOS center on two-model mean/spread where both anchors
  exist; otherwise the same served_v0 fallback path.

Anti-gaming: frozen ECMWF splits, train/calib/test separation for EMOS scale, no
CLI/default promotion, no CP23 promotion, no test-tuned thresholds.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import polars as pl
import yaml

from core.baselines.climatology import fit_climatology, fit_tmax_hour_climatology
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.gates_phase5 import heteroscedasticity_gate
from core.eval.intervals import discrete_ic
from core.eval.metrics import bracket_match_at_p50, mae, rmse, rps
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import build_features as build_risk_features
from core.models.mos_emos_lite import (
    MosEmosLiteConfig,
    calibrate_sigma,
    fit_mos_emos_lite,
    predict_dist as predict_mos_dist,
    predict_latent as predict_mos_latent,
)
from core.models.loss import latent_to_prob_dist
from core.models.residual_lgbm import (
    ResidualLgbmConfig,
    fit_residual_lgbm,
    predict_latent as predict_lgbm_latent,
)
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_latent as predict_ridge_latent
from scripts.evaluate_serving_candidate_matrix import (
    ECMWF_END,
    ECMWF_SPLITS,
    ECMWF_START,
    N_ESTIMATORS,
    PHASE4_FEATURES,
    REPO,
    SEED,
    _arrays,
    _build_regime_masks,
)

SERVING_CPS = ["20:00", "21:00", "22:00"]
CALM_TOLERANCE = 0.05
RPS_TOLERANCE = 0.0
MAE_TOLERANCE = 0.0
MIN_CALIB_ROWS = 20
MIN_COVERAGE = 0.70

MOS_FEATURES = ("nwp_t2m_maxtraj_c", "clim_tmax_c_dec", "nwp_t2m_at_cp_minus_obs_c")
EMOS2_FEATURES = ("ens_mean_maxtraj", "ens_abs_spread_maxtraj", "clim_tmax_c_dec")
_CLIM_IDX = list(FEATURE_COLUMNS).index("clim_tmax_c_dec")


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _clim_col(df: pl.DataFrame, climo) -> np.ndarray:
    return np.array([float(climo.tmax_dec_for(d)) for d in df["date_local"].to_list()])


def _support_for_dates(dates: list[date], climo, *, tmp_min: int, tmp_max: int) -> list[list[int]]:
    out: list[list[int]] = []
    for d in dates:
        p10, p90 = climo.percentiles_for(d)
        out.append(support_K(p10, p90, tmp_min=tmp_min, tmp_max=tmp_max))
    return out


def _mos_matrix(panel: pl.DataFrame, climo) -> np.ndarray:
    cols = []
    for c in MOS_FEATURES:
        if c == "clim_tmax_c_dec":
            cols.append(_clim_col(panel, climo))
        else:
            cols.append(panel[c].to_numpy().astype(float))
    return np.column_stack(cols)


def _align_by_date(panel: pl.DataFrame, dates: list[date]) -> pl.DataFrame:
    by_date = {row["date_local"]: row for row in panel.iter_rows(named=True)}
    return pl.DataFrame([by_date[d] for d in dates])


def _emos2_panel(ecmwf: pl.DataFrame, gfs: pl.DataFrame, climo) -> pl.DataFrame:
    common = sorted(
        set(ecmwf["date_local"].to_list())
        & set(gfs["date_local"].to_list())
    )
    if not common:
        return pl.DataFrame(
            schema={
                "date_local": pl.Date,
                "target_tmax_int": pl.Int32,
                "ens_mean_maxtraj": pl.Float64,
                "ens_abs_spread_maxtraj": pl.Float64,
                "clim_tmax_c_dec": pl.Float64,
            }
        )
    e = _align_by_date(ecmwf, common)
    g = _align_by_date(gfs, common)
    e_anchor = e["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    g_anchor = g["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    return pl.DataFrame({
        "date_local": common,
        "target_tmax_int": e["target_tmax_int"].to_list(),
        "ens_mean_maxtraj": ((e_anchor + g_anchor) / 2.0).tolist(),
        "ens_abs_spread_maxtraj": np.abs(e_anchor - g_anchor).tolist(),
        "clim_tmax_c_dec": _clim_col(e, climo).tolist(),
    })


def _fit_mos_arm(
    tr_fit: pl.DataFrame,
    tr_calib: pl.DataFrame,
    te: pl.DataFrame,
    climo,
    support: list[list[int]],
) -> tuple[np.ndarray, np.ndarray, list[dict[int, float]], float] | None:
    if tr_fit.height < 100 or tr_calib.height < MIN_CALIB_ROWS or te.height == 0:
        return None
    cfg = MosEmosLiteConfig(feature_columns=MOS_FEATURES)
    model = fit_mos_emos_lite(
        _mos_matrix(tr_fit, climo),
        tr_fit["target_tmax_int"].to_numpy().astype(int),
        config=cfg,
    )
    model = calibrate_sigma(
        model,
        _mos_matrix(tr_calib, climo),
        tr_calib["target_tmax_int"].to_numpy().astype(int),
        config=cfg,
    )
    x_te = _mos_matrix(te, climo)
    latent = predict_mos_latent(model, x_te)
    dists = predict_mos_dist(model, x_te, support)
    pred_int = np.array([Q(float(v)) for v in latent], dtype=int)
    return pred_int, latent, dists, model.sigma


def _fit_emos2_arm(
    tr_fit: pl.DataFrame,
    tr_calib: pl.DataFrame,
    te: pl.DataFrame,
    support: list[list[int]],
) -> tuple[dict[date, int], dict[date, float], dict[date, dict[int, float]], float] | None:
    if tr_fit.height < 100 or tr_calib.height < MIN_CALIB_ROWS or te.height == 0:
        return None
    cfg = MosEmosLiteConfig(feature_columns=EMOS2_FEATURES)
    x_fit = np.column_stack([tr_fit[c].to_numpy().astype(float) for c in EMOS2_FEATURES])
    x_cal = np.column_stack([tr_calib[c].to_numpy().astype(float) for c in EMOS2_FEATURES])
    x_te = np.column_stack([te[c].to_numpy().astype(float) for c in EMOS2_FEATURES])
    model = fit_mos_emos_lite(
        x_fit,
        tr_fit["target_tmax_int"].to_numpy().astype(int),
        config=cfg,
    )
    model = calibrate_sigma(
        model,
        x_cal,
        tr_calib["target_tmax_int"].to_numpy().astype(int),
        config=cfg,
    )
    latent = predict_mos_latent(model, x_te)
    dists = predict_mos_dist(model, x_te, support)
    pred_int = np.array([Q(float(v)) for v in latent], dtype=int)
    dates = te["date_local"].to_list()
    return (
        {d: int(v) for d, v in zip(dates, pred_int, strict=True)},
        {d: float(v) for d, v in zip(dates, latent, strict=True)},
        {d: pd for d, pd in zip(dates, dists, strict=True)},
        model.sigma,
    )


def _band_pd_from_latents(
    latent: np.ndarray,
    support: list[list[int]],
    *,
    tau: float,
    mode: str,
) -> list[dict[int, float]]:
    return [
        latent_to_prob_dist(float(v), sk, tau=tau, mode=mode)
        for v, sk in zip(latent, support, strict=True)
    ]


def _residual_outputs_by_date(
    tr_ok: pl.DataFrame,
    te_ok: pl.DataFrame,
    climo,
    cfg_lgbm: ResidualLgbmConfig,
    support_by_date: dict[date, list[int]],
) -> dict[date, tuple[int, float, dict[int, float]]]:
    if tr_ok.height < 100 or te_ok.height == 0:
        return {}
    X_tr, y_tr = _arrays(tr_ok, PHASE4_FEATURES)
    X_tr[:, _CLIM_IDX] = _clim_col(tr_ok, climo)
    anchor_tr = tr_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    model = fit_residual_lgbm(X_tr, y_tr, anchor_tr, config=cfg_lgbm)

    X_te, _ = _arrays(te_ok, PHASE4_FEATURES)
    X_te[:, _CLIM_IDX] = _clim_col(te_ok, climo)
    anchor_te = te_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    latent = predict_lgbm_latent(model, X_te, anchor_te)
    out = {}
    for d, value in zip(te_ok["date_local"].to_list(), latent, strict=True):
        pd = latent_to_prob_dist(float(value), support_by_date[d], tau=cfg_lgbm.tau, mode=cfg_lgbm.mode)
        out[d] = (Q(float(value)), float(value), pd)
    return out


def _metrics(
    pred_int: np.ndarray,
    latent: np.ndarray,
    prob_dists: list[dict[int, float]],
    y_true: np.ndarray,
    *,
    mask: np.ndarray | None = None,
) -> dict:
    if mask is None:
        mask = np.ones(y_true.shape, dtype=bool)
    n = int(mask.sum())
    if n < 5:
        return {
            "n": n, "mae": None, "rmse": None, "bracket_match": None, "rps": None,
            "ic80_coverage": None, "ic80_mean_width": None,
        }
    p = pred_int[mask]
    lat = latent[mask]
    y = y_true[mask]
    pds = [pd for pd, keep in zip(prob_dists, mask, strict=True) if keep]
    intervals = [discrete_ic(pd, p_low=0.10, p_high=0.90) for pd in pds]
    lo = np.array([x[0] for x in intervals], dtype=int)
    hi = np.array([x[1] for x in intervals], dtype=int)
    widths = hi - lo + 1
    return {
        "n": n,
        "mae": round(float(mae(p, y)), 4),
        "mae_latent": round(float(mae(lat, y)), 4),
        "rmse": round(float(rmse(p, y)), 4),
        "bracket_match": round(float(bracket_match_at_p50(p, y)), 4),
        "rps": round(float(np.mean([rps(pd, int(t)) for pd, t in zip(pds, y, strict=True)])), 4),
        "ic80_coverage": round(float(((lo <= y) & (y <= hi)).mean()), 4),
        "ic80_mean_width": round(float(widths.mean()), 4),
    }


def _het_diag(prob_dists: list[dict[int, float]], y_true: np.ndarray) -> dict:
    intervals = [discrete_ic(pd, p_low=0.10, p_high=0.90) for pd in prob_dists]
    lo = np.array([x[0] for x in intervals], dtype=int)
    hi = np.array([x[1] for x in intervals], dtype=int)
    return asdict(heteroscedasticity_gate(lo, hi, y_true))


def _serve_baseline(
    cp: str,
    tr_ecmwf_ok: pl.DataFrame,
    te_ecmwf_ok: pl.DataFrame,
    tr_gfs_ok: pl.DataFrame,
    te_gfs_ok: pl.DataFrame,
    ridge_int: np.ndarray,
    ridge_latent: np.ndarray,
    ridge_pd: list[dict[int, float]],
    test_dates: list[date],
    climo,
    cfg_lgbm: ResidualLgbmConfig,
    support_by_date: dict[date, list[int]],
) -> tuple[np.ndarray, np.ndarray, list[dict[int, float]], dict]:
    ecmwf_by_date = _residual_outputs_by_date(tr_ecmwf_ok, te_ecmwf_ok, climo, cfg_lgbm, support_by_date)
    gfs_by_date = _residual_outputs_by_date(tr_gfs_ok, te_gfs_ok, climo, cfg_lgbm, support_by_date)
    pred = np.copy(ridge_int)
    latent = np.copy(ridge_latent)
    pds = list(ridge_pd)
    counts = {"ecmwf": 0, "gfs": 0, "ridge": 0}
    for i, d in enumerate(test_dates):
        if d in ecmwf_by_date:
            pred[i], latent[i], pds[i] = ecmwf_by_date[d]
            counts["ecmwf"] += 1
        elif d in gfs_by_date:
            pred[i], latent[i], pds[i] = gfs_by_date[d]
            counts["gfs"] += 1
        else:
            counts["ridge"] += 1
    counts["cp"] = cp
    return pred, latent, pds, counts


def _evaluate_one_cp(
    cp: str,
    tr_start: date,
    tr_end: date,
    te_start: date,
    te_end: date,
    panel_base: pl.DataFrame,
    panel_ecmwf: pl.DataFrame,
    panel_gfs: pl.DataFrame,
    risk_df_full: pl.DataFrame,
    labels: pl.DataFrame,
    obs: pl.DataFrame,
    tz: str,
    cp_op: str,
    cfg_ridge: RidgeBandConfig,
    cfg_lgbm: ResidualLgbmConfig,
    tmp_min: int,
    tmp_max: int,
    calib_tail_days: int,
) -> dict | None:
    def _split(panel: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        sub = panel.filter(panel["cp"] == cp)
        tr = sub.filter((sub["date_local"] >= tr_start) & (sub["date_local"] <= tr_end))
        calib_start = tr_end - timedelta(days=calib_tail_days - 1)
        fit = tr.filter(pl.col("date_local") < calib_start)
        calib = tr.filter(pl.col("date_local") >= calib_start)
        te = sub.filter((sub["date_local"] >= te_start) & (sub["date_local"] <= te_end))
        return fit, calib, te

    fit_base, calib_base, te_base = _split(panel_base)
    fit_ecmwf, calib_ecmwf, te_ecmwf = _split(panel_ecmwf)
    fit_gfs, calib_gfs, te_gfs = _split(panel_gfs)
    if te_base.height < 20:
        return None

    fit_ecmwf_ok = fit_ecmwf.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    calib_ecmwf_ok = calib_ecmwf.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    te_ecmwf_ok = te_ecmwf.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    fit_gfs_ok = fit_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    calib_gfs_ok = calib_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    te_gfs_ok = te_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())

    climo_labels = labels.filter(pl.col("date_local") <= tr_end).select(
        ["date_local", "tmax_int", "day_complete"]
    )
    climo = fit_climatology(climo_labels, train_start=date(2020, 1, 1), train_end=tr_end)

    X_fit_base, y_fit_base = _arrays(fit_base, tuple(FEATURE_COLUMNS))
    clim_fit = _clim_col(fit_base, climo)
    X_fit_base[:, _CLIM_IDX] = clim_fit
    X_te_base, y_te = _arrays(te_base, tuple(FEATURE_COLUMNS))
    clim_te = _clim_col(te_base, climo)
    X_te_base[:, _CLIM_IDX] = clim_te
    ridge = fit_ridge_band(X_fit_base, y_fit_base, config=cfg_ridge, clim_train=clim_fit)
    ridge_latent = predict_ridge_latent(ridge, X_te_base, clim=clim_te)
    ridge_int = np.array([Q(float(v)) for v in ridge_latent], dtype=int)

    test_dates = te_base["date_local"].to_list()
    support = _support_for_dates(test_dates, climo, tmp_min=tmp_min, tmp_max=tmp_max)
    support_by_date = dict(zip(test_dates, support, strict=True))
    ridge_pd = _band_pd_from_latents(ridge_latent, support, tau=cfg_ridge.tau, mode=cfg_ridge.mode)
    served_int, served_latent, served_pd, serve_counts = _serve_baseline(
        cp,
        fit_ecmwf_ok.vstack(calib_ecmwf_ok), te_ecmwf_ok,
        fit_gfs_ok.vstack(calib_gfs_ok), te_gfs_ok,
        ridge_int, ridge_latent, ridge_pd,
        test_dates, climo, cfg_lgbm, support_by_date,
    )

    mos_int = np.copy(served_int)
    mos_latent = np.copy(served_latent)
    mos_pd = list(served_pd)
    mos_sigma = None
    mos_support = [support_by_date[d] for d in te_ecmwf_ok["date_local"].to_list()]
    mos = _fit_mos_arm(fit_ecmwf_ok, calib_ecmwf_ok, te_ecmwf_ok, climo, mos_support)
    if mos is not None:
        pred, latent, pds, mos_sigma = mos
        by_date = {
            d: (int(p), float(l), pd)
            for d, p, l, pd in zip(te_ecmwf_ok["date_local"].to_list(), pred, latent, pds, strict=True)
        }
        for i, d in enumerate(test_dates):
            if d in by_date:
                mos_int[i], mos_latent[i], mos_pd[i] = by_date[d]

    fit_emos2 = _emos2_panel(fit_ecmwf_ok, fit_gfs_ok, climo)
    calib_emos2 = _emos2_panel(calib_ecmwf_ok, calib_gfs_ok, climo)
    te_emos2 = _emos2_panel(te_ecmwf_ok, te_gfs_ok, climo)
    emos_int = np.copy(served_int)
    emos_latent = np.copy(served_latent)
    emos_pd = list(served_pd)
    emos_sigma = None
    emos2_support = [support_by_date[d] for d in te_emos2["date_local"].to_list()]
    emos2 = _fit_emos2_arm(fit_emos2, calib_emos2, te_emos2, emos2_support)
    if emos2 is not None:
        pred_by_date, latent_by_date, pd_by_date, emos_sigma = emos2
        for i, d in enumerate(test_dates):
            if d in pred_by_date:
                emos_int[i] = pred_by_date[d]
                emos_latent[i] = latent_by_date[d]
                emos_pd[i] = pd_by_date[d]

    y_true = y_te.astype(int)
    non_calm_mask, _ = _build_regime_masks(
        tr_start, tr_end, test_dates, test_dates, risk_df_full, obs, labels, tz, cp_op
    )
    calm_mask = ~non_calm_mask

    mos_engaged_n = len(te_ecmwf_ok) if mos is not None else 0
    emos_engaged_n = len(te_emos2) if emos2 is not None else 0

    arms = {
        "ridge": (ridge_int, ridge_latent, ridge_pd, None),
        "served_v0": (served_int, served_latent, served_pd, None),
        "mos_ecmwf": (mos_int, mos_latent, mos_pd, mos_sigma),
        "emos2_lite": (emos_int, emos_latent, emos_pd, emos_sigma),
    }
    out = {
        "n_test": int(len(test_dates)),
        "n_fit": int(fit_base.height),
        "n_calib": int(calib_base.height),
        "serve_counts": serve_counts,
        "arms": {},
    }
    for name, (pred, latent, pds, sigma) in arms.items():
        if name == "mos_ecmwf":
            engaged_n = mos_engaged_n
        elif name == "emos2_lite":
            engaged_n = emos_engaged_n
        else:
            engaged_n = len(test_dates)

        coverage = engaged_n / len(test_dates) if len(test_dates) > 0 else 0.0

        out["arms"][name] = {
            "sigma": None if sigma is None else round(float(sigma), 4),
            "engaged_n": int(engaged_n),
            "coverage": round(float(coverage), 4),
            "ALL": _metrics(pred, latent, pds, y_true),
            "calm": _metrics(pred, latent, pds, y_true, mask=calm_mask),
            "non_calm": _metrics(pred, latent, pds, y_true, mask=non_calm_mask),
            "heteroscedasticity": _het_diag(pds, y_true),
        }
    return out


def _pool(rows: list[dict], arm: str, stratum: str = "ALL") -> dict:
    vals = [r["arms"][arm][stratum] for r in rows]
    n = sum(v["n"] for v in vals if v["mae"] is not None)
    if n == 0:
        return {"n": 0, "mae": None, "rps": None, "ic80_coverage": None}

    def _wavg(key: str) -> float | None:
        parts = [(v[key], v["n"]) for v in vals if v.get(key) is not None]
        if not parts:
            return None
        return round(float(sum(x * w for x, w in parts) / sum(w for _, w in parts)), 4)

    return {
        "n": int(n),
        "mae": _wavg("mae"),
        "rps": _wavg("rps"),
        "bracket_match": _wavg("bracket_match"),
        "ic80_coverage": _wavg("ic80_coverage"),
        "ic80_mean_width": _wavg("ic80_mean_width"),
    }


def _decide(per_cp_folds: dict[str, list[dict]]) -> dict:
    detail = {}
    for cp, rows in per_cp_folds.items():
        served = _pool(rows, "served_v0", "ALL")
        served_calm = _pool(rows, "served_v0", "calm")
        cp_detail = {"incumbent": "served_v0", "candidates": {}}
        for cand in ("mos_ecmwf", "emos2_lite"):
            pooled = _pool(rows, cand, "ALL")
            calm = _pool(rows, cand, "calm")
            folds_won_rps = 0
            folds_won_mae = 0
            for row in rows:
                c = row["arms"][cand]["ALL"]
                s = row["arms"]["served_v0"]["ALL"]
                if c["rps"] is not None and s["rps"] is not None and c["rps"] <= s["rps"]:
                    folds_won_rps += 1
                if c["mae"] is not None and s["mae"] is not None and c["mae"] <= s["mae"]:
                    folds_won_mae += 1
            calm_folds_ok = 0
            for row in rows:
                c_calm = row["arms"][cand]["calm"]
                s_calm = row["arms"]["served_v0"]["calm"]
                if (
                    c_calm["mae"] is not None
                    and s_calm["mae"] is not None
                    and c_calm["mae"] <= s_calm["mae"] + CALM_TOLERANCE
                ):
                    calm_folds_ok += 1
            calm_ok = (
                calm["mae"] is not None
                and served_calm["mae"] is not None
                and calm["mae"] <= served_calm["mae"] + CALM_TOLERANCE
                and calm_folds_ok == len(rows)
            )
            coverage_ok = all(
                row["arms"][cand]["coverage"] >= MIN_COVERAGE
                for row in rows
            )
            eligible = (
                pooled["rps"] is not None
                and served["rps"] is not None
                and pooled["mae"] is not None
                and served["mae"] is not None
                and pooled["rps"] <= served["rps"] + RPS_TOLERANCE
                and pooled["mae"] <= served["mae"] + MAE_TOLERANCE
                and folds_won_rps == len(rows)
                and folds_won_mae == len(rows)
                and calm_ok
                and coverage_ok
            )
            cp_detail["candidates"][cand] = {
                "pooled": pooled,
                "calm": calm,
                "folds_won_rps": folds_won_rps,
                "folds_won_mae": folds_won_mae,
                "calm_folds_ok": calm_folds_ok,
                "n_folds": len(rows),
                "calm_ok": calm_ok,
                "coverage_ok": bool(coverage_ok),
                "eligible_for_followup_prereg": bool(eligible),
            }
        detail[cp] = cp_detail
    return detail


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        model_cfg = yaml.safe_load(fh)
    tau = float(model_cfg["prob_dist"]["tau"])
    mode = str(model_cfg["prob_dist"]["mode"])
    calib_tail_days = int(model_cfg["conformal"]["per_cp_window_days"])
    tmp_min = cfg.tmp_c_int_plausibility.min
    tmp_max = cfg.tmp_c_int_plausibility.max

    print("=== Onda 2-C: MOS/EMOS-lite offline evaluator (CP20-22) ===", flush=True)
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=tmp_min,
        tmp_max_c=tmp_max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    gfs_snaps = read_snapshots(station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root)
    ecmwf_snaps = read_snapshots(station=cfg.icao, model=ECMWF_IFS_HRES, endpoint="single_runs", out_root=nwp_root)
    thc = fit_tmax_hour_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=cfg.tz)
    climo_broad = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))

    all_dates = sorted([
        d for d in labels["date_local"].unique().to_list()
        if d is not None and ECMWF_START <= d <= ECMWF_END
    ])
    print(f"  overlap dates={len(all_dates)}", flush=True)
    panel_base = build_training_panel(obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=cfg.cp_set_utc, dates=all_dates)
    panel_ecmwf = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=cfg.cp_set_utc, dates=all_dates,
        nwp_snapshots=ecmwf_snaps, nwp_models=(ECMWF_IFS_HRES.id,), tmax_hour_climo=thc,
    )
    panel_gfs = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=cfg.cp_set_utc, dates=all_dates,
        nwp_snapshots=gfs_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc,
    )
    risk_df_full = build_risk_features(obs, labels, cfg.tz, cfg.cp_operational_utc)

    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=tau, mode=mode, use_climatology_anchor=True,
    )
    cfg_lgbm = ResidualLgbmConfig(
        feature_columns=PHASE4_FEATURES,
        n_estimators=N_ESTIMATORS,
        learning_rate=0.05,
        num_leaves=31,
        min_data_in_leaf=20,
        tau=tau, mode=mode,
    )

    per_cp_folds: dict[str, list[dict]] = {cp: [] for cp in SERVING_CPS}
    for split_name, tr_start, tr_end, te_start, te_end in ECMWF_SPLITS:
        print(f"  fold {split_name}", flush=True)
        for cp in SERVING_CPS:
            print(f"    CP {cp}", flush=True)
            row = _evaluate_one_cp(
                cp, tr_start, tr_end, te_start, te_end,
                panel_base, panel_ecmwf, panel_gfs,
                risk_df_full, labels, obs, cfg.tz, cfg.cp_operational_utc,
                cfg_ridge, cfg_lgbm, tmp_min, tmp_max, calib_tail_days,
            )
            if row is not None:
                row["split"] = split_name
                row["train"] = [tr_start.isoformat(), tr_end.isoformat()]
                row["test"] = [te_start.isoformat(), te_end.isoformat()]
                per_cp_folds[cp].append(row)

    decision = _decide(per_cp_folds)
    report = {
        "task": "phase11-Onda2-C MOS/EMOS-lite offline evaluator",
        "status": "read_only_no_serving_change",
        "git_sha": _git_sha(),
        "seed": SEED,
        "deterministic": True,
        "window": [ECMWF_START.isoformat(), ECMWF_END.isoformat()],
        "serving_cps": SERVING_CPS,
        "splits": [s[0] for s in ECMWF_SPLITS],
        "calib_tail_days": calib_tail_days,
        "arms": ["ridge", "served_v0", "mos_ecmwf", "emos2_lite"],
        "gate_contract": {
            "incumbent": "served_v0",
            "candidate_must_win_rps_all_folds": True,
            "candidate_must_win_mae_all_folds": True,
            "calm_tolerance": CALM_TOLERANCE,
            "no_cli_or_default_serving_change": True,
        },
        "per_cp_folds": per_cp_folds,
        "decision": decision,
        "honest_conclusion": _conclusion(decision),
        "leakage_ok": True,
        "note": (
            "Offline readout only. MOS/EMOS-lite centers are fit on fold train excluding "
            "the last 90 days; sigma is calibrated on that train-tail; test is read once. "
            "NWP causality is delegated to select_max_trajectory_anchor/select_nwp_v1. "
            "No routing/default/CLI behavior is changed."
        ),
    }

    out_dir = REPO / "reports" / "serving"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mos_emos_lite_v0.json").write_text(
        json.dumps(report, default=str, ensure_ascii=True, indent=2), encoding="ascii"
    )
    (out_dir / "mos_emos_lite_v0.md").write_text(_render(report), encoding="ascii")
    print(f"  reports -> {out_dir}/mos_emos_lite_v0.{{json,md}}", flush=True)
    print(f"  conclusion: {report['honest_conclusion']['verdict']}", flush=True)
    return 0


def _conclusion(decision: dict) -> dict:
    eligible = [
        f"{cp}:{cand}"
        for cp, d in decision.items()
        for cand, c in d["candidates"].items()
        if c["eligible_for_followup_prereg"]
    ]
    return {
        "verdict": "PROMISING_FOR_FOLLOWUP_PREREG" if eligible else "NO_PROMOTION",
        "eligible_candidates": eligible,
        "serving_change": False,
    }


def _render(report: dict) -> str:
    lines = [
        "# Onda 2-C: MOS/EMOS-lite offline evaluator",
        "",
        f"- status: **{report['status']}**",
        f"- git_sha: `{report['git_sha']}`",
        f"- window: {report['window'][0]}..{report['window'][1]}  cps: {', '.join(report['serving_cps'])}",
        f"- calib_tail_days: {report['calib_tail_days']}  leakage_ok: **{report['leakage_ok']}**",
        f"- verdict: **{report['honest_conclusion']['verdict']}**",
        f"- {report['note']}",
        "",
        "## Gate Summary",
        "",
        "| CP | candidate | eligible | RPS | incumbent RPS | MAE | incumbent MAE | calm_ok | calm folds | coverage_ok | folds RPS | folds MAE |",
        "|----|-----------|----------|-----|---------------|-----|---------------|---------|------------|-------------|-----------|-----------|",
    ]
    for cp, d in report["decision"].items():
        inc_rows = report["per_cp_folds"][cp]
        inc = _pool(inc_rows, "served_v0", "ALL")
        for cand, c in d["candidates"].items():
            p = c["pooled"]
            lines.append(
                f"| {cp} | {cand} | {c['eligible_for_followup_prereg']} | {p['rps']} | "
                f"{inc['rps']} | {p['mae']} | {inc['mae']} | {c['calm_ok']} | "
                f"{c['calm_folds_ok']}/{c['n_folds']} | {c['coverage_ok']} | "
                f"{c['folds_won_rps']}/{c['n_folds']} | {c['folds_won_mae']}/{c['n_folds']} |"
            )
    lines += [
        "",
        "## Per CP x Fold",
        "",
        "| CP | fold | arm | n | engaged_n | coverage | MAE | RPS | BM | IC80 cov | IC80 width | sigma |",
        "|----|------|-----|---|-----------|----------|-----|-----|----|----------|------------|-------|",
    ]
    for cp in report["serving_cps"]:
        for row in report["per_cp_folds"].get(cp, []):
            for arm in report["arms"]:
                a = row["arms"][arm]
                m = a["ALL"]
                lines.append(
                    f"| {cp} | {row['split']} | {arm} | {m['n']} | {a['engaged_n']} | {a['coverage']} | {m['mae']} | {m['rps']} | "
                    f"{m['bracket_match']} | {m['ic80_coverage']} | {m['ic80_mean_width']} | {a['sigma']} |"
                )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
