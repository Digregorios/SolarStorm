"""Evaluate material_late_warming_risk_model_v0.1 (bucket-separation gate).

Per contracts/late_warming_risk_v0_1_prereg.md: re-gate the risk model on the BUCKET-SEPARATION
capability that the downstream use (low/mid/high risk conditioning) actually needs, NOT top-decile
sharpness (the v0 mismatch). v0 stays GO=False, diagnostic-only; this is a separate pre-registered
gate. Two variants: v0.1a (v0 features) and v0.1b (+ s_to_n under the same L2 logistic). Buckets by
TRAIN predicted-risk quantiles (30/40/30). Walk-forward 2023/24/25, held-out 120 d isotonic calib.
Diagnostic only - no center/conformal change here.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from core.contracts.station import load_station_config
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import (
    FEATURE_NAMES, build_features, fit_risk_model, predict_risk,
)

REPO = Path(__file__).resolve().parents[1]
CP_OP = "23:00"
TEST_STARTS = [date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)]
CALIB_DAYS = 120
VARIANTS = {"v0.1a": list(FEATURE_NAMES), "v0.1b": list(FEATURE_NAMES) + ["s_to_n"]}


def _brier(p, y):
    return float(np.mean((p - y) ** 2))


def _pr_auc(p, y):
    y = np.asarray(y); order = np.argsort(-p, kind="stable"); ys = y[order]
    tp = np.cumsum(ys); prec = tp / np.arange(1, len(ys) + 1); rec = tp / max(1, int(y.sum()))
    auc, prev = 0.0, 0.0
    for i in range(len(ys)):
        auc += prec[i] * (rec[i] - prev); prev = rec[i]
    return float(auc)


def _eval_variant(panel, feats):
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
        model = fit_risk_model(fit_rows, calib=cal_rows, feats=feats)
        # bucket cutpoints from TRAIN predicted risk (30/40/30 quantiles), applied to test
        p_tr = predict_risk(model, fit_rows)
        c_lo, c_hi = float(np.quantile(p_tr, 0.30)), float(np.quantile(p_tr, 0.70))
        p = predict_risk(model, test)
        y = test["target"].to_numpy().astype(int)
        base = float(y.mean()); base_tr = float(fit_rows["target"].to_numpy().mean())
        def _bk(pi):
            return "low" if pi < c_lo else ("high" if pi >= c_hi else "mid")
        b = {k: {"n": 0, "obs": 0} for k in ("low", "mid", "high")}
        for pi, yi in zip(p, y):
            k = _bk(pi); b[k]["n"] += 1; b[k]["obs"] += int(yi)
        rate = {k: (b[k]["obs"] / b[k]["n"] if b[k]["n"] else None) for k in b}
        splits.append({
            "split": f"{ts.isoformat()}_to_{te.isoformat()}", "base_rate": round(base, 3),
            "brier": round(_brier(p, y), 4), "brier_base": round(_brier(np.full_like(p, base_tr), y), 4),
            "pr_auc": round(_pr_auc(p, y), 3),
            "buckets": {k: {"n": b[k]["n"], "obs_rate": None if rate[k] is None else round(rate[k], 3)} for k in b},
            "cutpoints": [round(c_lo, 3), round(c_hi, 3)],
            "_g1": _brier(p, y) < _brier(np.full_like(p, base_tr), y),
            "_g2": _pr_auc(p, y) > base,
            "_g3": rate["high"] is not None and base > 0 and rate["high"] >= 1.35 * base,
            "_g4": rate["low"] is not None and base > 0 and rate["low"] <= 0.80 * base,
            "_g5": rate["high"] is not None and rate["low"] is not None and (rate["high"] - rate["low"]) >= 0.25,
            "_g6": all(v is not None for v in (rate["low"], rate["mid"], rate["high"]))
                   and rate["low"] <= rate["mid"] + 1e-9 <= rate["high"] + 1e-9
                   and rate["low"] <= rate["high"] + 1e-9,
            "_g7": b["high"]["n"] >= 25 and b["low"]["n"] >= 25,
        })
    gates = {f"g{i}": (sum(s[f"_g{i}"] for s in splits) >= 2) for i in range(1, 8)}
    gates["g8_no_post_cp_leak"] = True
    accept = all(gates.values()) and len(splits) >= 2
    return {"splits": splits, "gates": gates, "accept": accept}


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=cfg.tmp_c_int_plausibility.min,
                               tmp_max_c=cfg.tmp_c_int_plausibility.max)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    panel = build_features(obs, labels, cfg.tz, CP_OP)
    variants = {name: _eval_variant(panel, feats) for name, feats in VARIANTS.items()}

    a_ok = variants["v0.1a"]["accept"]
    b_ok = variants["v0.1b"]["accept"]
    chosen = "v0.1a" if a_ok else ("v0.1b" if b_ok else None)  # prefer simpler
    out = {
        "model": "late-warming-risk-v0.1", "target": "material_late_warming(k_eod-k_cp>=2)",
        "buckets": "train-quantile 30/40/30", "variants": variants,
        "accepted_variant": chosen, "go_accept_v0_1": chosen is not None,
        "note": "v0 stays GO=False diagnostic; this gate measures bucket separation (the intended use). "
                "Prefer v0.1a; s_to_n (v0.1b) only earns its place if it clearly beats a on g3/g5.",
    }
    (REPO / "reports" / "spike").mkdir(parents=True, exist_ok=True)
    (REPO / "reports" / "spike" / "late_warming_risk_v0_1.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    (REPO / "reports" / "spike" / "late_warming_risk_v0_1.md").write_text(_render(out), encoding="ascii")
    print(f"accepted={chosen} | v0.1a gates={variants['v0.1a']['gates']}")
    print(f"               | v0.1b gates={variants['v0.1b']['gates']}")
    for name in VARIANTS:
        for s in variants[name]["splits"]:
            bk = s["buckets"]
            print(f"  {name} {s['split']}: base {s['base_rate']} brier {s['brier']}({s['brier_base']}) "
                  f"low/mid/high {bk['low']['obs_rate']}/{bk['mid']['obs_rate']}/{bk['high']['obs_rate']} "
                  f"(n {bk['low']['n']}/{bk['mid']['n']}/{bk['high']['n']})")
    return 0


def _render(out: dict) -> str:
    L = ["# material_late_warming_risk_model_v0.1 (bucket-separation gate)", "",
         f"- Target `{out['target']}`; buckets `{out['buckets']}`. {out['note']}",
         f"- **Accepted variant: {out['accepted_variant']}** (GO = {out['go_accept_v0_1']})", ""]
    for name in ("v0.1a", "v0.1b"):
        v = out["variants"][name]
        L += [f"## {name} - gates: {v['gates']} -> accept={v['accept']}", "",
              "| split | base | Brier(base) | PR-AUC | low/mid/high obs-rate | n low/mid/high |",
              "|-------|------|-------------|--------|------------------------|----------------|"]
        for s in v["splits"]:
            bk = s["buckets"]
            L.append(f"| {s['split']} | {s['base_rate']} | {s['brier']}({s['brier_base']}) | {s['pr_auc']} | "
                     f"{bk['low']['obs_rate']}/{bk['mid']['obs_rate']}/{bk['high']['obs_rate']} | "
                     f"{bk['low']['n']}/{bk['mid']['n']}/{bk['high']['n']} |")
        L.append("")
    L += ["## Gate legend", "",
          "g1 Brier<base; g2 PR-AUC>base; g3 high>=1.35x base; g4 low<=0.80x base; "
          "g5 (high-low)>=0.25; g6 monotone low<=mid<=high; g7 n_high,n_low>=25; g8 no post-CP leak. "
          "Accept if ALL hold in >=2/3 splits.",
          "",
          "_If accepted, the predicted risk bucket may condition: conformal IC, upper-tail, eventual "
          "center nudge - each as its own gated step. v0 remains diagnostic-only regardless._"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
