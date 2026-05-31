"""Etapa 2: late_warming_precursor_audit (read-only; no center model, no conformal).

Validates the Etapa-1 pre-CP precursor shortlist for ``material_late_warming = (k_eod - k_cp
>= 2)`` (base rate ~0.377) under WALK-FORWARD discipline: bucket thresholds (quartiles) are fit
on TRAIN and applied on TEST; per-feature OOS lift is measured per split and stratified by
season; a precursor PASSES an explicit gate; a binary go/no-go for a risk_model_v0 is emitted.

Terminology (reviewer correction, update.txt 2026-05-31): these are CAUSAL-ELIGIBLE / pre-CP
precursors (admissible + statistically promising), NOT proven-causal. The wind-drying proxy is
named ``drying_warming_wind_proxy`` (not "foehn") until a mechanism is isolated.

Frozen feature definitions (pre-registered here; all use ONLY obs with ts_local < cp):
  - wind_quadrant_at_cp: modal wind quadrant (N/E/S/W from drct) over [cp-3h, cp)
  - wind_quadrant_change_overnight_to_cp: overnight modal (00-06 local) -> cp modal; flag S->N
  - delta_06_to_cp: T(nearest<=cp) - T(nearest<=06:00 local)  [morning warming slope]
  - rain_persistence_path: rainy in all of {00-06, 06-09, 09-cp} windows (p01i>0 or RA/SHRA)
  - drying_warming_wind_proxy: cp quadrant in {N,W} AND delta_06_to_cp>0 AND dewpoint-depression rising
  - t_06 / tmin_so_far_06: morning level (regime indicator)
  - month_decade: (month, decade) winter spike modifier (secondary)
Targets are audit-only; never forecast inputs.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from core.contracts.station import load_station_config
from core.io.timeutil import cp_to_utc, day_local_window
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels

REPO = Path(__file__).resolve().parents[1]
CP_OP = "23:00"
TARGET_NAME = "material_late_warming(k_eod-k_cp>=2)"
TEST_STARTS = [date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)]
MIN_BUCKET_N = 25
LIFT_HI, LIFT_LO = 1.20, 0.80
_QUAD = ("N", "E", "S", "W")


def _quadrant(drct: float | None) -> str | None:
    if drct is None or (isinstance(drct, float) and np.isnan(drct)):
        return None
    d = float(drct) % 360.0
    if d >= 315 or d < 45:
        return "N"
    if d < 135:
        return "E"
    if d < 225:
        return "S"
    return "W"


def _modal(vals: list[str | None]) -> str | None:
    c: dict[str, int] = {}
    for v in vals:
        if v is not None:
            c[v] = c.get(v, 0) + 1
    return max(c.items(), key=lambda kv: kv[1])[0] if c else None


def _season(month: int) -> str:
    return {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
            6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}[month]


def _is_rain(wx: str | None, p01: float | None) -> bool:
    if p01 is not None and not (isinstance(p01, float) and np.isnan(p01)) and float(p01) > 0:
        return True
    if wx:
        u = str(wx).upper()
        return any(t in u for t in ("RA", "SHRA", "DZ", "TS"))
    return False


def _build_rows(obs: pl.DataFrame, labels: pl.DataFrame, tz: str) -> list[dict]:
    """Per day_complete day, compute frozen pre-CP precursors + the audit target."""
    obs = obs.with_columns(pl.col("ts_utc").dt.convert_time_zone(tz).alias("ts_local"))
    lab = {r["date_local"]: r for r in labels.iter_rows(named=True) if r["day_complete"]}
    rows: list[dict] = []
    for d, lr in lab.items():
        if lr["tmax_int"] is None:
            continue
        cp_utc = cp_to_utc(d, CP_OP)
        day_start, _ = day_local_window(d, tz_name=tz)
        sub = obs.filter((pl.col("ts_utc") >= day_start) & (pl.col("ts_utc") < cp_utc)).sort("ts_utc")
        if sub.height < 6:
            continue
        loc_h = sub["ts_local"].dt.hour().to_list()
        drct = sub["drct"].to_list()
        tmpf = sub["tmpf"].to_list()
        dwpf = sub["dwpf"].to_list()
        wx = sub["wxcodes"].to_list() if "wxcodes" in sub.columns else [None] * sub.height
        p01 = sub["p01i"].to_list() if "p01i" in sub.columns else [None] * sub.height
        tmp_c = sub["tmp_c_int"].to_list()

        def _win(lo, hi):
            return [i for i, h in enumerate(loc_h) if lo <= h < hi]

        i_overnight = _win(0, 6)
        i_cp = [i for i, h in enumerate(loc_h) if h >= max(0, (loc_h[-1] - 3))]  # last ~3h before cp
        q_overnight = _modal([_quadrant(drct[i]) for i in i_overnight]) if i_overnight else None
        q_cp = _modal([_quadrant(drct[i]) for i in i_cp]) if i_cp else None
        s_to_n = (q_overnight == "S" and q_cp == "N")
        # morning slope: T at nearest<=06 vs T at last pre-cp
        t06 = next((tmp_c[i] for i in reversed(range(len(loc_h))) if loc_h[i] <= 6 and tmp_c[i] is not None), None)
        t_cp = next((v for v in reversed(tmp_c) if v is not None), None)
        delta_06_cp = (t_cp - t06) if (t06 is not None and t_cp is not None) else None
        # rain persistence across the 3 windows
        def _rain_win(idxs):
            return any(_is_rain(wx[i], p01[i]) for i in idxs) if idxs else False
        rain_path = _rain_win(i_overnight) and _rain_win(_win(6, 9)) and _rain_win(_win(9, 24))
        # dewpoint depression trend (rising = drying)
        dd = [(tmpf[i] - dwpf[i]) for i in range(len(loc_h))
              if tmpf[i] is not None and dwpf[i] is not None]
        dd_rising = (len(dd) >= 2 and dd[-1] > dd[0])
        drying_warming = (q_cp in ("N", "W")) and (delta_06_cp is not None and delta_06_cp > 0) and dd_rising
        k_cp = lr.get(f"late_spike_l1__cp_{CP_OP[:2]}")  # not k_cp; recompute below
        # k_cp = max tmp before cp; k_eod = tmax_int
        kcp = max((v for v in tmp_c if v is not None), default=None)
        if kcp is None:
            continue
        target = int((int(lr["tmax_int"]) - int(kcp)) >= 2)
        rows.append({
            "date": d, "month": d.month, "decade": min(3, (d.day - 1) // 10 + 1),
            "season": _season(d.month), "target": target,
            "wind_quadrant_at_cp": q_cp, "s_to_n": int(s_to_n),
            "delta_06_to_cp": delta_06_cp, "rain_persistence_path": int(rain_path),
            "drying_warming_wind_proxy": int(drying_warming),
            "t_06": float(t06) if t06 is not None else None,
        })
    return rows


def _lift_binary(train: list[dict], test: list[dict], key: str, want: str) -> dict:
    """Lift of P(target | flag==1) vs base, OOS. ``want`` = 'enhance' or 'suppress'."""
    base = float(np.mean([r["target"] for r in test])) if test else 0.0
    bucket = [r["target"] for r in test if r[key] == 1]
    n = len(bucket)
    rate = float(np.mean(bucket)) if n else None
    lift = (rate / base) if (rate is not None and base > 0) else None
    passed = bool(n >= MIN_BUCKET_N and lift is not None and (
        lift >= LIFT_HI if want == "enhance" else lift <= LIFT_LO))
    return {"base_rate_test": round(base, 3), "rate_in_bucket": None if rate is None else round(rate, 3),
            "lift": None if lift is None else round(lift, 3), "n_bucket": n, "want": want, "passed": passed}


def _lift_quartile(train: list[dict], test: list[dict], key: str, want: str) -> dict:
    """Top/bottom quartile of a continuous feature; threshold fit on TRAIN, applied on TEST."""
    tr = [r[key] for r in train if r[key] is not None]
    if len(tr) < 50:
        return {"passed": False, "reason": "insufficient_train"}
    q = float(np.quantile(tr, 0.75 if want == "enhance" else 0.25))
    base = float(np.mean([r["target"] for r in test])) if test else 0.0
    if want == "enhance":
        bucket = [r["target"] for r in test if r[key] is not None and r[key] >= q]
    else:
        bucket = [r["target"] for r in test if r[key] is not None and r[key] <= q]
    n = len(bucket)
    rate = float(np.mean(bucket)) if n else None
    lift = (rate / base) if (rate is not None and base > 0) else None
    passed = bool(n >= MIN_BUCKET_N and lift is not None and (
        lift >= LIFT_HI if want == "enhance" else lift <= LIFT_LO))
    return {"train_threshold": round(q, 2), "base_rate_test": round(base, 3),
            "rate_in_bucket": None if rate is None else round(rate, 3),
            "lift": None if lift is None else round(lift, 3), "n_bucket": n, "want": want, "passed": passed}


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=cfg.tmp_c_int_plausibility.min,
                               tmp_max_c=cfg.tmp_c_int_plausibility.max)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    rows = _build_rows(obs, labels, cfg.tz)

    # Feature registry: (name, kind, key, want)
    feats = [
        ("wind_quadrant_change_S_to_N", "binary", "s_to_n", "enhance"),
        ("delta_06_to_cp_top_quartile", "quartile", "delta_06_to_cp", "enhance"),
        ("wind_quadrant_at_cp_S", "binary_eq", ("wind_quadrant_at_cp", "S"), "suppress"),
        ("rain_persistence_path", "binary", "rain_persistence_path", "suppress"),
        ("drying_warming_wind_proxy", "binary", "drying_warming_wind_proxy", "enhance"),
        ("t_06_bottom_quartile", "quartile", "t_06", "enhance"),
    ]
    splits = []
    for ts in TEST_STARTS:
        te = ts + timedelta(days=364)
        splits.append((ts, te))

    results = []
    for name, kind, key, want in feats:
        per_split = []
        for ts, te in splits:
            train = [r for r in rows if r["date"] < ts]
            test = [r for r in rows if ts <= r["date"] <= te]
            if kind == "binary":
                per_split.append(_lift_binary(train, test, key, want))
            elif kind == "binary_eq":
                col, val = key
                tr2 = [{**r, "_f": int(r[col] == val)} for r in train]
                te2 = [{**r, "_f": int(r[col] == val)} for r in test]
                per_split.append(_lift_binary(tr2, te2, "_f", want))
            else:
                per_split.append(_lift_quartile(train, test, key, want))
        n_pass = sum(1 for p in per_split if p.get("passed"))
        # season-stratified lift (descriptive, full-history) for the binary/eq feats
        season_cut = {}
        for s in ("DJF", "MAM", "JJA", "SON"):
            sr = [r for r in rows if r["season"] == s]
            if not sr:
                continue
            base = float(np.mean([r["target"] for r in sr]))
            if kind == "binary":
                bk = [r["target"] for r in sr if r[key] == 1]
            elif kind == "binary_eq":
                col, val = key
                bk = [r["target"] for r in sr if r[col] == val]
            else:
                tr = [r[key] for r in sr if r[key] is not None]
                if len(tr) < 20:
                    continue
                q = float(np.quantile(tr, 0.75 if want == "enhance" else 0.25))
                bk = [r["target"] for r in sr if r[key] is not None and (
                    r[key] >= q if want == "enhance" else r[key] <= q)]
            season_cut[s] = {"base": round(base, 3), "n_bucket": len(bk),
                             "lift": round((np.mean(bk) / base), 3) if (bk and base > 0) else None}
        results.append({"feature": name, "want": want, "n_splits_passed": n_pass,
                        "per_split": per_split, "season_lift": season_cut,
                        "gate_passed": n_pass >= 2})

    n_primary_pass = sum(1 for r in results if r["gate_passed"]
                         and r["feature"] in ("wind_quadrant_change_S_to_N",
                                              "delta_06_to_cp_top_quartile",
                                              "wind_quadrant_at_cp_S", "rain_persistence_path"))
    go = n_primary_pass >= 2
    out = {
        "audit": "late_warming_precursor", "target": TARGET_NAME, "cp_operational": CP_OP,
        "n_days": len(rows), "base_rate": round(float(np.mean([r["target"] for r in rows])), 3),
        "split_protocol": "thresholds fit on TRAIN (<test_start), applied on TEST year; lift OOS",
        "gate": {"lift_hi": LIFT_HI, "lift_lo": LIFT_LO, "min_bucket_n": MIN_BUCKET_N,
                 "pass_rule": "expected-direction lift in >=2/3 splits"},
        "features": results,
        "n_primary_passed": n_primary_pass,
        "go_build_risk_model_v0": go,
        "terminology_note": "causal-eligible / pre-CP precursors, NOT proven-causal; "
                            "drying_warming_wind_proxy (not foehn) until mechanism isolated",
    }
    (REPO / "reports" / "spike").mkdir(parents=True, exist_ok=True)
    (REPO / "reports" / "spike" / "late_warming_precursor_audit.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    (REPO / "reports" / "spike" / "late_warming_precursor_audit.md").write_text(_render(out), encoding="ascii")
    print(f"n_days={len(rows)} base_rate={out['base_rate']} primary_passed={n_primary_pass} GO={go}")
    for r in results:
        lifts = "/".join("." if p.get("lift") is None else f"{p['lift']:.2f}" for p in r["per_split"])
        print(f"  {r['feature']} ({r['want']}): splits_passed={r['n_splits_passed']} lifts={lifts} gate={r['gate_passed']}")
    return 0


def _render(out: dict) -> str:
    L = ["# Late-warming precursor audit (Etapa 2; read-only, walk-forward)", "",
         "## 1. Preregistration",
         f"- Target (audit-only): `{out['target']}`; base rate `{out['base_rate']}` over `{out['n_days']}` days.",
         f"- Split protocol: {out['split_protocol']}. Test years 2023/2024/2025.",
         f"- Gate: expected-direction lift in >=2/3 splits; lift>= {out['gate']['lift_hi']} (enhance) "
         f"or <= {out['gate']['lift_lo']} (suppress); n_bucket >= {out['gate']['min_bucket_n']}/split.",
         f"- Terminology: {out['terminology_note']}.",
         "- No center model, no conformal-by-bucket here. Features use only obs with ts < CP.", "",
         "## 5. Single-feature OOS lift (per split) + gate", "",
         "| feature | want | split lifts (2023/24/25) | n_bucket (per split) | splits passed | GATE |",
         "|---------|------|--------------------------|----------------------|---------------|------|"]
    for r in out["features"]:
        lifts = " / ".join("-" if p.get("lift") is None else f"{p['lift']:.2f}" for p in r["per_split"])
        ns = " / ".join(str(p.get("n_bucket", "-")) for p in r["per_split"])
        L.append(f"| {r['feature']} | {r['want']} | {lifts} | {ns} | {r['n_splits_passed']}/3 | "
                 f"{'PASS' if r['gate_passed'] else 'fail'} |")
    L += ["", "## 6. Season-stratified lift (descriptive, full history)", "",
          "| feature | DJF | MAM | JJA | SON |", "|---------|-----|-----|-----|-----|"]
    for r in out["features"]:
        sc = r["season_lift"]
        def _c(s):
            v = sc.get(s, {})
            return "-" if v.get("lift") is None else f"{v['lift']:.2f}(n{v['n_bucket']})"
        L.append(f"| {r['feature']} | {_c('DJF')} | {_c('MAM')} | {_c('JJA')} | {_c('SON')} |")
    passed = [r["feature"] for r in out["features"] if r["gate_passed"]]
    failed = [r["feature"] for r in out["features"] if not r["gate_passed"]]
    L += ["", "## 9. Passed / failed precursors", "",
          f"- PASSED ({len(passed)}): {', '.join(passed) if passed else 'none'}",
          f"- FAILED ({len(failed)}): {', '.join(failed) if failed else 'none'}",
          "", "## 10. Recommendation - binary go/no-go for material_late_warming_risk_model_v0", "",
          f"- Primary precursors passing the gate: **{out['n_primary_passed']}** "
          "(of 4: S->N change, delta_06_to_cp, southerly-at-CP, rain-persistence).",
          f"- **GO build risk_model_v0: {out['go_build_risk_model_v0']}** "
          "(rule: >=2 primary precursors survive walk-forward).",
          "",
          "_Note: season-stratified lift is descriptive (full-history); the GATE uses the OOS "
          "per-split protocol. Small-n high-lift signals (e.g. S->N) may pass as candidates without "
          "being standalone features. No feature promoted to the forecast here._"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
