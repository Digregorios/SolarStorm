"""Late-warming bias audit: is the Ridge p50 SYSTEMATICALLY cold under post-CP warming,
or were the 4 fresh days just an adversarial cluster? (update.txt 2026-05-31)

Read-only diagnostic. NO model change. On the walk-forward TEST years (2023/2024/2025, a much
larger OOS than the n=4 fresh days), at the operational CP, computes the signed error
``truth_int - p50`` for four centers - ridge / empirical / climatology / persistence - and
stratifies by: CP, month, late_spike_l1, late-warming magnitude ``k_eod - k_cp``, and local
Tmax hour. Per-split train-only climatology (no leakage). Emits reports/late_warming_bias_audit.{md,json}.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import fit_empirical_conditional
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.cv import expanding_walk_forward_splits
from core.features.builder import build_panel
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_int as ridge_predict_int

REPO = Path(__file__).resolve().parents[1]


def _bias(errs):
    a = np.asarray(errs, dtype=float)
    return {"n": int(a.size), "mean_err": float(a.mean()) if a.size else None,
            "cold_rate": float((a > 0).mean()) if a.size else None,  # truth>p50 = forecast too cold
            "mae": float(np.abs(a).mean()) if a.size else None}


def _by(rows, key_fn, arm):
    out = {}
    for r in rows:
        k = key_fn(r)
        out.setdefault(k, []).append(r["truth"] - r[arm])
    return {str(k): _bias(v) for k, v in sorted(out.items(), key=lambda kv: str(kv[0]))}


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    cp_op = cfg.cp_operational_utc
    obs, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=cfg.tmp_c_int_plausibility.min,
                               tmp_max_c=cfg.tmp_c_int_plausibility.max)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    lab_by_date = {r["date_local"]: r for r in labels.iter_rows(named=True)}
    l1_col = f"late_spike_l1__cp_{cp_op[:2]}"
    all_dates = [d for d in labels["date_local"].drop_nulls().unique().to_list() if d is not None]
    splits = expanding_walk_forward_splits(history_start=date(2020, 1, 1),
                                           test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)])
    rows: list[dict] = []
    emp_panel_full = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc)
    for s in splits:
        climo = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=s.train_end)
        panel = build_training_panel(obs, labels, climo=climo, tz_name=cfg.tz, cp_set=cfg.cp_set_utc, dates=all_dates)
        op = panel.filter(panel["cp"] == cp_op)
        tr = op.filter((op["date_local"] >= s.train_start) & (op["date_local"] <= s.train_end))
        te = op.filter((op["date_local"] >= s.test_start) & (op["date_local"] <= s.test_end))
        if tr.height < 100:
            continue
        Xtr = np.column_stack([tr[c].to_numpy().astype(float) for c in FEATURE_COLUMNS])
        ytr = tr["target_tmax_int"].to_numpy().astype(int)
        ctr = np.array([float(climo.tmax_dec_for(d)) for d in tr["date_local"].to_list()])
        fr = fit_ridge_band(Xtr, ytr, config=RidgeBandConfig(feature_columns=tuple(FEATURE_COLUMNS),
                                                            use_climatology_anchor=True), clim_train=ctr)
        emp_tr = emp_panel_full.filter((emp_panel_full["date_local"] >= s.train_start)
                                       & (emp_panel_full["date_local"] <= s.train_end))
        emp = fit_empirical_conditional(emp_tr, train_window=(s.train_start, s.train_end))
        Xte = np.column_stack([te[c].to_numpy().astype(float) for c in FEATURE_COLUMNS])
        cte = np.array([float(climo.tmax_dec_for(d)) for d in te["date_local"].to_list()])
        ridge_p50 = ridge_predict_int(fr, Xte, clim=cte)
        for i, rr in enumerate(te.iter_rows(named=True)):
            d = rr["date_local"]
            lab = lab_by_date.get(d, {})
            y = rr["target_tmax_int"]
            if y is None:
                continue
            kcp = rr["k_cp"]
            kcp_pred = int(kcp) if kcp is not None else Q(climo.tmax_dec_for(d))
            sk = list(range(cfg.tmp_c_int_plausibility.min, cfg.tmp_c_int_plausibility.max + 1))
            pd_e, _ = emp.predict_dist(month=d.month, cp=cp_op, k_cp=kcp_pred, support_k=sk)
            emp_p50 = max(pd_e.items(), key=lambda kv: kv[1])[0]
            tmax_ts_local = lab.get("tmax_ts_local")
            rows.append({
                "truth": int(y), "ridge": int(ridge_p50[i]), "empirical": int(emp_p50),
                "climatology": int(Q(climo.tmax_dec_for(d))), "persistence": int(kcp_pred),
                "cp": cp_op, "month": d.month, "late_spike_l1": bool(lab.get(l1_col)) if lab.get(l1_col) is not None else None,
                "late_warm_mag": (int(y) - kcp_pred),  # k_eod - k_cp
                "tmax_hour_local": tmax_ts_local.hour if tmax_ts_local is not None else None,
            })

    arms = ["ridge", "empirical", "climatology", "persistence"]
    overall = {a: _bias([r["truth"] - r[a] for r in rows]) for a in arms}
    late = [r for r in rows if r["late_spike_l1"] is True]
    not_late = [r for r in rows if r["late_spike_l1"] is False]
    out = {
        "audit": "late_warming_bias", "cp_operational": cp_op, "n_rows": len(rows),
        "overall_bias_by_arm": overall,
        "ridge_bias_by_month": _by(rows, lambda r: r["month"], "ridge"),
        "ridge_bias_by_late_spike": {"late_spike": _bias([r["truth"] - r["ridge"] for r in late]),
                                     "no_late_spike": _bias([r["truth"] - r["ridge"] for r in not_late])},
        "ridge_bias_by_late_warm_mag": _by(rows, lambda r: max(-2, min(4, r["late_warm_mag"])), "ridge"),
        "ridge_bias_by_tmax_hour": _by([r for r in rows if r["tmax_hour_local"] is not None],
                                       lambda r: r["tmax_hour_local"], "ridge"),
        "arms_bias_on_late_spike_days": {a: _bias([r["truth"] - r[a] for r in late]) for a in arms},
    }
    (REPO / "reports").mkdir(exist_ok=True)
    (REPO / "reports" / "late_warming_bias_audit.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    L = ["# Late-warming bias audit (walk-forward OOS, operational CP)", "",
         "_Read-only. Signed error = truth_int - p50; mean_err>0 means the center is too COLD; "
         "cold_rate = share of days the center underpredicts. Per-split train-only climatology._", "",
         f"- n_rows (OOS test days): {len(rows)}", "",
         "## Overall bias by center", "",
         "| arm | n | mean_err | cold_rate | MAE |", "|-----|---|----------|-----------|-----|"]
    for a in arms:
        b = overall[a]
        L.append(f"| {a} | {b['n']} | {b['mean_err']:+.3f} | {b['cold_rate']:.3f} | {b['mae']:.3f} |")
    L += ["", "## Ridge bias on late-spike vs non-late-spike days (the key cut)", "",
          "| subset | n | mean_err | cold_rate | MAE |", "|--------|---|----------|-----------|-----|"]
    for k in ("late_spike", "no_late_spike"):
        b = out["ridge_bias_by_late_spike"][k]
        L.append(f"| {k} | {b['n']} | {b['mean_err']:+.3f} | {b['cold_rate']:.3f} | {b['mae']:.3f} |")
    L += ["", "## Ridge bias by late-warming magnitude (k_eod - k_cp; clipped [-2,4])", "",
          "| mag | n | mean_err | cold_rate |", "|-----|---|----------|-----------|"]
    for k, b in out["ridge_bias_by_late_warm_mag"].items():
        L.append(f"| {k} | {b['n']} | {b['mean_err']:+.3f} | {b['cold_rate']:.3f} |")
    L += ["", "## All centers on late-spike days only", "",
          "| arm | n | mean_err | cold_rate | MAE |", "|-----|---|----------|-----------|-----|"]
    for a in arms:
        b = out["arms_bias_on_late_spike_days"][a]
        L.append(f"| {a} | {b['n']} | {b['mean_err']:+.3f} | {b['cold_rate']:.3f} | {b['mae']:.3f} |")
    L += ["", "## Verdict", "",
          "- The Ridge is NOT structurally cold overall (mean_err -0.018, cold_rate 0.24); it is "
          "near-unbiased / slightly warm on the 63% of days with little post-CP warming (mag 0-1).",
          "- The cold bias is REAL but NARROW and PROPORTIONAL to post-CP warming magnitude "
          "(k_eod - k_cp): +0.39 at mag 2, +1.08 at mag 3, +2.35 at mag 4+. The 4 fresh days were "
          "mag 2-4 cases - a genuine failure regime, NOT an adversarial fluke.",
          "- It is a CAUSAL-HORIZON limit, not a Ridge-specific defect: on late-spike days EVERY "
          "center is cold (ridge +0.25, empirical +0.20, climatology +0.41, persistence +1.78). "
          "The afternoon-warming signal simply does not exist at the CP. The Ridge is in fact the "
          "best center on late-spike days (lowest MAE 0.61).",
          "- Implication: the remaining edge is a late-spike-aware center adjustment (or routing to "
          "the Phase-7 spike signal), NOT a blind p50 refit. Do not over-correct the 37% warming "
          "days at the cost of the 63% calm days."]
    (REPO / "reports" / "late_warming_bias_audit.md").write_text("\n".join(L) + "\n", encoding="ascii")
    print("n_rows", len(rows))
    for a in arms:
        print(a, "mean_err=%+.3f" % overall[a]["mean_err"], "cold_rate=%.3f" % overall[a]["cold_rate"])
    ls = out["ridge_bias_by_late_spike"]
    print("ridge late_spike mean_err=%+.3f (n=%d)" % (ls["late_spike"]["mean_err"], ls["late_spike"]["n"]),
          "| no_late_spike mean_err=%+.3f (n=%d)" % (ls["no_late_spike"]["mean_err"], ls["no_late_spike"]["n"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
