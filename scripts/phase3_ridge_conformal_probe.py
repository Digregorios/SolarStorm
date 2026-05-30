"""Phase-3 Ridge conformal-minimal probe: per-CP IC80 coverage on walk-forward TEST.

NOT Phase 5. Validates that ``ridge_conformal_minimal`` (per-CP 80% quantile of the Ridge's
own integer abs-residuals, design in core/models/ridge_conformal.py) produces IC80 coverage
near 0.80 per CP out of sample, with non-degenerate widths. Calibration window = the recent
tail of the train split (split conformal); test is read-only. Emits
reports/ridge_conformal_probe.{md,json}.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from core.baselines.climatology import fit_climatology
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.cv import expanding_walk_forward_splits
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_int as ridge_predict_int
from core.models.ridge_conformal import fit_cp_abs_conformal, interval

REPO = Path(__file__).resolve().parents[1]
CALIB_DAYS = 120  # recent tail of train used as the conformal calibration window
N_MIN = 30


def _arrays(panel, cols):
    X = np.column_stack([panel[c].to_numpy().astype(float) for c in cols])
    return X, panel["target_tmax_int"].to_numpy().astype(int)


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=cfg.tmp_c_int_plausibility.min,
                               tmp_max_c=cfg.tmp_c_int_plausibility.max)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    climo = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))
    all_dates = [d for d in labels["date_local"].drop_nulls().unique().to_list() if d is not None]
    panel = build_training_panel(obs, labels, climo=climo, tz_name=cfg.tz, cp_set=cfg.cp_set_utc,
                                 dates=all_dates)
    splits = expanding_walk_forward_splits(history_start=date(2020, 1, 1),
                                           test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)])
    cps = list(cfg.cp_set_utc)
    results = []
    for s in splits:
        tr = panel.filter((panel["date_local"] >= s.train_start) & (panel["date_local"] <= s.train_end))
        te = panel.filter((panel["date_local"] >= s.test_start) & (panel["date_local"] <= s.test_end))
        # Train Ridge on operational CP rows (matches phase3), predict p50 for all rows.
        tr_op = tr.filter(tr["cp"] == cfg.cp_operational_utc)
        if tr_op.height < 100:
            continue
        Xtr, ytr = _arrays(tr_op, FEATURE_COLUMNS)
        ctr = np.array([float(climo.tmax_dec_for(d)) for d in tr_op["date_local"].to_list()])
        fr = fit_ridge_band(Xtr, ytr, config=RidgeBandConfig(feature_columns=tuple(FEATURE_COLUMNS),
                                                            use_climatology_anchor=True), clim_train=ctr)

        def _p50(frame):
            X, _ = _arrays(frame, FEATURE_COLUMNS)
            c = np.array([float(climo.tmax_dec_for(d)) for d in frame["date_local"].to_list()])
            return ridge_predict_int(fr, X, clim=c)

        # Calibration window = last CALIB_DAYS of train, all CPs.
        cal_start = s.train_end - timedelta(days=CALIB_DAYS - 1)
        cal = tr.filter(tr["date_local"] >= cal_start)
        cal_p50 = _p50(cal)
        cal_abs = np.abs(cal["target_tmax_int"].to_numpy().astype(int) - cal_p50)
        conf = fit_cp_abs_conformal(cal_abs.tolist(), cal["cp"].to_list(), coverage=0.80, n_min=N_MIN)

        te_p50 = _p50(te)
        te_y = te["target_tmax_int"].to_numpy().astype(int)
        te_cp = te["cp"].to_list()
        per_cp = {cp: {"n": 0, "covered": 0, "width_sum": 0} for cp in cps}
        widths = []
        for p50, y, cp in zip(te_p50, te_y, te_cp):
            lo, hi, _src = interval(conf, int(p50), cp)
            w = hi - lo + 1
            widths.append(w)
            if cp in per_cp:
                per_cp[cp]["n"] += 1
                per_cp[cp]["covered"] += int(lo <= y <= hi)
                per_cp[cp]["width_sum"] += w
        cp_cov = {cp: {"coverage": (v["covered"] / v["n"]) if v["n"] else None,
                       "mean_width": (v["width_sum"] / v["n"]) if v["n"] else None, "n": v["n"]}
                  for cp, v in per_cp.items()}
        w = np.asarray(widths)
        overall = float(np.mean([
            1 if interval(conf, int(p), c)[0] <= yy <= interval(conf, int(p), c)[1] else 0
            for p, yy, c in zip(te_p50, te_y, te_cp)
        ]))
        results.append({
            "split": s.name,
            "overall_coverage": overall,
            "mean_width": float(w.mean()), "n_distinct_widths": int(np.unique(w).size),
            "by_cp": cp_cov,
        })

    out = {"probe": "ridge_conformal_minimal", "coverage_target": 0.80,
           "calib_days": CALIB_DAYS, "n_min": N_MIN, "splits": results}
    (REPO / "reports").mkdir(exist_ok=True)
    (REPO / "reports" / "ridge_conformal_probe.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    L = ["# Ridge conformal-minimal probe (per-CP IC80 coverage, walk-forward TEST)", "",
         "_NOT Phase 5. IC80 = per-CP 80% quantile of the Ridge's own integer abs-residuals._", "",
         "| split | overall cov | mean width | distinct w | per-CP coverage (n) |",
         "|-------|-------------|------------|------------|----------------------|"]
    for r in results:
        cps_str = "; ".join(f"{cp} {v['coverage']:.2f} (n={v['n']})" for cp, v in r["by_cp"].items() if v["coverage"] is not None)
        L.append(f"| {r['split']} | {r['overall_coverage']:.3f} | {r['mean_width']:.2f} | {r['n_distinct_widths']} | {cps_str} |")
    (REPO / "reports" / "ridge_conformal_probe.md").write_text("\n".join(L) + "\n", encoding="ascii")
    for r in results:
        print(r["split"], "overall_cov=%.3f" % r["overall_coverage"], "mean_w=%.2f" % r["mean_width"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
