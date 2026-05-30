"""Clean backtest 2026-05-27..30 on fresh live data (NZWN).

Merges the historical IEM CSV with live aviationweather.gov observations, then for each target
day emits the baseline empirical-conditional forecast at the operational CP (training strictly
on data <= D-1) and compares p50/IC80 against the realized integer Tmax. Bracket-match = p50 hits
the realized bracket. ASCII report to reports/backtest_may2026.md.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import fit_empirical_conditional
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.intervals import discrete_ic
from core.features.builder import build_cp_features, build_panel
from core.ingest.iem_csv import load_observations
from core.ingest.metar_live import fetch_observations, merge_observations
from core.labels.tmax import build_tmax_labels

REPO = Path(__file__).resolve().parents[1]
TARGETS = [date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29), date(2026, 5, 30)]
CP = "23:00"


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    tmin, tmax = cfg.tmp_c_int_plausibility.min, cfg.tmp_c_int_plausibility.max
    hist, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=tmin, tmp_max_c=tmax)
    live, _ = fetch_observations("NZWN", hours=168, tmp_min_c=tmin, tmp_max_c=tmax)
    obs = merge_observations(hist, live)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    truth = {r["date_local"]: r["tmax_int"] for r in labels.iter_rows(named=True)
             if r["day_complete"]}

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
        pd_, src = emp.predict_dist(month=d.month, cp=CP, k_cp=kcp_pred, support_k=sk)
        p50 = max(pd_.items(), key=lambda kv: kv[1])[0]
        lo, hi = discrete_ic(pd_, p_low=0.10, p_high=0.90)
        y = truth.get(d)
        rows.append({
            "date": d.isoformat(), "p50_int": int(p50), "ic80": [int(lo), int(hi)],
            "k_cp": None if kcp is None else int(kcp), "truth_int": None if y is None else int(y),
            "bracket_match": None if y is None else int(int(p50) == int(y)),
            "in_ic80": None if y is None else int(lo <= y <= hi), "src": src,
        })

    n = sum(1 for r in rows if r["truth_int"] is not None)
    hits = sum(r["bracket_match"] for r in rows if r["bracket_match"] is not None)
    cov = sum(r["in_ic80"] for r in rows if r["in_ic80"] is not None)
    out = {"target_cp": CP, "n_scored": n, "bracket_match": (hits / n) if n else None,
           "ic80_coverage": (cov / n) if n else None, "rows": rows}

    (REPO / "reports").mkdir(exist_ok=True)
    (REPO / "reports" / "backtest_may2026.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii")
    L = ["# Clean backtest 2026-05-27..30 (live data, baseline empirical @ CP 23:00)", "",
         f"- n_scored: {n}  bracket-match: {out['bracket_match']}  IC80 coverage: {out['ic80_coverage']}", "",
         "| date | k_cp | p50 | IC80 | truth | bracket_match | in_IC80 | src |",
         "|------|------|-----|------|-------|---------------|---------|-----|"]
    for r in rows:
        L.append(f"| {r['date']} | {r['k_cp']} | {r['p50_int']} | {r['ic80']} | {r['truth_int']} | "
                 f"{r['bracket_match']} | {r['in_ic80']} | {r['src']} |")
    (REPO / "reports" / "backtest_may2026.md").write_text("\n".join(L) + "\n", encoding="ascii")
    for r in rows:
        print(r)
    print(f"bracket-match {hits}/{n}  IC80 cov {cov}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
