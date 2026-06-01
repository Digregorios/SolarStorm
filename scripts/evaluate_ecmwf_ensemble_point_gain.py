"""T-11-5: ECMWF ensemble point gain evaluation.

Measures whether ECMWF alone or GFS+ECMWF ensemble improves the Tmax POINT
forecast vs Ridge/GFS-residual, per CP and in the non_calm/high_delta error
pocket. Walk-forward over the ECMWF overlap window 2024-03..2025-12.

prereg: contracts/ecmwf_ensemble_point_gain_v0_prereg.md (prereg_version 1.0)
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from core.baselines.climatology import fit_climatology, fit_tmax_hour_climatology
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.metrics import bracket_match_at_p50, mae, rmse, rps
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
    build_features as build_lw_features,
    fit_risk_model,
    predict_risk,
)
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
SEED = 42
np.random.seed(SEED)

# ECMWF overlap window
WINDOW_START = date(2024, 3, 1)
WINDOW_END = date(2025, 12, 31)

# Within-window expanding splits (>=2 test folds)
# Train from WINDOW_START, test H1-2025 and H2-2025
SPLITS = [
    ("2025-H1", WINDOW_START, date(2024, 12, 31), date(2025, 1, 1), date(2025, 6, 30)),
    ("2025-H2", WINDOW_START, date(2025, 6, 30), date(2025, 7, 1), date(2025, 12, 31)),
]

PHASE4_FEATURES = tuple(FEATURE_COLUMNS) + tuple(NWP_FEATURE_COLUMNS)

# Reduced n_estimators for speed (noted in report)
N_ESTIMATORS = 200



def _rps_from_latent(latent_arr, y_int, climo, dates, tau, mode, tmp_min, tmp_max):
    """Compute mean RPS from latent predictions."""
    scores = []
    for v, t, d in zip(latent_arr, y_int, dates):
        p10, p90 = climo.percentiles_for(d)
        sk = support_K(p10, p90, tmp_min=tmp_min, tmp_max=tmp_max)
        pd = latent_to_prob_dist(float(v), sk, tau=tau, mode=mode)
        scores.append(rps(pd, int(t)))
    return float(np.mean(scores))


def _compute_metrics(pred_int, pred_latent, y_int, climo, dates, tau, mode, tmp_min, tmp_max):
    """Return dict with MAE, RMSE, bracket_match, RPS."""
    return {
        "mae": round(mae(pred_int, y_int), 4),
        "rmse": round(rmse(pred_int, y_int), 4),
        "bracket_match": round(bracket_match_at_p50(pred_int, y_int), 4),
        "rps": round(_rps_from_latent(pred_latent, y_int, climo, dates, tau, mode, tmp_min, tmp_max), 4),
    }


def _arrays(panel, columns):
    X = np.column_stack([panel[c].to_numpy().astype(float) for c in columns])
    y = panel["target_tmax_int"].to_numpy().astype(int)
    return X, y




def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    tau, mode = 0.5, "linear"
    tmp_min = cfg.tmp_c_int_plausibility.min
    tmp_max = cfg.tmp_c_int_plausibility.max
    cp_set = cfg.cp_set_utc

    print("[1/6] Loading observations + labels ...")
    obs, _ = load_observations(
        REPO / "NZWN.csv", tmp_min_c=tmp_min, tmp_max_c=tmp_max
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cp_set)

    print("[2/6] Loading NWP snapshots ...")
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    gfs_snaps = read_snapshots(station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root)
    ecmwf_snaps = read_snapshots(station=cfg.icao, model=ECMWF_IFS_HRES, endpoint="single_runs", out_root=nwp_root)
    print(f"  GFS rows={gfs_snaps.height}, ECMWF rows={ecmwf_snaps.height}")
    ensemble_snaps = pl.concat([gfs_snaps, ecmwf_snaps], how="vertical_relaxed")

    print("[3/6] Fitting tmax-hour climatology ...")
    thc = fit_tmax_hour_climatology(
        labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=cfg.tz
    )

    # Restrict dates to the overlap window
    overlap_dates = [
        d for d in labels["date_local"].unique().to_list()
        if d is not None and WINDOW_START <= d <= WINDOW_END
    ]
    overlap_dates.sort()
    print(f"  Overlap window dates: {len(overlap_dates)}")

    print("[4/6] Building panels (GFS, ECMWF, ensemble) ...")
    # Broad climo for panel seeding (per-split refit inside)
    climo_broad = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))

    panel_gfs = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=cp_set,
        dates=overlap_dates,
        nwp_snapshots=gfs_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc,
    )
    print(f"  panel_gfs rows={panel_gfs.height}")

    panel_ecmwf = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=cp_set,
        dates=overlap_dates,
        nwp_snapshots=ecmwf_snaps, nwp_models=(ECMWF_IFS_HRES.id,), tmax_hour_climo=thc,
    )
    print(f"  panel_ecmwf rows={panel_ecmwf.height}")

    panel_ensemble = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=cp_set,
        dates=overlap_dates,
        nwp_snapshots=ensemble_snaps, nwp_models=(NCEP_GFS.id, ECMWF_IFS_HRES.id), tmax_hour_climo=thc,
    )
    print(f"  panel_ensemble rows={panel_ensemble.height}")

    # Also build a no-NWP panel for Ridge baseline
    panel_base = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=cp_set,
        dates=overlap_dates,
    )
    print(f"  panel_base rows={panel_base.height}")

    # Late-warming features for regime strata
    print("[5/6] Building late-warming features for regime strata ...")
    lw_panel = build_lw_features(obs, labels, tz=cfg.tz, cp_hhmm=cfg.cp_operational_utc)



    print("[6/6] Walk-forward evaluation ...")
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

    all_results = []

    for split_name, tr_start, tr_end, te_start, te_end in SPLITS:
        print(f"  Split: {split_name}")
        split_out = {"split": split_name, "train": [tr_start.isoformat(), tr_end.isoformat()],
                     "test": [te_start.isoformat(), te_end.isoformat()], "by_cp": {}}

        for cp in cp_set:
            # --- Filter panels to this CP and split windows ---
            def _split(panel):
                sub = panel.filter(panel["cp"] == cp)
                tr = sub.filter((sub["date_local"] >= tr_start) & (sub["date_local"] <= tr_end))
                te = sub.filter((sub["date_local"] >= te_start) & (sub["date_local"] <= te_end))
                return tr, te

            tr_base, te_base = _split(panel_base)
            tr_gfs, te_gfs = _split(panel_gfs)
            tr_ecmwf, te_ecmwf = _split(panel_ecmwf)
            tr_ens, te_ens = _split(panel_ensemble)

            # Keep only rows with valid NWP anchor for NWP models
            tr_gfs_ok = tr_gfs.filter(tr_gfs["nwp_t2m_maxtraj_c"].is_not_null())
            te_gfs_ok = te_gfs.filter(te_gfs["nwp_t2m_maxtraj_c"].is_not_null())
            tr_ecmwf_ok = tr_ecmwf.filter(tr_ecmwf["nwp_t2m_maxtraj_c"].is_not_null())
            te_ecmwf_ok = te_ecmwf.filter(te_ecmwf["nwp_t2m_maxtraj_c"].is_not_null())
            tr_ens_ok = tr_ens.filter(tr_ens["nwp_t2m_maxtraj_c"].is_not_null())
            te_ens_ok = te_ens.filter(te_ens["nwp_t2m_maxtraj_c"].is_not_null())

            # Intersect test dates across all candidates for fair comparison
            dates_base = set(te_base["date_local"].to_list())
            dates_gfs = set(te_gfs_ok["date_local"].to_list())
            dates_ecmwf = set(te_ecmwf_ok["date_local"].to_list())
            dates_ens = set(te_ens_ok["date_local"].to_list())
            common_dates = sorted(dates_base & dates_gfs & dates_ecmwf & dates_ens)

            if len(common_dates) < 20:
                print(f"    CP={cp}: only {len(common_dates)} common dates, skipping")
                continue

            # Filter to common dates
            te_base_c = te_base.filter(pl.col("date_local").is_in(common_dates))
            te_gfs_c = te_gfs_ok.filter(pl.col("date_local").is_in(common_dates))
            te_ecmwf_c = te_ecmwf_ok.filter(pl.col("date_local").is_in(common_dates))
            te_ens_c = te_ens_ok.filter(pl.col("date_local").is_in(common_dates))

            # Per-split train-only climatology (uses full obs history up to tr_end,
            # not just the ECMWF overlap window - climo needs >= 365 days)
            climo_labels = labels.filter(
                pl.col("date_local") <= tr_end
            ).select(["date_local", "tmax_int", "day_complete"])
            climo = fit_climatology(climo_labels, train_start=date(2020, 1, 1), train_end=tr_end)

            # --- 1. Ridge base ---
            X_tr_base, y_tr_base = _arrays(tr_base, tuple(FEATURE_COLUMNS))
            clim_tr = np.array([float(climo.tmax_dec_for(d)) for d in tr_base["date_local"].to_list()])
            ridge = fit_ridge_band(X_tr_base, y_tr_base, config=cfg_ridge, clim_train=clim_tr)

            X_te_base, y_te = _arrays(te_base_c, tuple(FEATURE_COLUMNS))
            clim_te = np.array([float(climo.tmax_dec_for(d)) for d in te_base_c["date_local"].to_list()])
            ridge_latent = predict_ridge_latent(ridge, X_te_base, clim=clim_te)
            ridge_int = np.array([Q(float(v)) for v in ridge_latent], dtype=int)

            # --- 2. GFS-residual ---
            X_tr_gfs, y_tr_gfs = _arrays(tr_gfs_ok, PHASE4_FEATURES)
            anchor_tr_gfs = tr_gfs_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
            if tr_gfs_ok.height >= 100:
                lgbm_gfs = fit_residual_lgbm(X_tr_gfs, y_tr_gfs, anchor_tr_gfs, config=cfg_lgbm)
                X_te_gfs, _ = _arrays(te_gfs_c, PHASE4_FEATURES)
                anchor_te_gfs = te_gfs_c["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
                gfs_latent = predict_lgbm_latent(lgbm_gfs, X_te_gfs, anchor_te_gfs)
                gfs_int = np.array([Q(float(v)) for v in gfs_latent], dtype=int)
            else:
                gfs_latent = ridge_latent.copy()
                gfs_int = ridge_int.copy()

            # --- 3. ECMWF-residual ---
            X_tr_ecmwf, y_tr_ecmwf = _arrays(tr_ecmwf_ok, PHASE4_FEATURES)
            anchor_tr_ecmwf = tr_ecmwf_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
            if tr_ecmwf_ok.height >= 100:
                lgbm_ecmwf = fit_residual_lgbm(X_tr_ecmwf, y_tr_ecmwf, anchor_tr_ecmwf, config=cfg_lgbm)
                X_te_ecmwf, _ = _arrays(te_ecmwf_c, PHASE4_FEATURES)
                anchor_te_ecmwf = te_ecmwf_c["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
                ecmwf_latent = predict_lgbm_latent(lgbm_ecmwf, X_te_ecmwf, anchor_te_ecmwf)
                ecmwf_int = np.array([Q(float(v)) for v in ecmwf_latent], dtype=int)
            else:
                ecmwf_latent = ridge_latent.copy()
                ecmwf_int = ridge_int.copy()

            # --- 4. GFS+ECMWF ensemble ---
            X_tr_ens, y_tr_ens = _arrays(tr_ens_ok, PHASE4_FEATURES)
            anchor_tr_ens = tr_ens_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
            if tr_ens_ok.height >= 100:
                lgbm_ens = fit_residual_lgbm(X_tr_ens, y_tr_ens, anchor_tr_ens, config=cfg_lgbm)
                X_te_ens, _ = _arrays(te_ens_c, PHASE4_FEATURES)
                anchor_te_ens = te_ens_c["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
                ens_latent = predict_lgbm_latent(lgbm_ens, X_te_ens, anchor_te_ens)
                ens_int = np.array([Q(float(v)) for v in ens_latent], dtype=int)
            else:
                ens_latent = ridge_latent.copy()
                ens_int = ridge_int.copy()

            test_dates = te_base_c["date_local"].to_list()

            # --- Strata masks ---
            # EX-ANTE non_calm: predicted_risk >= c30 (train P30)
            lw_tr = lw_panel.filter(
                (lw_panel["date_local"] >= tr_start) & (lw_panel["date_local"] <= tr_end)
            )
            risk_model = None
            c30 = 0.3
            if lw_tr.height >= 200:
                risk_model = fit_risk_model(lw_tr, seed=SEED)
                p_tr = predict_risk(risk_model, lw_tr)
                c30 = float(np.quantile(p_tr, 0.30))

            # Predict risk on test dates
            lw_te = lw_panel.filter(pl.col("date_local").is_in(common_dates))
            risk_map = {}
            if risk_model is not None and lw_te.height > 0:
                p_te = predict_risk(risk_model, lw_te)
                for d, p in zip(lw_te["date_local"].to_list(), p_te):
                    risk_map[d] = float(p)

            # delta_06_to_cp from lw_panel
            delta_map = {}
            for row in lw_panel.filter(pl.col("date_local").is_in(common_dates)).iter_rows(named=True):
                delta_map[row["date_local"]] = row.get("delta_06_to_cp")

            # Compute train P50 of delta_06_to_cp for high_delta threshold
            lw_tr_deltas = [
                r["delta_06_to_cp"] for r in lw_tr.iter_rows(named=True)
                if r["delta_06_to_cp"] is not None and not (isinstance(r["delta_06_to_cp"], float) and math.isnan(r["delta_06_to_cp"]))
            ]
            delta_p50 = float(np.median(lw_tr_deltas)) if lw_tr_deltas else 0.0

            # Build masks
            non_calm_mask = np.array([risk_map.get(d, 0.0) >= c30 for d in test_dates])
            high_delta_mask = np.array([
                (delta_map.get(d) is not None and
                 not (isinstance(delta_map.get(d), float) and math.isnan(delta_map.get(d))) and
                 delta_map.get(d) >= delta_p50)
                for d in test_dates
            ])
            intersection_mask = non_calm_mask & high_delta_mask
            all_mask = np.ones(len(test_dates), dtype=bool)

            # Compute metrics per candidate per stratum
            strata = {"ALL": all_mask, "non_calm": non_calm_mask,
                      "high_delta_06": high_delta_mask, "non_calm_AND_high_delta": intersection_mask}

            cp_results = {"n_test": len(common_dates), "c30": round(c30, 4), "delta_p50": round(delta_p50, 2)}
            for cand_name, cand_int, cand_latent in [
                ("ridge", ridge_int, ridge_latent),
                ("gfs_residual", gfs_int, gfs_latent),
                ("ecmwf_residual", ecmwf_int, ecmwf_latent),
                ("ensemble", ens_int, ens_latent),
            ]:
                cand_out = {}
                for st_name, mask in strata.items():
                    n_st = int(mask.sum())
                    if n_st < 5:
                        cand_out[st_name] = {"n": n_st, "mae": None, "rmse": None, "bracket_match": None, "rps": None}
                        continue
                    cand_out[st_name] = _compute_metrics(
                        cand_int[mask], cand_latent[mask], y_te[mask],
                        climo, [test_dates[i] for i in range(len(test_dates)) if mask[i]],
                        tau, mode, tmp_min, tmp_max,
                    )
                    cand_out[st_name]["n"] = n_st
                cp_results[cand_name] = cand_out
            split_out["by_cp"][cp] = cp_results

        all_results.append(split_out)



    # --- GATE EVALUATION ---
    print("\n[GATE] Evaluating 5-part GO gate PER CANDIDATE (prereg: prefer ecmwf_residual, then ensemble) ...")

    def _cand_gate1(cand: str) -> int:
        """Splits where `cand` beats best of {ridge, gfs_residual} on MAE OR RPS at CP20-22."""
        n = 0
        for sr in all_results:
            cp_wins = 0
            for cp in ["20:00", "21:00", "22:00"]:
                cpd = sr["by_cp"].get(cp)
                if cpd is None:
                    continue
                ridge_m = cpd.get("ridge", {}).get("ALL", {})
                gfs_m = cpd.get("gfs_residual", {}).get("ALL", {})
                cand_m = cpd.get(cand, {}).get("ALL", {})
                if not all(x.get("mae") is not None for x in [ridge_m, gfs_m, cand_m]):
                    continue
                if (cand_m["mae"] < min(ridge_m["mae"], gfs_m["mae"])
                        or cand_m["rps"] < min(ridge_m["rps"], gfs_m["rps"])):
                    cp_wins += 1
            if cp_wins >= 2:
                n += 1
        return n

    def _cand_gate2(cand: str) -> bool:
        """`cand` does not regress CP23 MAE by > 0.02 vs best existing, in any split."""
        for sr in all_results:
            cpd = sr["by_cp"].get("23:00")
            if cpd is None:
                continue
            ridge_m = cpd.get("ridge", {}).get("ALL", {})
            gfs_m = cpd.get("gfs_residual", {}).get("ALL", {})
            cand_m = cpd.get(cand, {}).get("ALL", {})
            if not all(x.get("mae") is not None for x in [ridge_m, gfs_m, cand_m]):
                continue
            if cand_m["mae"] - min(ridge_m["mae"], gfs_m["mae"]) > 0.02:
                return False
        return True

    def _cand_gate3(cand: str) -> int:
        """Splits where `cand` materially gains in the non_calm/high_delta pocket at CP20-22."""
        n = 0
        for sr in all_results:
            wins, cps = 0, 0
            for cp in ["20:00", "21:00", "22:00"]:
                cpd = sr["by_cp"].get(cp)
                if cpd is None:
                    continue
                pk = "non_calm_AND_high_delta"
                ridge_p = cpd.get("ridge", {}).get(pk, {})
                gfs_p = cpd.get("gfs_residual", {}).get(pk, {})
                cand_p = cpd.get(cand, {}).get(pk, {})
                if not all(x.get("mae") is not None for x in [ridge_p, gfs_p, cand_p]):
                    continue
                cps += 1
                if (cand_p["mae"] - min(ridge_p["mae"], gfs_p["mae"])) <= -0.03 \
                        or cand_p["rps"] < min(ridge_p["rps"], gfs_p["rps"]):
                    wins += 1
            if cps > 0 and wins >= 2:
                n += 1
        return n

    n_splits = len(all_results)
    need = max(2, n_splits - 1)  # >=2/3, or >=2/2 in the shorter window
    per_candidate = {}
    for cand in ("ecmwf_residual", "ensemble"):
        g1 = _cand_gate1(cand) >= need
        g2 = _cand_gate2(cand)
        g3 = _cand_gate3(cand) >= need
        per_candidate[cand] = {
            "gate1_cp20_22": g1, "gate1_splits": _cand_gate1(cand),
            "gate2_cp23_no_regress": g2,
            "gate3_pocket": g3, "gate3_splits": _cand_gate3(cand),
            "passes": g1 and g2 and g3,
        }
        print(f"  {cand}: g1={g1} g2={g2} g3={g3} -> passes={per_candidate[cand]['passes']}")

    gate4 = True  # causal/deterministic by construction (seed 42, deterministic, num_threads=1)
    gate5 = True  # predictor-only, no exec/calib change
    # GO = the simplest candidate (prefer ecmwf_residual, then ensemble) meeting gates 1-3 (+4,5).
    best_candidate = next((c for c in ("ecmwf_residual", "ensemble")
                           if per_candidate[c]["passes"]), None)
    go = best_candidate is not None and gate4 and gate5
    verdict = "GO" if go else "KILL"
    kill_reason = "" if go else (
        "No single NWP candidate passes gates 1-3 per-candidate; ECMWF value, if any, is for "
        "SPREAD (T-11-6), not the point.")

    print(f"\n  === VERDICT: {verdict} ===")
    if kill_reason:
        print(f"  Reason: {kill_reason}")
    if best_candidate:
        print(f"  Best candidate: {best_candidate}")



    # --- Write reports ---
    out_dir = REPO / "reports" / "nwp"
    out_dir.mkdir(parents=True, exist_ok=True)

    report_json = {
        "task": "T-11-5",
        "prereg": "contracts/ecmwf_ensemble_point_gain_v0_prereg.md",
        "prereg_version": "1.0",
        "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "n_estimators_note": f"Reduced to {N_ESTIMATORS} for speed (from 500)",
        "splits": all_results,
        "gate_required_splits": need,
        "per_candidate_gates": per_candidate,
        "gate4_causal_deterministic": gate4,
        "gate5_no_exec_calib_change": gate5,
        "verdict": verdict,
        "best_candidate": best_candidate,
        "kill_reason": kill_reason if not go else None,
        "seed": SEED,
        "deterministic": True,
        "num_threads": 1,
    }

    (out_dir / "ecmwf_ensemble_point_gain.json").write_text(
        json.dumps(report_json, default=str, ensure_ascii=True, indent=2),
        encoding="ascii",
    )

    # Markdown report
    md_lines = [
        "# T-11-5: ECMWF Ensemble Point Gain Evaluation",
        "",
        f"**Verdict: {verdict}**",
        "",
        f"- Prereg: `contracts/ecmwf_ensemble_point_gain_v0_prereg.md` (v1.0)",
        f"- Window: {WINDOW_START} to {WINDOW_END} (ECMWF overlap, SHORTER than 2023-2025 point splits)",
        f"- Splits: {len(SPLITS)} within-window expanding (train from 2024-03)",
        f"- LGBM n_estimators: {N_ESTIMATORS} (reduced from 500 for speed)",
        f"- Seed: {SEED}, deterministic=True, num_threads=1",
        "",
        "## Gate Results (per candidate; GO = simplest candidate passing gates 1-3)",
        "",
        f"| Candidate | gate1 CP20-22 (splits) | gate2 CP23 no-regress | gate3 pocket (splits) | passes |",
        f"|-----------|------------------------|-----------------------|-----------------------|--------|",
        f"| ecmwf_residual | {per_candidate['ecmwf_residual']['gate1_cp20_22']} "
        f"({per_candidate['ecmwf_residual']['gate1_splits']}/{len(all_results)}) | "
        f"{per_candidate['ecmwf_residual']['gate2_cp23_no_regress']} | "
        f"{per_candidate['ecmwf_residual']['gate3_pocket']} "
        f"({per_candidate['ecmwf_residual']['gate3_splits']}/{len(all_results)}) | "
        f"{per_candidate['ecmwf_residual']['passes']} |",
        f"| ensemble | {per_candidate['ensemble']['gate1_cp20_22']} "
        f"({per_candidate['ensemble']['gate1_splits']}/{len(all_results)}) | "
        f"{per_candidate['ensemble']['gate2_cp23_no_regress']} | "
        f"{per_candidate['ensemble']['gate3_pocket']} "
        f"({per_candidate['ensemble']['gate3_splits']}/{len(all_results)}) | "
        f"{per_candidate['ensemble']['passes']} |",
        f"| (gate4 causal/deterministic: {gate4}; gate5 no exec/calib: {gate5}) | | | | |",
        "",
    ]
    if kill_reason:
        md_lines.extend([f"**Kill reason:** {kill_reason}", ""])
    if best_candidate:
        md_lines.extend([f"**Best candidate:** {best_candidate}", ""])

    # Per-CP summary tables
    md_lines.extend(["## Per-CP Results (ALL stratum)", ""])
    for sr in all_results:
        md_lines.append(f"### Split: {sr['split']}")
        md_lines.append("")
        md_lines.append("| CP | Candidate | MAE | RMSE | BM | RPS | n |")
        md_lines.append("|----|-----------|-----|------|----|-----|---|")
        for cp in cp_set:
            cpd = sr["by_cp"].get(cp)
            if cpd is None:
                continue
            for cand in ["ridge", "gfs_residual", "ecmwf_residual", "ensemble"]:
                m = cpd.get(cand, {}).get("ALL", {})
                if m.get("mae") is None:
                    continue
                md_lines.append(
                    f"| {cp} | {cand} | {m['mae']:.4f} | {m['rmse']:.4f} | {m['bracket_match']:.4f} | {m['rps']:.4f} | {m['n']} |"
                )
        md_lines.append("")

    # Pocket results
    md_lines.extend(["## Non-calm AND High-delta Pocket", ""])
    for sr in all_results:
        md_lines.append(f"### Split: {sr['split']}")
        md_lines.append("")
        md_lines.append("| CP | Candidate | MAE | RPS | n |")
        md_lines.append("|----|-----------|-----|-----|---|")
        for cp in cp_set:
            cpd = sr["by_cp"].get(cp)
            if cpd is None:
                continue
            for cand in ["ridge", "gfs_residual", "ecmwf_residual", "ensemble"]:
                m = cpd.get(cand, {}).get("non_calm_AND_high_delta", {})
                if m.get("mae") is None:
                    continue
                md_lines.append(
                    f"| {cp} | {cand} | {m['mae']:.4f} | {m['rps']:.4f} | {m['n']} |"
                )
        md_lines.append("")

    md_lines.extend([
        "## Notes",
        "",
        "- This is a SHORTER walk-forward than the 2023-2025 point splits due to ECMWF archive start (2024-02).",
        "- Anti-leakage: per-split train-only climatology, c30, P50; causal NWP (run_time <= cp - 60min).",
        "- Regime strata are EX-ANTE (predicted risk, never truth).",
        "- If KILL: ECMWF value may be for SPREAD (T-11-6), not the point forecast.",
        "",
    ])

    (out_dir / "ecmwf_ensemble_point_gain.md").write_text(
        "\n".join(md_lines), encoding="ascii"
    )

    print(f"\n[DONE] Reports written to {out_dir}")
    print(f"  - ecmwf_ensemble_point_gain.json")
    print(f"  - ecmwf_ensemble_point_gain.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
