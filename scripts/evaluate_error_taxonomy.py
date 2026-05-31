"""T-10-3 forecast_error_taxonomy: ranked failure map of Ridge point errors.

Walk-forward 2023/24/25, operational CP 23:00. Breaks Ridge point error by
strata (month/season, wind quadrant, rain-persistence, s_to_n, predicted-risk
regime, delta_06_to_cp magnitude, and DIAGNOSTIC post-hoc strata). Produces
reports/model_error_taxonomy.{md,json}.

Read-only analysis. No model/threshold change. Deterministic seed 42.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from core.baselines.climatology import fit_climatology
from core.contracts.station import load_station_config
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import (
    build_features as build_lw_features,
    fit_risk_model,
    predict_risk,
)
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_int

REPO = Path(__file__).resolve().parents[1]
CP_OP = "23:00"
TEST_STARTS = [date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)]
SEED = 42

SEASONS = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
            6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    # Broad climatology for panel building (train-only per split below)
    climo_broad = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))
    panel = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=[CP_OP]
    )

    # Late-warming risk features panel
    lw_panel = build_lw_features(obs, labels, cfg.tz, CP_OP)

    # Collect all test rows across walk-forward splits
    all_rows: list[dict] = []

    for ts in TEST_STARTS:
        te = date(ts.year, 12, 31)
        train = panel.filter(panel["date_local"] < ts)
        test = panel.filter((panel["date_local"] >= ts) & (panel["date_local"] <= te))
        if train.height < 200 or test.height < 50:
            continue

        # Train-only climatology
        tl = (train.select(["date_local", "target_tmax_int"])
              .rename({"target_tmax_int": "tmax_int"})
              .with_columns(pl.lit(True).alias("day_complete")))
        cl = fit_climatology(tl, train_start=date(2020, 1, 1), train_end=ts)

        # Fit Ridge
        Xtr = np.column_stack([train[c].to_numpy().astype(float) for c in FEATURE_COLUMNS])
        ytr = train["target_tmax_int"].to_numpy().astype(int)
        clim_tr = np.array([float(cl.tmax_dec_for(d)) for d in train["date_local"].to_list()])
        rb = RidgeBandConfig(feature_columns=tuple(FEATURE_COLUMNS),
                             use_climatology_anchor=True, seed=SEED)
        model = fit_ridge_band(Xtr, ytr, config=rb, clim_train=clim_tr)

        # Predict on test
        Xte = np.column_stack([test[c].to_numpy().astype(float) for c in FEATURE_COLUMNS])
        clim_te = np.array([float(cl.tmax_dec_for(d)) for d in test["date_local"].to_list()])
        pred = predict_int(model, Xte, clim=clim_te)
        truth = test["target_tmax_int"].to_numpy().astype(int)
        kcp = test["k_cp"].to_numpy().astype(int)
        dates_test = test["date_local"].to_list()

        # Fit late-warming risk model on train portion (EX-ANTE regime)
        lw_train = lw_panel.filter(lw_panel["date_local"] < ts)
        lw_test = lw_panel.filter(
            (lw_panel["date_local"] >= ts) & (lw_panel["date_local"] <= te)
        )
        # Train P30 threshold (calm_day_filter_v0 c30): calm = bottom-30% predicted risk,
        # non_calm = risk >= P30 (top 70%). Same definition as T-9-1/T-9-3 (no drift).
        risk_model = None
        c30_thresh = 0.3
        if lw_train.height >= 200:
            risk_model = fit_risk_model(lw_train, seed=SEED)
            p_tr = predict_risk(risk_model, lw_train)
            c30_thresh = float(np.quantile(p_tr, 0.30))

        # Build date->risk map for test
        risk_map: dict[date, float] = {}
        if risk_model is not None and lw_test.height > 0:
            p_te = predict_risk(risk_model, lw_test)
            for d, p in zip(lw_test["date_local"].to_list(), p_te):
                risk_map[d] = float(p)

        # Build date->lw_features map for strata
        lw_feat_map: dict[date, dict] = {}
        for row in lw_panel.iter_rows(named=True):
            lw_feat_map[row["date_local"]] = row

        for i in range(len(dates_test)):
            d = dates_test[i]
            lw_row = lw_feat_map.get(d, {})
            risk_p = risk_map.get(d)
            regime = "non_calm" if (risk_p is not None and risk_p >= c30_thresh) else "calm"

            # Wind quadrant at CP
            southerly = lw_row.get("southerly_at_cp", 0)
            wind_quad = "southerly" if southerly else "northerly"

            # Rain persistence
            rain_path = bool(lw_row.get("rain_persistence_path", 0))

            # s_to_n
            s_to_n = bool(lw_row.get("s_to_n", 0))

            # delta_06_to_cp
            delta_06 = lw_row.get("delta_06_to_cp")

            all_rows.append({
                "date": d,
                "month": d.month,
                "season": SEASONS[d.month],
                "pred_int": int(pred[i]),
                "truth_int": int(truth[i]),
                "k_cp": int(kcp[i]),
                "abs_error": abs(int(pred[i]) - int(truth[i])),
                "signed_error": int(pred[i]) - int(truth[i]),
                "bracket_miss": int(int(pred[i]) != int(truth[i])),
                "wind_quad": wind_quad,
                "rain_persistence": rain_path,
                "s_to_n": s_to_n,
                "regime_exante": regime,
                "delta_06_to_cp": delta_06,
                # DIAGNOSTIC (post-hoc) strata
                "material_late_warming": int((int(truth[i]) - int(kcp[i])) >= 2),
                "tmax_already_reached": int(int(kcp[i]) == int(truth[i])),
            })

    if not all_rows:
        print("ERROR: no test rows produced")
        return 1

    # Compute strata stats
    total_abs_error = sum(r["abs_error"] for r in all_rows)
    n_total = len(all_rows)

    def _stratum_stats(mask_rows):
        n = len(mask_rows)
        if n == 0:
            return None
        ae = [r["abs_error"] for r in mask_rows]
        se = [r["signed_error"] for r in mask_rows]
        bm = [r["bracket_miss"] for r in mask_rows]
        return {
            "n": n,
            "mean_abs_error": round(float(np.mean(ae)), 3),
            "signed_bias": round(float(np.mean(se)), 3),
            "bracket_miss_rate": round(float(np.mean(bm)), 4),
            "error_share": round(float(sum(ae)) / total_abs_error, 4) if total_abs_error > 0 else 0.0,
        }

    strata_results: dict[str, dict] = {}

    # Month
    for m in range(1, 13):
        rows_m = [r for r in all_rows if r["month"] == m]
        s = _stratum_stats(rows_m)
        if s:
            strata_results[f"month_{m:02d}"] = s

    # Season
    for ssn in ("DJF", "MAM", "JJA", "SON"):
        rows_s = [r for r in all_rows if r["season"] == ssn]
        s = _stratum_stats(rows_s)
        if s:
            strata_results[f"season_{ssn}"] = s

    # Wind quadrant
    for wq in ("southerly", "northerly"):
        rows_w = [r for r in all_rows if r["wind_quad"] == wq]
        s = _stratum_stats(rows_w)
        if s:
            strata_results[f"wind_{wq}"] = s

    # Rain persistence
    for rp in (True, False):
        rows_r = [r for r in all_rows if r["rain_persistence"] == rp]
        s = _stratum_stats(rows_r)
        if s:
            strata_results[f"rain_persist_{'yes' if rp else 'no'}"] = s

    # s_to_n
    for sn in (True, False):
        rows_sn = [r for r in all_rows if r["s_to_n"] == sn]
        s = _stratum_stats(rows_sn)
        if s:
            strata_results[f"s_to_n_{'yes' if sn else 'no'}"] = s

    # Predicted-risk regime (EX-ANTE)
    for reg in ("calm", "non_calm"):
        rows_reg = [r for r in all_rows if r["regime_exante"] == reg]
        s = _stratum_stats(rows_reg)
        if s:
            strata_results[f"regime_exante_{reg}"] = s

    # delta_06_to_cp magnitude bins
    valid_delta = [r for r in all_rows if r["delta_06_to_cp"] is not None
                   and not (isinstance(r["delta_06_to_cp"], float) and math.isnan(r["delta_06_to_cp"]))]
    if valid_delta:
        deltas = [r["delta_06_to_cp"] for r in valid_delta]
        q33 = float(np.quantile(deltas, 0.33))
        q67 = float(np.quantile(deltas, 0.67))
        for label, lo, hi in [("low", -999, q33), ("mid", q33, q67), ("high", q67, 999)]:
            rows_d = [r for r in valid_delta if lo <= r["delta_06_to_cp"] < hi]
            s = _stratum_stats(rows_d)
            if s:
                s["bin_range"] = f"[{lo:.1f}, {hi:.1f})"
                strata_results[f"delta06_bin_{label}"] = s

    # DIAGNOSTIC post-hoc: material late-warming (truth-derived)
    rows_lw = [r for r in all_rows if r["material_late_warming"]]
    s = _stratum_stats(rows_lw)
    if s:
        s["label"] = "POST-HOC (truth-derived)"
        strata_results["DIAG_material_late_warming"] = s

    rows_no_lw = [r for r in all_rows if not r["material_late_warming"]]
    s = _stratum_stats(rows_no_lw)
    if s:
        s["label"] = "POST-HOC (truth-derived)"
        strata_results["DIAG_no_late_warming"] = s

    # DIAGNOSTIC post-hoc: Tmax already reached at CP
    rows_ar = [r for r in all_rows if r["tmax_already_reached"]]
    s = _stratum_stats(rows_ar)
    if s:
        s["label"] = "POST-HOC (truth-derived)"
        strata_results["DIAG_tmax_already_reached"] = s

    rows_nar = [r for r in all_rows if not r["tmax_already_reached"]]
    s = _stratum_stats(rows_nar)
    if s:
        s["label"] = "POST-HOC (truth-derived)"
        strata_results["DIAG_tmax_not_yet_reached"] = s

    # RANKED top-5 error pockets by share of total absolute error
    # (n * mean|error| / sum). For binary strata, only the minority class is
    # a meaningful "pocket"; the complement is the baseline population.
    MAJORITY_COMPLEMENTS = {
        "s_to_n_no", "rain_persist_no", "wind_northerly",
        "DIAG_no_late_warming", "DIAG_tmax_not_yet_reached",
        "regime_exante_calm",
    }
    pocket_candidates = {k: v for k, v in strata_results.items()
                         if k not in MAJORITY_COMPLEMENTS}
    ranked = sorted(pocket_candidates.items(), key=lambda kv: -kv[1]["error_share"])
    top5 = []
    for name, stats in ranked[:5]:
        is_posthoc = "DIAG" in name
        top5.append({
            "stratum": name,
            "n": stats["n"],
            "mean_abs_error": stats["mean_abs_error"],
            "signed_bias": stats["signed_bias"],
            "bracket_miss_rate": stats["bracket_miss_rate"],
            "error_share": stats["error_share"],
            "actionable": "POST-HOC only" if is_posthoc else "EX-ANTE actionable",
        })

    out = {
        "model": "ridge_band_point_forecast",
        "cp": CP_OP,
        "walk_forward_splits": [s.isoformat() for s in TEST_STARTS],
        "n_total": n_total,
        "total_abs_error_degC": int(total_abs_error),
        "overall_mae": round(float(np.mean([r["abs_error"] for r in all_rows])), 3),
        "overall_bias": round(float(np.mean([r["signed_error"] for r in all_rows])), 3),
        "overall_bracket_miss": round(float(np.mean([r["bracket_miss"] for r in all_rows])), 4),
        "strata": strata_results,
        "top5_error_pockets": top5,
        "seed": SEED,
        "note": "EX-ANTE strata use predicted risk (not truth). "
                "DIAG_ strata are POST-HOC (truth-derived) and clearly labelled.",
    }

    (REPO / "reports").mkdir(exist_ok=True)
    (REPO / "reports" / "model_error_taxonomy.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str),
        encoding="ascii",
    )
    (REPO / "reports" / "model_error_taxonomy.md").write_text(
        _render(out), encoding="ascii"
    )
    print(f"n={n_total} MAE={out['overall_mae']} bias={out['overall_bias']} "
          f"bracket_miss={out['overall_bracket_miss']}")
    print("\nTOP-5 ERROR POCKETS (ranked by share of total |error|):")
    for i, p in enumerate(top5, 1):
        print(f"  {i}. {p['stratum']}: share={p['error_share']:.1%} "
              f"MAE={p['mean_abs_error']} n={p['n']} [{p['actionable']}]")
    return 0


def _render(out: dict) -> str:
    L = [
        "# Model Error Taxonomy (T-10-3)", "",
        f"Ridge point forecast at CP {out['cp']}, walk-forward {out['walk_forward_splits']}.", "",
        f"- N = {out['n_total']}, overall MAE = {out['overall_mae']} degC, "
        f"bias = {out['overall_bias']}, bracket-miss = {out['overall_bracket_miss']}", "",
        "## Strata breakdown", "",
        "| Stratum | n | MAE | Bias | Bracket-miss | Error share |",
        "|---------|---|-----|------|--------------|-------------|",
    ]
    for name, s in sorted(out["strata"].items()):
        tag = " [POST-HOC]" if "DIAG" in name else ""
        L.append(f"| {name}{tag} | {s['n']} | {s['mean_abs_error']} | "
                 f"{s['signed_bias']} | {s['bracket_miss_rate']} | "
                 f"{s['error_share']:.1%} |")
    L += ["", "## TOP-5 ranked error pockets", "",
          "| Rank | Stratum | Share | MAE | n | Actionable |",
          "|------|---------|-------|-----|---|------------|"]
    for i, p in enumerate(out["top5_error_pockets"], 1):
        L.append(f"| {i} | {p['stratum']} | {p['error_share']:.1%} | "
                 f"{p['mean_abs_error']} | {p['n']} | {p['actionable']} |")
    L += ["", "---", f"Seed {out['seed']}. Anti-leakage: regime strata use EX-ANTE predicted risk "
          "(calm = bottom-30% predicted risk; non_calm = risk >= train P30, the calm_day_filter_v0 c30). DIAG_ strata are POST-HOC (truth-derived).", ""]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
