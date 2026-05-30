"""Side-by-side backtest 2026-05-27..30 on fresh live data (NZWN).

Compares baseline empirical, Phase-3 Ridge, persistence and climatology at the operational CP,
on days the historical CSV does not cover (merged history + live aviationweather.gov METAR).
Reports per-arm bracket-match and IC80 coverage. Directly probes the reviewer concern that the
Ridge IC80 (Phase-3 sanity interval, NOT conformal) may be too narrow out of sample.
ASCII report to reports/backtest_may2026.md.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import fit_empirical_conditional
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.intervals import discrete_ic
from core.features.builder import build_cp_features, build_panel
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.ingest.metar_live import fetch_observations, merge_observations
from core.labels.tmax import build_tmax_labels
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_dist as ridge_dist

REPO = Path(__file__).resolve().parents[1]
TARGETS = [date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29), date(2026, 5, 30)]
CP = "23:00"


def _score(p50, lo, hi, y):
    return {"p50": int(p50), "ic80": [int(lo), int(hi)],
            "bracket_match": None if y is None else int(int(p50) == int(y)),
            "in_ic80": None if y is None else int(lo <= y <= hi)}


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    tmin, tmax = cfg.tmp_c_int_plausibility.min, cfg.tmp_c_int_plausibility.max
    hist, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=tmin, tmp_max_c=tmax)
    live, _ = fetch_observations("NZWN", hours=168, tmp_min_c=tmin, tmp_max_c=tmax)
    obs = merge_observations(hist, live)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    truth = {r["date_local"]: r["tmax_int"] for r in labels.iter_rows(named=True) if r["day_complete"]}

    rows = []
    for d in TARGETS:
        train_end = date.fromordinal(d.toordinal() - 1)
        panel = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc)
        tp = panel.filter((panel["date_local"] >= date(2020, 1, 1)) & (panel["date_local"] <= train_end))
        climo = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=train_end)
        emp = fit_empirical_conditional(tp, train_window=(date(2020, 1, 1), train_end))
        feats = build_cp_features(obs, date_local=d, cp_hhmm=CP, tz_name=cfg.tz, labels=labels)
        p10, p90 = climo.percentiles_for(d)
        sk = support_K(p10, p90, tmp_min=tmin, tmp_max=tmax)
        kcp = feats.features.get("k_cp")
        kcp_pred = int(kcp) if kcp is not None else Q(climo.tmax_dec_for(d))
        y = truth.get(d)
        arms: dict[str, dict] = {}

        # empirical
        pd_e, _ = emp.predict_dist(month=d.month, cp=CP, k_cp=kcp_pred, support_k=sk)
        lo_e, hi_e = discrete_ic(pd_e, p_low=0.10, p_high=0.90)
        arms["empirical"] = _score(max(pd_e.items(), key=lambda kv: kv[1])[0], lo_e, hi_e, y)

        # ridge (Phase 3 band-aware; clim anchor)
        rtp = build_training_panel(obs, labels, climo=climo, tz_name=cfg.tz, cp_set=[CP],
                                   dates=[r for r in panel["date_local"].unique().to_list()
                                          if r is not None and date(2020, 1, 1) <= r <= train_end])
        X = np.column_stack([rtp[c].to_numpy().astype(float) for c in FEATURE_COLUMNS])
        ytr = rtp["target_tmax_int"].to_numpy().astype(int)
        ctr = np.array([float(climo.tmax_dec_for(dd)) for dd in rtp["date_local"].to_list()])
        fr = fit_ridge_band(X, ytr, config=RidgeBandConfig(feature_columns=tuple(FEATURE_COLUMNS),
                                                           use_climatology_anchor=True), clim_train=ctr)
        xr = np.array([[float(feats.features.get(c)) if feats.features.get(c) is not None else float("nan")
                        for c in FEATURE_COLUMNS]])
        pd_r = ridge_dist(fr, xr, [sk], clim=np.array([float(climo.tmax_dec_for(d))]))[0]
        lo_r, hi_r = discrete_ic(pd_r, p_low=0.10, p_high=0.90)
        arms["ridge"] = _score(max(pd_r.items(), key=lambda kv: kv[1])[0], lo_r, hi_r, y)

        # persistence (k_cp) + climatology (point arms; IC = point for bracket scoring)
        arms["persistence"] = _score(kcp_pred, kcp_pred, kcp_pred, y)
        kc = Q(climo.tmax_dec_for(d))
        arms["climatology"] = _score(kc, kc, kc, y)

        rows.append({"date": d.isoformat(), "k_cp": None if kcp is None else int(kcp),
                     "truth_int": None if y is None else int(y), "arms": arms})

    arm_names = ["empirical", "ridge", "persistence", "climatology"]
    n = sum(1 for r in rows if r["truth_int"] is not None)
    summary = {a: {"bracket_match": sum(r["arms"][a]["bracket_match"] for r in rows if r["truth_int"] is not None) / n,
                   "ic80_coverage": sum(r["arms"][a]["in_ic80"] for r in rows if r["truth_int"] is not None) / n}
               for a in arm_names}
    out = {"target_cp": CP, "n_scored": n, "summary": summary, "rows": rows}

    (REPO / "reports").mkdir(exist_ok=True)
    (REPO / "reports" / "backtest_may2026.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii")
    L = ["# Side-by-side backtest 2026-05-27..30 (merged history+live, @ CP 23:00)", "",
         f"- n_scored: {n}", "",
         "| arm | bracket-match | IC80 coverage |", "|-----|---------------|---------------|"]
    for a in arm_names:
        L.append(f"| {a} | {summary[a]['bracket_match']:.2f} | {summary[a]['ic80_coverage']:.2f} |")
    L += ["", "| date | truth | empirical p50/IC80 | ridge p50/IC80 | persistence | climatology |",
          "|------|-------|--------------------|----------------|-------------|-------------|"]
    for r in rows:
        a = r["arms"]
        L.append(f"| {r['date']} | {r['truth_int']} | {a['empirical']['p50']}/{a['empirical']['ic80']} | "
                 f"{a['ridge']['p50']}/{a['ridge']['ic80']} | {a['persistence']['p50']} | {a['climatology']['p50']} |")
    L += ["", "_NOTE: Ridge IC80 is the Phase-3 sanity interval (p50 +/- discrete_ic), NOT conformal; "
          "narrow out-of-sample coverage here is expected and is exactly why Ridge is not promoted as "
          "default before conformal/coverage validation._"]
    (REPO / "reports" / "backtest_may2026.md").write_text("\n".join(L) + "\n", encoding="ascii")
    for a in arm_names:
        print(f"{a}: bracket-match {summary[a]['bracket_match']:.2f}  IC80 cov {summary[a]['ic80_coverage']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
