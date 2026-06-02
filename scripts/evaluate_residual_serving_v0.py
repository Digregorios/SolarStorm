"""Onda 2 Track B (B2): offline backtest of the EXACT ``--serve-residuals`` decision.

The CLI serving path (``core/cli/residual_serving.py``) was shipped behind the flag
in B1 with full telemetry, but a path that exists is not a path that is measured.
This script backtests the SAME per-day serve decision over the ECMWF overlap folds
(CP20-22 only) so the reviewer's gate items become real numbers, not assertions:

* **Real fallback rate** = test day-CPs with NO causal NWP anchor / all test day-CPs
  (per CP + pooled). A day is "served" if EITHER model has a causal max-trajectory
  anchor in the panel (ECMWF preferred, GFS otherwise) -- exactly what the router
  keys off at CP20-22 -- else it deterministically falls back to Ridge. Cross-checked
  against ``1 - any_causal`` from the Onda 2-A audit (different windows: this is the
  2025 test folds, the audit is the full 2021-2025 window -- both recorded, not asserted equal).
* **Calm guard preserved:** served-arm calm-stratum MAE vs Ridge calm MAE, same
  ex-ante ``_build_regime_masks`` strata as the candidate matrix; ``calm_ok`` per CP
  with the matrix's ``+0.05`` tolerance.
* **Leakage:** every panel anchor is built through ``select_max_trajectory_anchor`` ->
  ``select_nwp_v1`` (``run_time <= cp - safety``); a violation RAISES at panel-build
  time, so a clean run IS the gate (same delegation as the permanent leakage test).

Anti-gaming: eval == serving (same PHASE4_FEATURES, max-trajectory anchor,
n_estimators=500, causal per-split climo override); thresholds pre-stated; the
fallback rate is descriptive (it is whatever the data is), not tuned. Backtest entry
point only -- NOT run inside pytest (mirrors the candidate-matrix eval).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

# Make the repo root importable so ``scripts.evaluate_serving_candidate_matrix``
# resolves when this file is run directly (py -3 scripts/...), not only under pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import polars as pl
import yaml

from core.baselines.climatology import fit_climatology, fit_tmax_hour_climatology
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.metrics import mae
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import build_features as build_risk_features
from core.models.residual_lgbm import (
    ResidualLgbmConfig,
    fit_residual_lgbm,
    predict_latent as predict_lgbm_latent,
)
from core.models.ridge_band import (
    RidgeBandConfig,
    fit_ridge_band,
    predict_latent as predict_ridge_latent,
)
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

# Serving fires only at CP20-22 (NWP_LEAD_CPS); CP23 is conservative Ridge.
SERVING_CPS = ["20:00", "21:00", "22:00"]
CALM_TOLERANCE = 0.05  # pre-stated: served_calm_mae <= ridge_calm_mae + tol (matches matrix)
AUDIT_ANY_CAUSAL_FALLBACK = 0.0444  # 1 - 0.9556 from reports/live_nwp (full 2021-2025 window)
_CLIM_IDX = list(FEATURE_COLUMNS).index("clim_tmax_c_dec")


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _clim_col(df, climo):
    return np.array([float(climo.tmax_dec_for(d)) for d in df["date_local"].to_list()])


def _residual_preds_by_date(tr_ok, te_ok, climo, cfg_lgbm):
    """Train residual on anchor-present train rows, predict on anchor-present test rows.

    Returns ``{date_local: pred_int}`` (empty if the fold has < 100 train anchors).
    Mirrors the candidate matrix EXACTLY: PHASE4_FEATURES, causal-climo override of
    ``clim_tmax_c_dec``, max-trajectory anchor, n_estimators=500.
    """
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
    ints = [Q(float(v)) for v in latent]
    return {d: int(v) for d, v in zip(te_ok["date_local"].to_list(), ints)}


def _serve_one_cp(
    cp, tr_start, tr_end, te_start, te_end,
    panel_base, panel_ecmwf, panel_gfs,
    risk_df_full, labels, obs, tz, cp_op,
    cfg_ridge, cfg_lgbm,
):
    """Backtest the serve decision for one CP in one ECMWF fold.

    Decision per TEST day: serve ecmwf_residual if it has a causal anchor; else
    gfs_residual if it has one; else deterministic Ridge fallback. Ridge covers
    every test day, so the served set == the base test set (same rows for MAE)."""
    def _split(panel):
        sub = panel.filter(panel["cp"] == cp)
        tr = sub.filter((sub["date_local"] >= tr_start) & (sub["date_local"] <= tr_end))
        te = sub.filter((sub["date_local"] >= te_start) & (sub["date_local"] <= te_end))
        return tr, te

    tr_base, te_base = _split(panel_base)
    tr_ecmwf, te_ecmwf = _split(panel_ecmwf)
    tr_gfs, te_gfs = _split(panel_gfs)
    if te_base.height < 20:
        return None

    tr_ecmwf_ok = tr_ecmwf.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    te_ecmwf_ok = te_ecmwf.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    tr_gfs_ok = tr_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    te_gfs_ok = te_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())

    # Per-split causal climatology (train-only), same as the matrix.
    climo_labels = labels.filter(pl.col("date_local") <= tr_end).select(
        ["date_local", "tmax_int", "day_complete"]
    )
    climo = fit_climatology(climo_labels, train_start=date(2020, 1, 1), train_end=tr_end)

    # Ridge over the full base test set (the fallback arm, covers every day).
    X_tr_base, y_tr_base = _arrays(tr_base, tuple(FEATURE_COLUMNS))
    clim_tr = _clim_col(tr_base, climo)
    X_te_base, y_te = _arrays(te_base, tuple(FEATURE_COLUMNS))
    clim_te = _clim_col(te_base, climo)
    X_tr_base[:, _CLIM_IDX] = clim_tr
    X_te_base[:, _CLIM_IDX] = clim_te
    ridge = fit_ridge_band(X_tr_base, y_tr_base, config=cfg_ridge, clim_train=clim_tr)
    ridge_int = np.array([Q(float(v)) for v in predict_ridge_latent(ridge, X_te_base, clim=clim_te)], dtype=int)

    test_dates = te_base["date_local"].to_list()
    ecmwf_by_date = _residual_preds_by_date(tr_ecmwf_ok, te_ecmwf_ok, climo, cfg_lgbm)
    gfs_by_date = _residual_preds_by_date(tr_gfs_ok, te_gfs_ok, climo, cfg_lgbm)

    served_int = np.copy(ridge_int)
    n_ecmwf = n_gfs = n_fallback = 0
    for i, d in enumerate(test_dates):
        if d in ecmwf_by_date:
            served_int[i] = ecmwf_by_date[d]
            n_ecmwf += 1
        elif d in gfs_by_date:
            served_int[i] = gfs_by_date[d]
            n_gfs += 1
        else:
            n_fallback += 1  # served_int already == ridge_int[i]

    n_test = len(test_dates)
    # Calm stratum (ex-ante, train-only thresholds) -- same helper as the matrix.
    non_calm_mask, _ = _build_regime_masks(
        tr_start, tr_end, test_dates, test_dates, risk_df_full, obs, labels, tz, cp_op,
    )
    calm_mask = ~non_calm_mask

    def _mae(pred, mask=None):
        if mask is None:
            return round(float(mae(pred, y_te)), 4)
        if int(mask.sum()) < 5:
            return None
        return round(float(mae(pred[mask], y_te[mask])), 4)

    served_calm = _mae(served_int, calm_mask)
    ridge_calm = _mae(ridge_int, calm_mask)
    calm_ok = (
        served_calm is None or ridge_calm is None
        or served_calm <= ridge_calm + CALM_TOLERANCE
    )

    return {
        "n_test": n_test,
        "n_served_ecmwf": n_ecmwf,
        "n_served_gfs": n_gfs,
        "n_fallback_ridge": n_fallback,
        "fallback_rate": round(n_fallback / n_test, 4) if n_test else None,
        "served_mae_all": _mae(served_int),
        "ridge_mae_all": _mae(ridge_int),
        "served_mae_calm": served_calm,
        "ridge_mae_calm": ridge_calm,
        "n_calm": int(calm_mask.sum()),
        "calm_ok": bool(calm_ok),
    }


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        model_cfg = yaml.safe_load(fh)
    tau = float(model_cfg["prob_dist"]["tau"])
    mode = str(model_cfg["prob_dist"]["mode"])
    tz = cfg.tz
    cp_op = cfg.cp_operational_utc

    print("=== Onda 2-B: residual serving v0 backtest (CP20-22, ECMWF folds) ===")
    print(f"  seed={SEED} n_estimators={N_ESTIMATORS} calm_tol={CALM_TOLERANCE}")

    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=tz, cp_set_utc=cfg.cp_set_utc)

    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    gfs_snaps = read_snapshots(station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root)
    ecmwf_snaps = read_snapshots(station=cfg.icao, model=ECMWF_IFS_HRES, endpoint="single_runs", out_root=nwp_root)

    thc = fit_tmax_hour_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=tz)
    climo_broad = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))

    all_dates = sorted([
        d for d in labels["date_local"].unique().to_list()
        if d is not None and ECMWF_START <= d <= ECMWF_END
    ])
    print(f"  overlap dates: {len(all_dates)}")

    panel_base = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cfg.cp_set_utc, dates=all_dates)
    panel_ecmwf = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cfg.cp_set_utc, dates=all_dates,
                                       nwp_snapshots=ecmwf_snaps, nwp_models=(ECMWF_IFS_HRES.id,), tmax_hour_climo=thc)
    panel_gfs = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cfg.cp_set_utc, dates=all_dates,
                                     nwp_snapshots=gfs_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc)
    risk_df_full = build_risk_features(obs, labels, tz, cp_op)

    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=tau, mode=mode, use_climatology_anchor=True,
    )
    cfg_lgbm = ResidualLgbmConfig(
        feature_columns=PHASE4_FEATURES, n_estimators=N_ESTIMATORS,
        learning_rate=0.05, num_leaves=31, min_data_in_leaf=20, tau=tau, mode=mode,
    )

    per_cp_folds: dict[str, list] = {cp: [] for cp in SERVING_CPS}
    for split_name, tr_start, tr_end, te_start, te_end in ECMWF_SPLITS:
        print(f"  fold {split_name}")
        for cp in SERVING_CPS:
            res = _serve_one_cp(
                cp, tr_start, tr_end, te_start, te_end,
                panel_base, panel_ecmwf, panel_gfs,
                risk_df_full, labels, obs, tz, cp_op,
                cfg_ridge, cfg_lgbm,
            )
            if res is not None:
                res["split"] = split_name
                per_cp_folds[cp].append(res)

    # Pool across folds per CP, then overall.
    def _pool(rows):
        n = sum(r["n_test"] for r in rows)
        fb = sum(r["n_fallback_ridge"] for r in rows)
        ne = sum(r["n_served_ecmwf"] for r in rows)
        ng = sum(r["n_served_gfs"] for r in rows)
        calm_ok = all(r["calm_ok"] for r in rows) if rows else None
        return {
            "n_test": n, "n_served_ecmwf": ne, "n_served_gfs": ng, "n_fallback_ridge": fb,
            "fallback_rate": round(fb / n, 4) if n else None,
            "calm_ok": calm_ok, "n_folds": len(rows),
        }

    per_cp_pooled = {cp: _pool(rows) for cp, rows in per_cp_folds.items() if rows}
    all_rows = [r for rows in per_cp_folds.values() for r in rows]
    overall = _pool(all_rows)
    leakage_ok = True  # delegated to select_nwp_v1 at panel-build; a violation RAISES there.

    report = {
        "task": "phase11-Onda2-B (B2 serving report)",
        "seed": SEED,
        "deterministic": True,
        "num_threads": 1,
        "n_estimators": N_ESTIMATORS,
        "calm_tolerance": CALM_TOLERANCE,
        "git_sha": _git_sha(),
        "window": [ECMWF_START.isoformat(), ECMWF_END.isoformat()],
        "serving_cps": SERVING_CPS,
        "per_cp_folds": per_cp_folds,
        "per_cp_pooled": per_cp_pooled,
        "overall": overall,
        "leakage_ok": leakage_ok,
        "fallback_cross_check": {
            "measured_overall_fallback_rate": overall["fallback_rate"],
            "audit_any_causal_fallback_rate": AUDIT_ANY_CAUSAL_FALLBACK,
            "note": (
                "Windows DIFFER: this backtest measures the ECMWF overlap TEST folds "
                "(2025), the audit measures the full 2021-2025 window. Both recorded; "
                "NOT asserted equal -- ECMWF coverage is much higher post-2024."
            ),
        },
        "note": (
            "Backtests the EXACT --serve-residuals decision (ecmwf_residual preferred, "
            "gfs_residual otherwise, deterministic Ridge fallback) at CP20-22 over the "
            "ECMWF folds. fallback_rate is DESCRIPTIVE (whatever the data is), not tuned. "
            "calm_ok uses the same ex-ante strata + 0.05 tolerance as the candidate matrix. "
            "Leakage delegated to the frozen select_nwp_v1 (run_time <= cp - safety); a "
            "violation raises at panel build, so a clean run is the gate. eval == serving: "
            "same PHASE4_FEATURES, max-trajectory anchor, n_estimators, causal climo override."
        ),
    }

    out_dir = REPO / "reports" / "serving"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "residual_serving_v0.json").write_text(
        json.dumps(report, default=str, ensure_ascii=True, indent=2), encoding="ascii"
    )
    (out_dir / "residual_serving_v0.md").write_text(_render(report), encoding="ascii")

    print("\n=== OVERALL ===")
    print(f"  served ecmwf={overall['n_served_ecmwf']} gfs={overall['n_served_gfs']} "
          f"fallback={overall['n_fallback_ridge']}/{overall['n_test']} "
          f"rate={overall['fallback_rate']} calm_ok={overall['calm_ok']} leakage_ok={leakage_ok}")
    for cp in SERVING_CPS:
        p = per_cp_pooled.get(cp)
        if p:
            print(f"  {cp}: fb_rate={p['fallback_rate']} calm_ok={p['calm_ok']} (folds={p['n_folds']})")
    print(f"  reports -> {out_dir}/residual_serving_v0.{{json,md}}")
    return 0


def _render(r: dict) -> str:
    L = [
        "# Onda 2-B: residual serving v0 backtest (CP20-22)",
        "",
        f"- git_sha: `{r['git_sha']}`  window: {r['window'][0]}..{r['window'][1]} (ECMWF folds)",
        f"- seed: {r['seed']}  n_estimators: {r['n_estimators']}  calm_tol: {r['calm_tolerance']}  "
        f"leakage_ok: **{r['leakage_ok']}**",
        f"- {r['note']}",
        "",
        "## Overall (pooled over CP20-22 x folds)",
        "",
        f"- served ecmwf: {r['overall']['n_served_ecmwf']}  served gfs: {r['overall']['n_served_gfs']}  "
        f"ridge fallback: {r['overall']['n_fallback_ridge']} / {r['overall']['n_test']}",
        f"- **fallback_rate: {r['overall']['fallback_rate']}**  calm_ok (all CPs/folds): "
        f"**{r['overall']['calm_ok']}**",
        "",
        "### Fallback cross-check vs Onda 2-A audit",
        "",
        f"- measured (2025 test folds): {r['fallback_cross_check']['measured_overall_fallback_rate']}",
        f"- audit any_causal (2021-2025 full): {r['fallback_cross_check']['audit_any_causal_fallback_rate']}",
        f"- {r['fallback_cross_check']['note']}",
        "",
        "## Per CP (pooled)",
        "",
        "| CP | fallback_rate | served ecmwf | served gfs | ridge fallback | n_test | calm_ok |",
        "|----|---------------|--------------|------------|----------------|--------|---------|",
    ]
    for cp in r["serving_cps"]:
        p = r["per_cp_pooled"].get(cp)
        if not p:
            continue
        L.append(
            f"| {cp} | {p['fallback_rate']} | {p['n_served_ecmwf']} | {p['n_served_gfs']} | "
            f"{p['n_fallback_ridge']} | {p['n_test']} | {p['calm_ok']} |"
        )
    L += ["", "## Per CP x fold (MAE: served vs ridge, ALL + calm)", "",
          "| CP | fold | fb_rate | served_mae | ridge_mae | served_calm | ridge_calm | calm_ok |",
          "|----|------|---------|------------|-----------|-------------|------------|---------|"]
    for cp in r["serving_cps"]:
        for f in r["per_cp_folds"].get(cp, []):
            L.append(
                f"| {cp} | {f['split']} | {f['fallback_rate']} | {f['served_mae_all']} | "
                f"{f['ridge_mae_all']} | {f['served_mae_calm']} | {f['ridge_mae_calm']} | {f['calm_ok']} |"
            )
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
