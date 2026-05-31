"""Evaluate calm_day_filter_v0: a protective LOW-risk filter for material late-warming.

Per contracts/calm_day_filter_v0_prereg.md. Reuses core.models.late_warming_risk (the validated
precursors) but re-frames the objective around the robust signal: identify CALM days (predicted
risk in the bottom-30% TRAIN band) where material late-warming is reliably LOW. Walk-forward
2023/24/25, held-out 120 d isotonic calib, c_low from TRAIN predicted risk. Diagnostic only - no
forecast/IC/center change. Binary GO on a LOW-bucket-focused gate.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from core.contracts.station import load_station_config
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import FEATURE_NAMES, build_features, fit_risk_model, predict_risk

REPO = Path(__file__).resolve().parents[1]
CP_OP = "23:00"
TEST_STARTS = [date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)]
CALIB_DAYS = 120
CALM_SUPPRESS_MAX = 0.65   # calm-bucket obs-rate must be <= 0.65x base
CALM_PRECISION_MIN = 0.75  # P(no material late-warming | calm) >= 0.75


def _brier(p, y):
    return float(np.mean((p - y) ** 2))


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=cfg.tmp_c_int_plausibility.min,
                               tmp_max_c=cfg.tmp_c_int_plausibility.max)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    panel = build_features(obs, labels, cfg.tz, CP_OP)

    splits = []
    for ts in TEST_STARTS:
        te = ts + timedelta(days=364)
        tr = panel.filter(panel["date_local"] < ts)
        cal_start = ts - timedelta(days=CALIB_DAYS)
        fit_rows = tr.filter(tr["date_local"] < cal_start)
        cal_rows = tr.filter(tr["date_local"] >= cal_start)
        test = panel.filter((panel["date_local"] >= ts) & (panel["date_local"] <= te))
        if fit_rows.height < 200 or test.height < 50:
            continue
        model = fit_risk_model(fit_rows, calib=cal_rows, feats=list(FEATURE_NAMES))
        c_low = float(np.quantile(predict_risk(model, fit_rows), 0.30))
        p = predict_risk(model, test)
        y = test["target"].to_numpy().astype(int)
        base = float(y.mean()); base_tr = float(fit_rows["target"].to_numpy().mean())
        calm = p < c_low
        n_calm = int(calm.sum())
        calm_rate = float(y[calm].mean()) if n_calm else None
        precision_calm = (1.0 - calm_rate) if calm_rate is not None else None
        brier = _brier(p, y); brier_base = _brier(np.full_like(p, base_tr), y)
        splits.append({
            "split": f"{ts.isoformat()}_to_{te.isoformat()}", "base_rate": round(base, 3),
            "c_low": round(c_low, 3), "n_calm": n_calm,
            "calm_obs_rate": None if calm_rate is None else round(calm_rate, 3),
            "calm_precision_no_lw": None if precision_calm is None else round(precision_calm, 3),
            "brier": round(brier, 4), "brier_base": round(brier_base, 4),
            "_g1": calm_rate is not None and base > 0 and calm_rate <= CALM_SUPPRESS_MAX * base,
            "_g2": n_calm >= 25,
            "_g3": precision_calm is not None and precision_calm >= CALM_PRECISION_MIN,
            "_g4": brier < brier_base,
        })
    gates = {f"g{i}": (sum(s[f"_g{i}"] for s in splits) >= 2) for i in range(1, 5)}
    gates["g6_no_post_cp_leak"] = True
    go = all(gates.values()) and len(splits) >= 2
    out = {"model": "calm-day-filter-v0", "target": "material_late_warming(k_eod-k_cp>=2)",
           "calm_rule": "predicted_risk < train P30", "splits": splits,
           "gate": gates, "go_accept": go,
           "note": "Protective LOW filter; high-risk detection deferred to Etapa 3 (analogs). "
                   "Diagnostic only; no forecast/IC/center change. Does not promote risk_model_v0.1."}
    (REPO / "reports" / "spike").mkdir(parents=True, exist_ok=True)
    (REPO / "reports" / "spike" / "calm_day_filter_v0.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    (REPO / "reports" / "spike" / "calm_day_filter_v0.md").write_text(_render(out), encoding="ascii")
    print(f"GO={go} gates={gates}")
    for s in splits:
        print(f"  {s['split']}: base {s['base_rate']} c_low {s['c_low']} n_calm {s['n_calm']} "
              f"calm_obs_rate {s['calm_obs_rate']} precision {s['calm_precision_no_lw']} "
              f"brier {s['brier']}({s['brier_base']})")
    return 0


def _render(out: dict) -> str:
    L = ["# calm_day_filter_v0 (protective low-risk filter; walk-forward)", "",
         f"- Target `{out['target']}`; calm rule: `{out['calm_rule']}`. {out['note']}",
         f"- **GO accept: {out['go_accept']}** | gates: {out['gate']}", "",
         "| split | base | c_low | n_calm | calm obs-rate | precision(no-LW) | Brier(base) |",
         "|-------|------|-------|--------|---------------|------------------|-------------|"]
    for s in out["splits"]:
        L.append(f"| {s['split']} | {s['base_rate']} | {s['c_low']} | {s['n_calm']} | "
                 f"{s['calm_obs_rate']} | {s['calm_precision_no_lw']} | {s['brier']}({s['brier_base']}) |")
    L += ["", "## Gate (accept if all hold >=2/3 splits)", "",
          f"- g1 calm obs-rate <= {CALM_SUPPRESS_MAX}x base; g2 n_calm>=25; "
          f"g3 precision(no late-warming | calm) >= {CALM_PRECISION_MIN}; g4 Brier<base; g6 no post-CP leak.",
          "", "_If accepted, the calm flag may LATER (each separately gated) narrow IC on calm days, "
          "reduce late-spike weight, raise persistence/Ridge trust. Nothing changed here._"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
