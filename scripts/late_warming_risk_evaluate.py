"""Evaluate material_late_warming_risk_model_v0 (Etapa 5): walk-forward, calibrated, gated.

Predicts P(k_eod-k_cp>=2) at the operational CP from the 3 gate-passing precursors + season.
Walk-forward test years 2023/2024/2025; within each, the last 120 d of train is held out as the
isotonic CALIB set (the model never fits on it). Emits the full metric battery (Brier, PR-AUC,
ROC-AUC, reliability by decile, lift@top-decile, risk buckets) per split + an explicit GO gate.
DIAGNOSTIC only: nothing here touches the center p50 or conformal.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from core.contracts.station import load_station_config
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import (
    FEATURE_NAMES, RISK_MODEL_VERSION, build_features, fit_risk_model, predict_risk, risk_bucket,
)

REPO = Path(__file__).resolve().parents[1]
CP_OP = "23:00"
TEST_STARTS = [date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)]
CALIB_DAYS = 120


def _brier(p, y):
    return float(np.mean((p - y) ** 2))


def _roc_auc(p, y):
    y = np.asarray(y)
    n1, n0 = int(y.sum()), int((1 - y).sum())
    if n1 == 0 or n0 == 0:
        return None
    order = np.argsort(p, kind="stable")
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _pr_auc(p, y):
    y = np.asarray(y)
    order = np.argsort(-p, kind="stable")
    ys = y[order]
    tp = np.cumsum(ys)
    prec = tp / np.arange(1, len(ys) + 1)
    rec = tp / max(1, int(y.sum()))
    # step integral over recall
    auc, prev_r = 0.0, 0.0
    for i in range(len(ys)):
        auc += prec[i] * (rec[i] - prev_r)
        prev_r = rec[i]
    return float(auc)


def _reliability(p, y, bins=5):
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for b in range(bins):
        m = (p > edges[b]) & (p <= edges[b + 1]) if b > 0 else (p >= edges[b]) & (p <= edges[b + 1])
        if m.sum() == 0:
            continue
        out.append({"bin": f"{edges[b]:.1f}-{edges[b+1]:.1f}", "n": int(m.sum()),
                    "mean_pred": round(float(p[m].mean()), 3), "obs_rate": round(float(y[m].mean()), 3)})
    return out


def _top_decile_lift(p, y, base):
    n = max(1, int(round(0.10 * len(p))))
    order = np.argsort(-p, kind="stable")[:n]
    rate = float(y[order].mean())
    return (rate / base) if base > 0 else None, rate


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
        model = fit_risk_model(fit_rows, calib=cal_rows)
        p = predict_risk(model, test)
        y = test["target"].to_numpy().astype(int)
        base = float(y.mean())
        base_train = float(fit_rows["target"].to_numpy().mean())
        lift, top_rate = _top_decile_lift(p, y, base)
        buckets = {b: {"n": 0, "obs": 0} for b in ("low", "mid", "high")}
        for pi, yi in zip(p, y):
            bk = risk_bucket(float(pi))
            buckets[bk]["n"] += 1
            buckets[bk]["obs"] += int(yi)
        bucket_rate = {b: (v["obs"] / v["n"] if v["n"] else None) for b, v in buckets.items()}
        low_ok = (bucket_rate["low"] is not None and base > 0 and bucket_rate["low"] <= 0.8 * base)
        splits.append({
            "split": f"{ts.isoformat()}_to_{te.isoformat()}",
            "n_fit": int(fit_rows.height), "n_calib": int(cal_rows.height), "n_test": int(test.height),
            "base_rate_test": round(base, 3), "base_rate_train": round(base_train, 3),
            "brier": round(_brier(p, y), 4), "brier_base": round(_brier(np.full_like(p, base_train), y), 4),
            "roc_auc": None if _roc_auc(p, y) is None else round(_roc_auc(p, y), 3),
            "pr_auc": round(_pr_auc(p, y), 3),
            "top_decile_lift": None if lift is None else round(lift, 2),
            "top_decile_rate": round(top_rate, 3),
            "risk_buckets": {b: {"n": buckets[b]["n"], "obs_rate": None if bucket_rate[b] is None else round(bucket_rate[b], 3)} for b in buckets},
            "reliability": _reliability(p, y),
            "_brier_better": _brier(p, y) < _brier(np.full_like(p, base_train), y),
            "_pr_gt_base": _pr_auc(p, y) > base,
            "_lift_ge_14": (lift is not None and lift >= 1.4),
            "_low_le_08base": low_ok,
        })

    n = len(splits)
    g1 = sum(s["_brier_better"] for s in splits) >= 2
    g2 = sum(s["_pr_gt_base"] for s in splits) >= 2
    g3 = sum(s["_lift_ge_14"] for s in splits) >= 2
    g4 = sum(s["_low_le_08base"] for s in splits) >= 2
    # g5: reliability monotone (bucket obs_rate low<=mid<=high) in >=2/3
    def _mono(s):
        r = s["risk_buckets"]
        vals = [r[b]["obs_rate"] for b in ("low", "mid", "high") if r[b]["obs_rate"] is not None]
        return all(vals[i] <= vals[i + 1] + 1e-9 for i in range(len(vals) - 1))
    g5 = sum(_mono(s) for s in splits) >= 2
    go = bool(g1 and g2 and g3 and g4 and g5)
    out = {
        "model": RISK_MODEL_VERSION, "target": "material_late_warming(k_eod-k_cp>=2)",
        "cp_operational": CP_OP, "features": list(FEATURE_NAMES),
        "calib_days": CALIB_DAYS, "splits": splits,
        "gate": {
            "g1_brier_better_than_baserate": g1, "g2_pr_auc_gt_base": g2,
            "g3_top_decile_lift_ge_1.4": g3, "g4_low_bucket_le_0.8base": g4,
            "g5_bucket_reliability_monotone": g5,
            "g6_no_post_cp_timestamps": True,  # enforced by build_features (ts<cp) + unit test
        },
        "go_accept_v0": go,
        "usage": "DIAGNOSTIC only (prob + risk_bucket); does NOT modify p50 or conformal here.",
    }
    (REPO / "reports" / "spike").mkdir(parents=True, exist_ok=True)
    (REPO / "reports" / "spike" / "late_warming_risk_v0.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    (REPO / "reports" / "spike" / "late_warming_risk_v0.md").write_text(_render(out), encoding="ascii")
    print(f"GO={go} | gates g1..g5 = {g1}/{g2}/{g3}/{g4}/{g5}")
    for s in splits:
        rb = s["risk_buckets"]
        print(f"  {s['split']}: brier {s['brier']} (base {s['brier_base']}) pr_auc {s['pr_auc']} "
              f"roc {s['roc_auc']} lift@10 {s['top_decile_lift']} | buckets "
              f"low {rb['low']['obs_rate']} mid {rb['mid']['obs_rate']} high {rb['high']['obs_rate']}")
    # GO=False is an HONEST diagnostic outcome, not a run failure -> exit 0 once the report is
    # written (so CI/automation does not read 'experiment did not pass' as 'script broke').
    return 0


def _render(out: dict) -> str:
    L = ["# material_late_warming_risk_model_v0 (Etapa 5; walk-forward, calibrated)", "",
         f"- Model: `{out['model']}`; target `{out['target']}`; CP `{out['cp_operational']}`.",
         f"- Features (causal, pre-CP): `{', '.join(out['features'])}`. Calib held-out {out['calib_days']} d (isotonic).",
         f"- Usage: {out['usage']}", "",
         "## Per-split metrics", "",
         "| split | base | Brier (base) | PR-AUC | ROC-AUC | lift@10% | low/mid/high obs-rate |",
         "|-------|------|--------------|--------|---------|----------|------------------------|"]
    for s in out["splits"]:
        rb = s["risk_buckets"]
        L.append(f"| {s['split']} | {s['base_rate_test']} | {s['brier']} ({s['brier_base']}) | "
                 f"{s['pr_auc']} | {s['roc_auc']} | {s['top_decile_lift']} | "
                 f"{rb['low']['obs_rate']} / {rb['mid']['obs_rate']} / {rb['high']['obs_rate']} |")
    g = out["gate"]
    L += ["", "## GO gate (accept v0 only if all pass in >=2/3 splits)", "",
          f"- g1 Brier < base-rate Brier: **{g['g1_brier_better_than_baserate']}**",
          f"- g2 PR-AUC > base rate: **{g['g2_pr_auc_gt_base']}**",
          f"- g3 top-decile lift >= 1.4: **{g['g3_top_decile_lift_ge_1.4']}**",
          f"- g4 low bucket <= 0.8x base: **{g['g4_low_bucket_le_0.8base']}**",
          f"- g5 bucket reliability monotone (low<=mid<=high): **{g['g5_bucket_reliability_monotone']}**",
          f"- g6 no post-CP timestamps: **{g['g6_no_post_cp_timestamps']}** (build_features uses ts<cp; unit-tested)",
          "", f"## Verdict: ACCEPT risk_model_v0 = **{out['go_accept_v0']}**", "",
          "_If accepted, the next uses are: (1) conditional conformal by PREDICTED risk bucket; "
          "(2) upper-tail adjustment conditioned on risk; (3) light center nudge ONLY if it improves "
          "RPS/MAE without degrading calm days. None done here - this is a diagnostic detector._"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
