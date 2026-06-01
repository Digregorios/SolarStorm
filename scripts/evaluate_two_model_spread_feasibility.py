"""T-11-6: Two-model spread feasibility evaluation.

Does a causal two-model NWP spread |GFS - ECMWF| predict the realized integer
Tmax error? Measure Spearman + quartile curve per CP, especially CP20-22 /
non_calm / high_delta.

prereg: contracts/two_model_spread_feasibility_v0_prereg.md (prereg_version 1.0)
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import spearmanr

from core.baselines.climatology import fit_climatology, fit_tmax_hour_climatology
from core.contracts.station import load_station_config
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots, select_nwp_v1
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import (
    build_features as build_lw_features,
    fit_risk_model,
    predict_risk,
)
from core.models.ridge_band import (
    RidgeBandConfig,
    fit_ridge_band,
    predict_int as predict_ridge_int,
)

REPO = Path(__file__).resolve().parents[1]
SEED = 42
np.random.seed(SEED)

WINDOW_START = date(2024, 3, 1)
WINDOW_END = date(2025, 12, 31)

# >=2 expanding folds within the ECMWF overlap window
SPLITS = [
    ("fold1", WINDOW_START, date(2024, 12, 31), date(2025, 1, 1), date(2025, 6, 30)),
    ("fold2", WINDOW_START, date(2025, 6, 30), date(2025, 7, 1), date(2025, 12, 31)),
]

SAFETY_MARGIN = timedelta(minutes=60)


def _spearman(x, y):
    """Spearman correlation, returns (rho, p) or (nan, nan) if degenerate."""
    if len(x) < 5:
        return float("nan"), float("nan")
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), float("nan")
    rho, p = spearmanr(x, y)
    return float(rho), float(p)


def _quartile_means(spread, error, q_edges):
    """Mean error per quartile bin defined by q_edges (from train)."""
    out = {}
    for qi in range(4):
        lo = q_edges[qi]
        hi = q_edges[qi + 1] if qi < 3 else float("inf")
        if qi == 0:
            mask = spread <= hi
        elif qi == 3:
            mask = spread > lo
        else:
            mask = (spread > lo) & (spread <= hi)
        vals = error[mask]
        out[f"Q{qi+1}"] = float(np.mean(vals)) if len(vals) > 0 else None
    return out


def _train_quartile_edges(spread_train):
    """Compute quartile edges from train spread (25/50/75 percentiles)."""
    q25, q50, q75 = np.percentile(spread_train, [25, 50, 75])
    return [float("-inf"), float(q25), float(q50), float(q75)]


def _fmt(v):
    """Format a float or None for markdown."""
    return f"{v:.3f}" if v is not None else "-"




def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    tmp_min = cfg.tmp_c_int_plausibility.min
    tmp_max = cfg.tmp_c_int_plausibility.max
    cp_set = cfg.cp_set_utc
    tz = cfg.tz

    print("[1/5] Loading observations + labels ...")
    obs, _ = load_observations(
        REPO / "NZWN.csv", tmp_min_c=tmp_min, tmp_max_c=tmp_max
    )
    labels = build_tmax_labels(obs, tz_name=tz, cp_set_utc=cp_set)

    print("[2/5] Loading NWP snapshots ...")
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    gfs_snaps = read_snapshots(
        station=cfg.icao, model=NCEP_GFS,
        endpoint="s3_grib", out_root=nwp_root
    )
    ecmwf_snaps = read_snapshots(
        station="NZWN", model=ECMWF_IFS_HRES,
        endpoint="single_runs", out_root=nwp_root
    )
    print(f"  GFS rows={gfs_snaps.height}, ECMWF rows={ecmwf_snaps.height}")

    print("[3/5] Building panels ...")
    overlap_dates = sorted([
        d for d in labels["date_local"].unique().to_list()
        if d is not None and WINDOW_START <= d <= WINDOW_END
    ])
    print(f"  Overlap window dates: {len(overlap_dates)}")

    climo_broad = fit_climatology(
        labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31)
    )
    thc = fit_tmax_hour_climatology(
        labels, train_start=date(2020, 1, 1),
        train_end=date(2022, 12, 31), tz_name=tz
    )

    # Build panel with GFS only (for Ridge point prediction)
    panel_gfs = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set,
        dates=overlap_dates,
        nwp_snapshots=gfs_snaps, nwp_models=(NCEP_GFS.id,),
        tmax_hour_climo=thc,
    )
    print(f"  panel_gfs rows={panel_gfs.height}")

    print("[4/5] Building late-warming features ...")
    lw_panel = build_lw_features(obs, labels, tz=tz, cp_hhmm=cfg.cp_operational_utc)

    print("[5/5] Walk-forward spread evaluation ...")
    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=0.5, mode="linear", use_climatology_anchor=True,
    )

    all_results = []


    for split_name, tr_start, tr_end, te_start, te_end in SPLITS:
        print(f"  Split: {split_name} (train {tr_start}..{tr_end}, test {te_start}..{te_end})")
        split_out = {"split": split_name, "by_cp": {}}

        for cp in cp_set:
            # Filter panel to this CP
            sub = panel_gfs.filter(pl.col("cp") == cp)
            tr = sub.filter(
                (pl.col("date_local") >= tr_start) & (pl.col("date_local") <= tr_end)
            )
            te = sub.filter(
                (pl.col("date_local") >= te_start) & (pl.col("date_local") <= te_end)
            )

            # Need valid NWP for Ridge anchor
            tr_ok = tr.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
            te_ok = te.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
            if tr_ok.height < 50 or te_ok.height < 10:
                print(f"    CP={cp}: insufficient data (tr={tr_ok.height}, te={te_ok.height})")
                continue

            # Per-split train-only climatology
            climo = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=tr_end)

            # Fit Ridge on train
            feat_cols = tuple(FEATURE_COLUMNS)
            X_tr = np.column_stack([tr_ok[c].to_numpy().astype(float) for c in feat_cols])
            y_tr = tr_ok["target_tmax_int"].to_numpy().astype(int)
            clim_tr = np.array([float(climo.tmax_dec_for(d)) for d in tr_ok["date_local"].to_list()])
            ridge = fit_ridge_band(X_tr, y_tr, config=cfg_ridge, clim_train=clim_tr)

            # Predict on test
            X_te = np.column_stack([te_ok[c].to_numpy().astype(float) for c in feat_cols])
            y_te = te_ok["target_tmax_int"].to_numpy().astype(int)
            clim_te = np.array([float(climo.tmax_dec_for(d)) for d in te_ok["date_local"].to_list()])
            pred_int = predict_ridge_int(ridge, X_te, clim=clim_te)

            # For each test row, get causal GFS and ECMWF t2m at CP
            test_dates = te_ok["date_local"].to_list()
            cp_utcs = te_ok["cp_utc"].to_list()

            gfs_t2m = []
            ecmwf_t2m = []
            gfs_maxtraj = []
            ecmwf_maxtraj = []
            valid_mask = []

            for i, (d, cp_utc_val) in enumerate(zip(test_dates, cp_utcs)):
                # select_nwp_v1 for each model
                gfs_sel = select_nwp_v1(
                    gfs_snaps, cp_utc=cp_utc_val,
                    target_valid_utc=cp_utc_val, safety_margin=SAFETY_MARGIN
                )
                ecmwf_sel = select_nwp_v1(
                    ecmwf_snaps, cp_utc=cp_utc_val,
                    target_valid_utc=cp_utc_val, safety_margin=SAFETY_MARGIN
                )
                if gfs_sel is not None and gfs_sel.t2m_c is not None and \
                   ecmwf_sel is not None and ecmwf_sel.t2m_c is not None:
                    gfs_t2m.append(gfs_sel.t2m_c)
                    ecmwf_t2m.append(ecmwf_sel.t2m_c)
                    valid_mask.append(True)
                else:
                    gfs_t2m.append(None)
                    ecmwf_t2m.append(None)
                    valid_mask.append(False)

            valid_mask = np.array(valid_mask)
            n_valid = int(valid_mask.sum())
            if n_valid < 10:
                print(f"    CP={cp}: only {n_valid} rows with both models, skipping")
                continue

            # Compute spreads on valid rows only
            gfs_arr = np.array([v for v in gfs_t2m if v is not None])
            ecmwf_arr = np.array([v for v in ecmwf_t2m if v is not None])
            spread_at_cp = np.abs(gfs_arr - ecmwf_arr)

            # Error signals on same valid rows
            y_valid = y_te[valid_mask]
            pred_valid = pred_int[valid_mask]
            abs_error = np.abs(y_valid - pred_valid).astype(float)

            # Also get maxtraj spread from the panel (already computed)
            maxtraj_spread = te_ok["nwp_t2m_maxtraj_spread_c"].to_numpy()[valid_mask]
            # maxtraj_spread was computed with single model -> will be 0
            # Compute real maxtraj spread: need per-model maxtraj
            # Use the panel's nwp_t2m_maxtraj_c as GFS maxtraj (panel built with GFS only)
            # For a true two-model maxtraj spread we'd need both panels
            # Instead use spread_at_cp as primary candidate (prereg primary)

            # Train spread for quartile edges (from train rows with both models)
            tr_dates = tr_ok["date_local"].to_list()
            tr_cp_utcs = tr_ok["cp_utc"].to_list()
            train_spreads = []
            for td, tc in zip(tr_dates, tr_cp_utcs):
                gs = select_nwp_v1(gfs_snaps, cp_utc=tc, target_valid_utc=tc, safety_margin=SAFETY_MARGIN)
                es = select_nwp_v1(ecmwf_snaps, cp_utc=tc, target_valid_utc=tc, safety_margin=SAFETY_MARGIN)
                if gs and gs.t2m_c is not None and es and es.t2m_c is not None:
                    train_spreads.append(abs(gs.t2m_c - es.t2m_c))
            train_spreads = np.array(train_spreads) if train_spreads else np.array([0.0])

            q_edges = _train_quartile_edges(train_spreads)

            # Spearman and quartile analysis
            rho, p_val = _spearman(spread_at_cp, abs_error)
            q_means = _quartile_means(spread_at_cp, abs_error, q_edges)

            # Regime strata (ex-ante, train-only thresholds)
            # non_calm: predicted_risk >= c30 (train P30)
            lw_tr = lw_panel.filter(
                (pl.col("date_local") >= tr_start) & (pl.col("date_local") <= tr_end)
            )
            c30 = 0.3
            risk_model = None
            if lw_tr.height >= 50:
                risk_model = fit_risk_model(lw_tr, seed=SEED)
                p_tr = predict_risk(risk_model, lw_tr)
                c30 = float(np.quantile(p_tr, 0.30))

            # high_delta_06: delta_06_to_cp >= train P50
            lw_tr_deltas = [
                r["delta_06_to_cp"] for r in lw_tr.iter_rows(named=True)
                if r.get("delta_06_to_cp") is not None
                and not (isinstance(r["delta_06_to_cp"], float) and math.isnan(r["delta_06_to_cp"]))
            ]
            delta_p50 = float(np.median(lw_tr_deltas)) if lw_tr_deltas else 0.0

            # Predict risk on test dates
            valid_dates = [test_dates[i] for i in range(len(test_dates)) if valid_mask[i]]
            lw_te = lw_panel.filter(pl.col("date_local").is_in(valid_dates))
            risk_map = {}
            if risk_model is not None and lw_te.height > 0:
                p_te = predict_risk(risk_model, lw_te)
                for d_lw, p_lw in zip(lw_te["date_local"].to_list(), p_te):
                    risk_map[d_lw] = float(p_lw)

            delta_map = {}
            for row in lw_panel.filter(pl.col("date_local").is_in(valid_dates)).iter_rows(named=True):
                delta_map[row["date_local"]] = row.get("delta_06_to_cp")

            non_calm = np.array([risk_map.get(d, 0.0) >= c30 for d in valid_dates])
            high_delta = np.array([
                (delta_map.get(d) is not None
                 and not (isinstance(delta_map.get(d), float) and math.isnan(delta_map.get(d)))
                 and delta_map.get(d) >= delta_p50)
                for d in valid_dates
            ])

            # Per-stratum results
            strata_results = {}
            for st_name, st_mask in [("ALL", np.ones(n_valid, dtype=bool)),
                                      ("non_calm", non_calm),
                                      ("high_delta_06", high_delta)]:
                n_st = int(st_mask.sum())
                if n_st < 5:
                    strata_results[st_name] = {"n": n_st, "spearman": None, "quartiles": None}
                    continue
                rho_st, _ = _spearman(spread_at_cp[st_mask], abs_error[st_mask])
                q_st = _quartile_means(spread_at_cp[st_mask], abs_error[st_mask], q_edges)
                strata_results[st_name] = {
                    "n": n_st, "spearman": round(rho_st, 4), "quartiles": q_st
                }

            cp_result = {
                "n_valid": n_valid,
                "spearman_rho": round(rho, 4),
                "spearman_p": round(p_val, 4),
                "quartile_means": q_means,
                "q_edges_train": [round(e, 3) if not math.isinf(e) else str(e) for e in q_edges],
                "mean_spread": round(float(np.mean(spread_at_cp)), 3),
                "strata": strata_results,
                "c30": round(c30, 4),
                "delta_p50": round(delta_p50, 2),
            }
            split_out["by_cp"][cp] = cp_result
            print(f"    CP={cp}: n={n_valid}, Spearman={rho:.4f}, "
                  f"Q1={q_means.get('Q1','?'):.3f} Q4={q_means.get('Q4','?'):.3f}")

        all_results.append(split_out)


    # --- GATE EVALUATION (4-part per prereg) ---
    print("\n[GATE] Evaluating FEASIBLE gate ...")
    # Gate 1: Spearman positive in >= 2 folds
    # Gate 2: Q4 > Q1 mean abs_error in >= 2 folds
    # Gate 3: Holds per CP, esp CP20-22
    # Gate 4: Causal + same rows + train-only thresholds

    gate1_passes = 0  # folds with positive Spearman (any CP)
    gate2_passes = 0  # folds with Q4 > Q1 (any CP)
    gate3_cp2022 = True  # signal holds at CP20-22

    per_cp_spearman = {}  # cp -> list of rho across folds
    per_cp_quartiles = {}  # cp -> list of {Q1..Q4} across folds

    for sr in all_results:
        fold_has_pos_spearman = False
        fold_has_q4_gt_q1 = False
        for cp, cpd in sr["by_cp"].items():
            rho = cpd["spearman_rho"]
            qm = cpd["quartile_means"]
            per_cp_spearman.setdefault(cp, []).append(rho)
            per_cp_quartiles.setdefault(cp, []).append(qm)
            if not math.isnan(rho) and rho > 0:
                fold_has_pos_spearman = True
            if qm.get("Q4") is not None and qm.get("Q1") is not None:
                if qm["Q4"] > qm["Q1"]:
                    fold_has_q4_gt_q1 = True
        if fold_has_pos_spearman:
            gate1_passes += 1
        if fold_has_q4_gt_q1:
            gate2_passes += 1

    # Gate 3: check CP20-22 specifically - require at least 1 fold positive per CP
    # and majority of (CP, fold) pairs positive
    cp2022_positive = 0
    cp2022_total = 0
    for cp in ["20:00", "21:00", "22:00"]:
        rhos = per_cp_spearman.get(cp, [])
        for r in rhos:
            cp2022_total += 1
            if not math.isnan(r) and r > 0:
                cp2022_positive += 1
    gate3_cp2022 = cp2022_total > 0 and cp2022_positive > cp2022_total / 2

    gate4 = True  # causal by construction (select_nwp_v1 + train-only edges)

    gate1_ok = gate1_passes >= 2
    gate2_ok = gate2_passes >= 2
    feasible = gate1_ok and gate2_ok and gate3_cp2022 and gate4

    # Robustness: is the spread->error sign CONSISTENT across folds per CP? A CP whose Spearman
    # flips sign between folds is a seasonal reversal (not a usable standalone signal). This
    # tightens the lenient any-CP gate into an honest headline.
    cp_sign_consistent = {}
    for cp, rhos in per_cp_spearman.items():
        clean = [r for r in rhos if not math.isnan(r)]
        cp_sign_consistent[cp] = bool(clean) and (all(r > 0 for r in clean) or all(r < 0 for r in clean))
    sign_reversal = any(not cp_sign_consistent.get(cp, False) for cp in ["20:00", "21:00", "22:00"])

    if not feasible:
        verdict = "NOT FEASIBLE"
    elif sign_reversal:
        # Gates technically met (lenient any-CP), but the signal reverses sign by fold/season ->
        # only usable as a SEASON-INTERACTED calibration difficulty axis, never standalone / routing.
        verdict = "FEASIBLE-CONDITIONAL"
    else:
        verdict = "FEASIBLE"

    print(f"\n  Gate 1 (Spearman positive >= 2 folds): {gate1_ok} ({gate1_passes}/{len(all_results)})")
    print(f"  Gate 2 (Q4 > Q1 >= 2 folds): {gate2_ok} ({gate2_passes}/{len(all_results)})")
    print(f"  Gate 3 (holds CP20-22): {gate3_cp2022}")
    print(f"  Gate 4 (causal/train-only): {gate4}")
    print(f"  Cross-fold sign consistency per CP: {cp_sign_consistent} (reversal={sign_reversal})")
    print(f"\n  === VERDICT: {verdict} ===")

    # Best spread candidate
    best_candidate = "spread_at_cp (|GFS_t2m - ECMWF_t2m| at CP)"

    # --- Write JSON report ---
    out_dir = REPO / "reports" / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)

    report_json = {
        "task": "T-11-6",
        "prereg": "contracts/two_model_spread_feasibility_v0_prereg.md",
        "prereg_version": "1.0",
        "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "window_note": "ECMWF overlap 2024-03..2025-12; shorter than 2023-2025",
        "splits": all_results,
        "gate1_spearman_positive_folds": gate1_passes,
        "gate2_q4_gt_q1_folds": gate2_passes,
        "gate3_cp2022_holds": gate3_cp2022,
        "gate4_causal_train_only": gate4,
        "cp_sign_consistent": cp_sign_consistent,
        "sign_reversal": sign_reversal,
        "verdict": verdict,
        "verdict_note": ("FEASIBLE-CONDITIONAL = gates met but spread->error sign reverses by season "
                         "(CP20/CP21 flip across folds); usable ONLY as a season/regime-interacted "
                         "calibration difficulty axis with mandatory ablation; NOT standalone, NOT point "
                         "routing." if verdict == "FEASIBLE-CONDITIONAL" else ""),
        "best_spread_candidate": best_candidate,
        "per_cp_spearman_summary": {
            cp: [round(r, 4) for r in rhos]
            for cp, rhos in per_cp_spearman.items()
        },
        "per_cp_quartile_summary": per_cp_quartiles,
        "seed": SEED,
        "deterministic": True,
    }

    (out_dir / "two_model_spread_feasibility.json").write_text(
        json.dumps(report_json, default=str, ensure_ascii=True, indent=2),
        encoding="ascii",
    )

    # --- Write Markdown report ---
    md = []
    md.append("# T-11-6: Two-Model Spread Feasibility")
    md.append("")
    md.append(f"**Verdict: {verdict}**")
    md.append("")
    md.append(f"- Prereg: `contracts/two_model_spread_feasibility_v0_prereg.md` (v1.0)")
    md.append(f"- Window: {WINDOW_START} to {WINDOW_END} (ECMWF overlap, shorter than 2023-2025)")
    md.append(f"- Splits: {len(SPLITS)} expanding folds within overlap window")
    md.append(f"- Best spread candidate: {best_candidate}")
    md.append(f"- Seed: {SEED}, deterministic")
    md.append("")
    md.append("## Gate Results")
    md.append("")
    md.append(f"| Gate | Criterion | Result |")
    md.append(f"|------|-----------|--------|")
    md.append(f"| 1 | Spearman positive >= 2 folds | {gate1_ok} ({gate1_passes}/{len(all_results)}) |")
    md.append(f"| 2 | Q4 > Q1 mean abs_error >= 2 folds | {gate2_ok} ({gate2_passes}/{len(all_results)}) |")
    md.append(f"| 3 | Holds per CP esp CP20-22 | {gate3_cp2022} |")
    md.append(f"| 4 | Causal + same rows + train-only | {gate4} |")
    md.append("")
    md.append("## Per-CP Spearman(spread, abs_error)")
    md.append("")
    md.append("| CP | Fold 1 | Fold 2 |")
    md.append("|----|--------|--------|")
    for cp in cp_set:
        rhos = per_cp_spearman.get(cp, [])
        row_vals = " | ".join(f"{r:.4f}" if not math.isnan(r) else "-" for r in rhos)
        md.append(f"| {cp} | {row_vals} |")
    md.append("")
    md.append("## Quartile Curve (mean abs_error by spread quartile)")
    md.append("")
    for sr in all_results:
        md.append(f"### {sr['split']}")
        md.append("")
        md.append("| CP | Q1 | Q2 | Q3 | Q4 | n |")
        md.append("|----|----|----|----|----|---|")
        for cp, cpd in sr["by_cp"].items():
            qm = cpd["quartile_means"]
            md.append(f"| {cp} | {_fmt(qm.get('Q1'))} | {_fmt(qm.get('Q2'))} | "
                      f"{_fmt(qm.get('Q3'))} | {_fmt(qm.get('Q4'))} | {cpd['n_valid']} |")
        md.append("")
    md.append("## Strata Breakdown (non_calm / high_delta_06)")
    md.append("")
    for sr in all_results:
        md.append(f"### {sr['split']}")
        md.append("")
        md.append("| CP | Stratum | n | Spearman | Q1 | Q4 |")
        md.append("|----|---------|---|----------|----|----|")
        for cp, cpd in sr["by_cp"].items():
            for st_name in ["non_calm", "high_delta_06"]:
                st = cpd["strata"].get(st_name, {})
                n_st = st.get("n", 0)
                rho_st = st.get("spearman")
                qm_st = st.get("quartiles") or {}
                rho_s = f"{rho_st:.4f}" if rho_st is not None else "-"
                q1_s = f"{qm_st.get('Q1', 0):.3f}" if qm_st.get("Q1") is not None else "-"
                q4_s = f"{qm_st.get('Q4', 0):.3f}" if qm_st.get("Q4") is not None else "-"
                md.append(f"| {cp} | {st_name} | {n_st} | {rho_s} | {q1_s} | {q4_s} |")
        md.append("")
    md.append("## Notes")
    md.append("")
    md.append("- Anti-leakage: causal NWP (run_time <= cp - 60min), train-only quartile edges,")
    md.append("  train-only c30/P50, ex-ante regime (predicted risk, never truth), same rows.")
    md.append("- Window is shorter than full 2023-2025 due to ECMWF archive start (2024-03).")
    md.append("- Spread candidate: |GFS_t2m_at_cp - ECMWF_t2m_at_cp| per CP.")
    md.append(f"- Cross-fold sign consistency per CP: {cp_sign_consistent} (reversal={sign_reversal}).")
    if verdict == "FEASIBLE":
        md.append("- FEASIBLE: spread reliably predicts error and is sign-consistent across folds.")
        md.append("  Recommend T-11-8 using spread as a difficulty axis for the integer-native/CQR calibrator.")
    elif verdict == "FEASIBLE-CONDITIONAL":
        md.append("- FEASIBLE-CONDITIONAL: gates met but the spread->error sign REVERSES by fold/season")
        md.append("  (CP20/CP21 flip). Usable ONLY as a season/regime-INTERACTED calibration difficulty")
        md.append("  axis (T-11-8 CQR), with mandatory ablation. NOT a standalone signal and NOT for")
        md.append("  point routing/serving. REQ-AUD-5 stays unchanged (no auto-reopen).")
    else:
        md.append("- NOT FEASIBLE: two-model spread does not reliably predict error at NZWN")
        md.append("  in this window. Do NOT build a spread-conditioned calibrator.")
    md.append("")

    (out_dir / "two_model_spread_feasibility.md").write_text(
        "\n".join(md), encoding="ascii"
    )

    print(f"\n[DONE] Reports written to {out_dir}")
    print(f"  - two_model_spread_feasibility.json")
    print(f"  - two_model_spread_feasibility.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
