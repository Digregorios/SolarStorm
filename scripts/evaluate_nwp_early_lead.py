"""T-10-2: NWP early-lead point gain consolidation in degC.

Reuses the Phase-4 panel + residual LGBM to compare Ridge-only vs
Ridge+NWP-residual per CP (20/21/22/23) across walk-forward splits 2023/24/25.
Reports MAE, RMSE, bracket-match, RPS per CP.

GATE: GO if NWP improves MAE OR RPS at CP20-22 in >=2/3 splits AND does not
regress CP23 MAE by >0.02 degC.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from core.baselines.climatology import (
    Climatology,
    fit_climatology,
    fit_tmax_hour_climatology,
)
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.cv import expanding_walk_forward_splits
from core.eval.metrics import bracket_match_at_p50, mae, rmse, rps
from core.features.training_panel import (
    FEATURE_COLUMNS,
    NWP_FEATURE_COLUMNS,
    build_training_panel,
)
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots
from core.ingest.nwp_client import NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.loss import latent_to_prob_dist
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

REPO = Path(__file__).resolve().parents[1]
PHASE4_FEATURES = tuple(FEATURE_COLUMNS) + tuple(NWP_FEATURE_COLUMNS)
SEED = 42


def _rebuild_climo_features(panel: pl.DataFrame, climo: Climatology) -> pl.DataFrame:
    dates = panel["date_local"].to_list()
    clim_dec = [float(climo.tmax_dec_for(d)) for d in dates]
    return panel.with_columns(pl.Series("clim_tmax_c_dec", clim_dec, dtype=pl.Float64))


def _arrays(panel: pl.DataFrame, columns: tuple[str, ...]):
    X = np.column_stack([panel[c].to_numpy().astype(float) for c in columns])
    y_int = panel["target_tmax_int"].to_numpy().astype(int)
    return X, y_int


def _compute_rps(latents, climo, dates, y_test, tau, mode, tmp_min, tmp_max):
    scores = []
    for v, d, t in zip(latents, dates, y_test):
        p10, p90 = climo.percentiles_for(d)
        sk = support_K(p10, p90, tmp_min=tmp_min, tmp_max=tmp_max)
        pd = latent_to_prob_dist(float(v), sk, tau=tau, mode=mode)
        scores.append(rps(pd, int(t)))
    return float(np.mean(scores))


def evaluate_cp(
    panel: pl.DataFrame,
    cp: str,
    train_start: date,
    train_end: date,
    test_start: date,
    test_end: date,
    cfg_ridge: RidgeBandConfig,
    cfg_lgbm: ResidualLgbmConfig,
    tau: float,
    mode: str,
    tmp_min: int,
    tmp_max: int,
) -> dict | None:
    sub = panel.filter(panel["cp"] == cp)
    train = sub.filter(
        (sub["date_local"] >= train_start) & (sub["date_local"] <= train_end)
    )
    test = sub.filter(
        (sub["date_local"] >= test_start) & (sub["date_local"] <= test_end)
    )
    # Keep only rows with valid NWP anchor
    train_ok = train.filter(train["nwp_t2m_maxtraj_c"].is_not_null())
    test_ok = test.filter(test["nwp_t2m_maxtraj_c"].is_not_null())
    if train_ok.height < 100 or test_ok.height < 30:
        return None

    # Causal climatology on train only
    train_labels = (
        train_ok.select(["date_local", "target_tmax_int"])
        .rename({"target_tmax_int": "tmax_int"})
        .with_columns(pl.lit(True).alias("day_complete"))
    )
    climo = fit_climatology(train_labels, train_start=train_start, train_end=train_end)
    train_ok = _rebuild_climo_features(train_ok, climo)
    test_ok = _rebuild_climo_features(test_ok, climo)

    clim_train = np.array([float(climo.tmax_dec_for(d)) for d in train_ok["date_local"].to_list()])
    clim_test = np.array([float(climo.tmax_dec_for(d)) for d in test_ok["date_local"].to_list()])

    X_ridge_train, y_train = _arrays(train_ok, tuple(FEATURE_COLUMNS))
    X_ridge_test, y_test = _arrays(test_ok, tuple(FEATURE_COLUMNS))
    X_lgbm_train, _ = _arrays(train_ok, PHASE4_FEATURES)
    X_lgbm_test, _ = _arrays(test_ok, PHASE4_FEATURES)
    nwp_anchor_train = train_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    nwp_anchor_test = test_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)

    # Ridge-only
    ridge = fit_ridge_band(X_ridge_train, y_train, config=cfg_ridge, clim_train=clim_train)
    ridge_latent = predict_ridge_latent(ridge, X_ridge_test, clim=clim_test)
    ridge_int = np.array([Q(float(v)) for v in ridge_latent], dtype=int)

    # Ridge+NWP residual LGBM
    lgbm = fit_residual_lgbm(X_lgbm_train, y_train, nwp_anchor_train, config=cfg_lgbm)
    lgbm_latent = predict_lgbm_latent(lgbm, X_lgbm_test, nwp_anchor_test)
    lgbm_int = np.array([Q(float(v)) for v in lgbm_latent], dtype=int)

    y_f = y_test.astype(float)
    ridge_mae = mae(ridge_latent, y_f)
    ridge_rmse = rmse(ridge_latent, y_f)
    lgbm_mae = mae(lgbm_latent, y_f)
    lgbm_rmse = rmse(lgbm_latent, y_f)
    ridge_bm = bracket_match_at_p50(ridge_int, y_test)
    lgbm_bm = bracket_match_at_p50(lgbm_int, y_test)

    test_dates = test_ok["date_local"].to_list()
    ridge_rps = _compute_rps(ridge_latent, climo, test_dates, y_test, tau, mode, tmp_min, tmp_max)
    lgbm_rps = _compute_rps(lgbm_latent, climo, test_dates, y_test, tau, mode, tmp_min, tmp_max)

    return {
        "cp": cp,
        "n_train": int(train_ok.height),
        "n_test": int(test_ok.height),
        "ridge_mae": round(ridge_mae, 4),
        "ridge_rmse": round(ridge_rmse, 4),
        "ridge_bm": round(ridge_bm, 4),
        "ridge_rps": round(ridge_rps, 4),
        "nwp_mae": round(lgbm_mae, 4),
        "nwp_rmse": round(lgbm_rmse, 4),
        "nwp_bm": round(lgbm_bm, 4),
        "nwp_rps": round(lgbm_rps, 4),
        "d_mae": round(lgbm_mae - ridge_mae, 4),
        "d_rmse": round(lgbm_rmse - ridge_rmse, 4),
        "d_bm": round(lgbm_bm - ridge_bm, 4),
        "d_rps": round(lgbm_rps - ridge_rps, 4),
    }


def main() -> int:
    np.random.seed(SEED)
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    tau = float(mcfg["prob_dist"]["tau"])
    mode = str(mcfg["prob_dist"]["mode"])

    print("[1/4] Loading observations + labels ...")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    print("[2/4] Climatology + NWP snapshots ...")
    climo = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    nwp_snaps = read_snapshots(
        station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root
    )
    thc = fit_tmax_hour_climatology(
        labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=cfg.tz
    )

    print("[3/4] Building panel ...")
    panel = build_training_panel(
        obs, labels, climo=climo, tz_name=cfg.tz, cp_set=cfg.cp_set_utc,
        nwp_snapshots=nwp_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc,
    )
    print(f"  panel rows={panel.height}")

    splits = expanding_walk_forward_splits(
        history_start=date(2020, 1, 1),
        test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)],
        test_length_days=365,
    )
    cp_set = cfg.cp_set_utc  # ["20:00","21:00","22:00","23:00"]

    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=tau, mode=mode, use_climatology_anchor=True,
    )
    cfg_lgbm = ResidualLgbmConfig(
        feature_columns=PHASE4_FEATURES,
        n_estimators=500, learning_rate=0.05, num_leaves=31,
        min_data_in_leaf=20, tau=tau, mode=mode,
    )

    print("[4/4] Evaluating per CP x split ...")
    all_results: list[dict] = []
    for s in splits:
        for cp in cp_set:
            r = evaluate_cp(
                panel, cp, s.train_start, s.train_end, s.test_start, s.test_end,
                cfg_ridge, cfg_lgbm, tau, mode,
                cfg.tmp_c_int_plausibility.min, cfg.tmp_c_int_plausibility.max,
            )
            if r is None:
                print(f"  {s.name} CP={cp}: thin coverage, skipped")
                all_results.append({
                    "split": s.name, "cp": cp, "thin_coverage": True,
                })
            else:
                print(f"  {s.name} CP={cp}: dMAE={r['d_mae']:+.4f} dBM={r['d_bm']:+.4f}")
                all_results.append({"split": s.name, "thin_coverage": False, **r})

    # --- GATE logic ---
    early_cps = ["20:00", "21:00", "22:00"]
    split_names = [s.name for s in splits]

    # Per split: does NWP improve MAE OR RPS at early CPs?
    splits_improved = 0
    for sn in split_names:
        early = [r for r in all_results if r["split"] == sn
                 and r.get("cp") in early_cps and not r.get("thin_coverage")]
        if not early:
            continue
        mae_improved = all(r["d_mae"] < 0 for r in early)
        rps_improved = all(r["d_rps"] < 0 for r in early)
        if mae_improved or rps_improved:
            splits_improved += 1

    # CP23 non-regression
    cp23_results = [r for r in all_results if r.get("cp") == "23:00"
                    and not r.get("thin_coverage")]
    cp23_regresses = any(r["d_mae"] > 0.02 for r in cp23_results)

    go = (splits_improved >= 2) and (not cp23_regresses)
    verdict = "GO" if go else "KILL"

    # Reconcile bracket-match with phase4.md
    # Phase4 horizon curve uses LGBM(obs+NWP) vs LGBM(obs-only) as baseline;
    # we use Ridge as baseline. Both should show positive NWP delta at early CPs
    # and a degradation pattern toward CP23. Reconciliation = same sign pattern.
    phase4_bm_positive = True  # phase4 showed +0.11/+0.10/+0.13 at 20Z (all positive)
    our_bm_20 = [r["d_bm"] for r in all_results
                 if r.get("cp") == "20:00" and not r.get("thin_coverage")]
    bm_reconciles = True
    if our_bm_20:
        # All early-CP BM deltas should be positive (same direction as phase4)
        early_bm = [r["d_bm"] for r in all_results
                    if r.get("cp") in early_cps and not r.get("thin_coverage")]
        if not all(d > 0 for d in early_bm):
            bm_reconciles = False

    # Check if degC contradicts BM (BM up but MAE worse)
    degc_contradicts_bm = False
    for r in all_results:
        if r.get("thin_coverage"):
            continue
        if r.get("d_bm", 0) > 0.02 and r.get("d_mae", 0) > 0.01:
            degc_contradicts_bm = True

    # --- Build output ---
    out_json = {
        "task": "T-10-2 nwp_early_lead_point_gain",
        "verdict": verdict,
        "gate": {
            "splits_improved_early_cps": splits_improved,
            "required": 2,
            "cp23_regresses": cp23_regresses,
            "go": go,
        },
        "bm_reconciles_with_phase4": bm_reconciles,
        "degc_contradicts_bm": degc_contradicts_bm,
        "results": all_results,
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nwp_early_lead_point_gain.json").write_text(
        json.dumps(out_json, default=str, ensure_ascii=True, indent=2), encoding="ascii"
    )

    # Markdown report
    md = _render_md(all_results, verdict, go, splits_improved, cp23_regresses,
                    bm_reconciles, degc_contradicts_bm)
    (out_dir / "nwp_early_lead_point_gain.md").write_text(md, encoding="ascii")

    print(f"\n[VERDICT] {verdict}")
    print(f"  splits_improved (early CPs): {splits_improved}/3")
    print(f"  CP23 regresses: {cp23_regresses}")
    print(f"  BM reconciles with phase4: {bm_reconciles}")
    print(f"  degC contradicts BM: {degc_contradicts_bm}")
    print(f"  reports written: nwp_early_lead_point_gain.{{md,json}}")
    return 0


def _render_md(results, verdict, go, splits_improved, cp23_regresses,
               bm_reconciles, degc_contradicts_bm):
    lines = [
        "# T-10-2: NWP Early-Lead Point Gain (degC consolidation)",
        "",
        f"Verdict: **{verdict}**",
        "",
        f"- Splits with early-CP (20/21/22Z) MAE or RPS improvement: {splits_improved}/3 (need >=2)",
        f"- CP23 non-regression (dMAE <= 0.02): {'PASS' if not cp23_regresses else 'FAIL'}",
        f"- Bracket-match reconciles with phase4.md: {bm_reconciles}",
        f"- degC contradicts bracket-match: {degc_contradicts_bm}",
        "",
        "## Per-CP results",
        "",
        "| Split | CP | Ridge MAE | Ridge+NWP MAE | dMAE | dRMSE | dBM | dRPS | n_test |",
        "|-------|----|-----------|---------------|------|-------|-----|------|--------|",
    ]
    for r in results:
        if r.get("thin_coverage"):
            lines.append(f"| {r['split']} | {r['cp']} | - | - | - | - | - | - | thin |")
        else:
            lines.append(
                f"| {r['split']} | {r['cp']} | {r['ridge_mae']:.4f} | "
                f"{r['nwp_mae']:.4f} | {r['d_mae']:+.4f} | {r['d_rmse']:+.4f} | "
                f"{r['d_bm']:+.4f} | {r['d_rps']:+.4f} | {r['n_test']} |"
            )
    lines.extend([
        "",
        "## Summary by CP (mean across splits)",
        "",
        "| CP | mean dMAE | mean dRMSE | mean dBM | mean dRPS | splits improved (MAE or RPS) |",
        "|----|-----------|------------|----------|----------|------------------------------|",
    ])
    for cp in ["20:00", "21:00", "22:00", "23:00"]:
        cp_rows = [r for r in results if r.get("cp") == cp and not r.get("thin_coverage")]
        if not cp_rows:
            lines.append(f"| {cp} | - | - | - | - | - |")
            continue
        m_dmae = np.mean([r["d_mae"] for r in cp_rows])
        m_drmse = np.mean([r["d_rmse"] for r in cp_rows])
        m_dbm = np.mean([r["d_bm"] for r in cp_rows])
        m_drps = np.mean([r["d_rps"] for r in cp_rows])
        n_imp = sum(1 for r in cp_rows if r["d_mae"] < 0 or r["d_rps"] < 0)
        lines.append(
            f"| {cp} | {m_dmae:+.4f} | {m_drmse:+.4f} | {m_dbm:+.4f} | "
            f"{m_drps:+.4f} | {n_imp}/{len(cp_rows)} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
