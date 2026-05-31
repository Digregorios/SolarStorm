"""T-9-5 native_integer_conformal_v0: walk-forward evaluation.

Compares native-integer calibrators (M1 abs, M2 signed) against the Phase 5
v1.0 decimal signed conformal baseline. All 4 CPs, 3 splits (2023/24/25).
Emits reports/calibration/native_integer_conformal_v0.{md,json}.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from core.baselines.climatology import fit_climatology
from core.calibration.conformal import (
    ConformalConfig,
    apply_conformal,
    fit_conformal,
)
from core.calibration.integer_conformal import (
    apply_integer_abs,
    apply_integer_signed,
    fit_integer_abs,
    fit_integer_signed,
)
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.cv import expanding_walk_forward_splits
from core.eval.gates_phase5 import heteroscedasticity_gate
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels
from core.models.ridge_band import (
    RidgeBandConfig,
    fit_ridge_band,
    predict_latent,
)

REPO = Path(__file__).resolve().parents[1]
SEED = 42
CALIB_DAYS = 120
MIN_CALIB = 30
COVERAGE = 0.80
GLOBAL_COV_LO = 0.78
GLOBAL_COV_HI = 0.86


def _arrays(panel, cols):
    X = np.column_stack([panel[c].to_numpy().astype(float) for c in cols])
    return X, panel["target_tmax_int"].to_numpy().astype(int)


def _coverage(lo, hi, y):
    return float(np.mean((lo <= y) & (y <= hi)))


def _mean_width(lo, hi):
    return float(np.mean(hi - lo + 1))


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    cps = list(cfg.cp_set_utc)

    splits = expanding_walk_forward_splits(
        history_start=date(2020, 1, 1),
        test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)],
    )

    all_results = []

    for s in splits:
        print(f"[split] {s.name}")
        climo = fit_climatology(labels, train_start=s.train_start, train_end=s.train_end)
        all_dates = [
            d for d in labels["date_local"].drop_nulls().unique().to_list()
            if d is not None
        ]
        panel = build_training_panel(
            obs, labels, climo=climo, tz_name=cfg.tz, cp_set=cps, dates=all_dates
        )

        cal_start = s.train_end - timedelta(days=CALIB_DAYS - 1)
        train_panel = panel.filter(
            (panel["date_local"] >= s.train_start) & (panel["date_local"] < cal_start)
        )
        calib_panel = panel.filter(
            (panel["date_local"] >= cal_start) & (panel["date_local"] <= s.train_end)
        )
        test_panel = panel.filter(
            (panel["date_local"] >= s.test_start) & (panel["date_local"] <= s.test_end)
        )

        # Fit Ridge on train
        rb_cfg = RidgeBandConfig(
            feature_columns=tuple(FEATURE_COLUMNS),
            alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
            use_climatology_anchor=True,
        )
        X_train, y_train = _arrays(train_panel, FEATURE_COLUMNS)
        clim_train = np.array(
            [float(climo.tmax_dec_for(d)) for d in train_panel["date_local"].to_list()]
        )
        model = fit_ridge_band(X_train, y_train, config=rb_cfg, clim_train=clim_train)

        # Predict on calib and test
        X_calib, y_calib = _arrays(calib_panel, FEATURE_COLUMNS)
        clim_calib = np.array(
            [float(climo.tmax_dec_for(d)) for d in calib_panel["date_local"].to_list()]
        )
        latent_calib = predict_latent(model, X_calib, clim=clim_calib)
        pred_int_calib = np.array([Q(float(v)) for v in latent_calib], dtype=int)

        X_test, y_test = _arrays(test_panel, FEATURE_COLUMNS)
        clim_test = np.array(
            [float(climo.tmax_dec_for(d)) for d in test_panel["date_local"].to_list()]
        )
        latent_test = predict_latent(model, X_test, clim=clim_test)
        pred_int_test = np.array([Q(float(v)) for v in latent_test], dtype=int)

        cp_calib = calib_panel["cp"].to_list()
        cp_test = test_panel["cp"].to_list()
        cp_test_arr = np.array(cp_test)

        # --- v1.0 baseline: decimal signed conformal ---
        cal_v1 = fit_conformal(
            y_true=y_calib.astype(float).tolist(),
            y_pred_dec=latent_calib.tolist(),
            cp=cp_calib,
            config=ConformalConfig(coverage=COVERAGE, method="signed", min_calib=MIN_CALIB),
        )
        lo_v1, hi_v1 = apply_conformal(cal_v1, latent_test.tolist(), cp_test)
        cov_v1 = _coverage(lo_v1, hi_v1, y_test)
        width_v1 = _mean_width(lo_v1, hi_v1)
        het_v1 = heteroscedasticity_gate(lo_v1.tolist(), hi_v1.tolist(), y_test.tolist())

        # --- M1: integer abs per CP ---
        resid_int_calib = y_calib - pred_int_calib
        lo_m1 = np.empty(len(y_test), dtype=int)
        hi_m1 = np.empty(len(y_test), dtype=int)
        m1_fits = {}
        for cp in cps:
            mask_c = np.array(cp_calib) == cp
            n_cp = int(mask_c.sum())
            if n_cp >= MIN_CALIB:
                m1_fits[cp] = fit_integer_abs(resid_int_calib[mask_c], coverage=COVERAGE)
            else:
                # pooled fallback
                m1_fits[cp] = fit_integer_abs(resid_int_calib, coverage=COVERAGE)
        for i in range(len(y_test)):
            fit_obj = m1_fits[cp_test[i]]
            lo_m1[i] = pred_int_test[i] - fit_obj.q
            hi_m1[i] = pred_int_test[i] + fit_obj.q

        cov_m1 = _coverage(lo_m1, hi_m1, y_test)
        width_m1 = _mean_width(lo_m1, hi_m1)
        het_m1 = heteroscedasticity_gate(lo_m1.tolist(), hi_m1.tolist(), y_test.tolist())

        # --- M2: integer signed per CP ---
        lo_m2 = np.empty(len(y_test), dtype=int)
        hi_m2 = np.empty(len(y_test), dtype=int)
        m2_fits = {}
        for cp in cps:
            mask_c = np.array(cp_calib) == cp
            n_cp = int(mask_c.sum())
            if n_cp >= MIN_CALIB:
                m2_fits[cp] = fit_integer_signed(resid_int_calib[mask_c], coverage=COVERAGE)
            else:
                m2_fits[cp] = fit_integer_signed(resid_int_calib, coverage=COVERAGE)
        for i in range(len(y_test)):
            fit_obj = m2_fits[cp_test[i]]
            lo_m2[i] = pred_int_test[i] + fit_obj.q_lo
            hi_m2[i] = pred_int_test[i] + fit_obj.q_hi

        cov_m2 = _coverage(lo_m2, hi_m2, y_test)
        width_m2 = _mean_width(lo_m2, hi_m2)
        het_m2 = heteroscedasticity_gate(lo_m2.tolist(), hi_m2.tolist(), y_test.tolist())

        all_results.append({
            "split": s.name,
            "n_train": train_panel.height,
            "n_calib": calib_panel.height,
            "n_test": test_panel.height,
            "v1_baseline": {
                "global_coverage": round(cov_v1, 4),
                "mean_width": round(width_v1, 2),
                "het_gate_pass": het_v1.passed,
            },
            "M1_integer_abs": {
                "global_coverage": round(cov_m1, 4),
                "mean_width": round(width_m1, 2),
                "het_gate_pass": het_m1.passed,
            },
            "M2_integer_signed": {
                "global_coverage": round(cov_m2, 4),
                "mean_width": round(width_m2, 2),
                "het_gate_pass": het_m2.passed,
            },
        })
        print(f"  v1.0  cov={cov_v1:.4f} w={width_v1:.2f} het={het_v1.passed}")
        print(f"  M1    cov={cov_m1:.4f} w={width_m1:.2f} het={het_m1.passed}")
        print(f"  M2    cov={cov_m2:.4f} w={width_m2:.2f} het={het_m2.passed}")

    # --- GO/KILL gate ---
    n_splits = len(all_results)

    def _check_method(key):
        cov_ok = sum(
            1 for r in all_results
            if GLOBAL_COV_LO <= r[key]["global_coverage"] <= GLOBAL_COV_HI
        )
        het_ok = sum(1 for r in all_results if r[key]["het_gate_pass"])
        width_ok = sum(
            1 for r in all_results
            if r[key]["mean_width"] < r["v1_baseline"]["mean_width"]
        )
        return {
            "cov_in_band": cov_ok,
            "het_pass": het_ok,
            "width_lower": width_ok,
            "gate_cov": cov_ok >= 2,
            "gate_het": het_ok >= 2,
            "gate_width": width_ok >= 2,
            "gate_deterministic_causal": True,
            "all_pass": (cov_ok >= 2) and (het_ok >= 2) and (width_ok >= 2),
        }

    gate_m1 = _check_method("M1_integer_abs")
    gate_m2 = _check_method("M2_integer_signed")

    # GO = simplest passing method (M1 first)
    if gate_m1["all_pass"]:
        verdict = "GO"
        promoted = "M1_integer_abs"
        diagnosis = "M1 (symmetric integer abs) passes all gates."
    elif gate_m2["all_pass"]:
        verdict = "GO"
        promoted = "M2_integer_signed"
        diagnosis = "M2 (asymmetric integer signed) passes all gates."
    else:
        verdict = "KILL"
        promoted = None
        # Diagnose why
        parts = []
        if not gate_m1["gate_het"] and not gate_m2["gate_het"]:
            parts.append(
                "het gate FAIL: over-coverage persists even native-integer; "
                "the slack is integer granularity itself, not Q-after"
            )
        if not gate_m1["gate_width"] and not gate_m2["gate_width"]:
            parts.append(
                "no width gain over v1.0 baseline"
            )
        if not gate_m1["gate_cov"] and not gate_m2["gate_cov"]:
            parts.append(
                "global coverage outside [0.78, 0.86]"
            )
        parts.append("Recommend T-9-7 diagnostic stopgap.")
        diagnosis = "; ".join(parts)

    output = {
        "task": "T-9-5",
        "prereg": "native_integer_conformal_v0",
        "verdict": verdict,
        "promoted_method": promoted,
        "diagnosis": diagnosis,
        "gate_M1": gate_m1,
        "gate_M2": gate_m2,
        "splits": all_results,
    }

    # Write reports
    out_dir = REPO / "reports" / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "native_integer_conformal_v0.json"
    with open(json_path, "w", encoding="ascii") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {json_path}")

    # Markdown report
    md_lines = [
        f"# T-9-5 native_integer_conformal_v0: {verdict}",
        "",
        f"**Verdict:** {verdict}",
        f"**Promoted:** {promoted}",
        f"**Diagnosis:** {diagnosis}",
        "",
        "## Per-split results",
        "",
        "| Split | Method | Coverage | Width | Het Pass |",
        "|-------|--------|----------|-------|----------|",
    ]
    for r in all_results:
        sp = r["split"][:10]
        for key, label in [
            ("v1_baseline", "v1.0"),
            ("M1_integer_abs", "M1"),
            ("M2_integer_signed", "M2"),
        ]:
            md_lines.append(
                f"| {sp} | {label} | {r[key]['global_coverage']:.4f} "
                f"| {r[key]['mean_width']:.2f} | {r[key]['het_gate_pass']} |"
            )
    md_lines.extend([
        "",
        "## Gate summary",
        "",
        f"- M1: cov_in_band={gate_m1['cov_in_band']}/3, "
        f"het_pass={gate_m1['het_pass']}/3, "
        f"width_lower={gate_m1['width_lower']}/3 -> "
        f"{'PASS' if gate_m1['all_pass'] else 'FAIL'}",
        f"- M2: cov_in_band={gate_m2['cov_in_band']}/3, "
        f"het_pass={gate_m2['het_pass']}/3, "
        f"width_lower={gate_m2['width_lower']}/3 -> "
        f"{'PASS' if gate_m2['all_pass'] else 'FAIL'}",
        "",
    ])

    md_path = out_dir / "native_integer_conformal_v0.md"
    with open(md_path, "w", encoding="ascii") as f:
        f.write("\n".join(md_lines))
    print(f"Wrote {md_path}")

    print(f"\nFinal verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
