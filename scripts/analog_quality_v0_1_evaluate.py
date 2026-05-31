"""analog_quality_v0.1: operationalize the g5 adherence gate without changing retrieval.

Per contracts/analog_quality_v0_1_prereg.md. Same causal k-NN as analog_retrieval_audit_v0
(K=50, alpha=1, 7-feature train-fit distance, train-only pool date<test). Tests 3 candidate
analog_quality metrics (analog_confidence, effective_n, weighted_mean_dist); the high-quality
bucket (split by TRAIN self-query median of the metric) must beat the low-quality bucket on BOTH
Brier (g5a) and within-bucket top-decile lift (g5b), in >=2/3 splits. Read-only.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from core.contracts.station import load_station_config
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import build_features

REPO = Path(__file__).resolve().parents[1]
CP_OP = "23:00"
TEST_STARTS = [date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)]
K = 50
ALPHA = 1.0
DIST_FEATS = ("k_cp", "delta_06_to_cp", "southerly_at_cp", "rain_persistence_path",
              "s_to_n", "month_sin", "month_cos")
METRICS = ("analog_confidence", "effective_n", "weighted_mean_dist")


def _brier(p, y):
    return float(np.mean((p - y) ** 2))


def _lift10(p, y, base):
    if len(p) < 10 or base <= 0:
        return None
    n = max(1, int(round(0.10 * len(p))))
    top = np.argsort(-p, kind="stable")[:n]
    return float(y[top].mean()) / base


def _matrix(df):
    return np.column_stack([df[c].to_numpy().astype(float) for c in DIST_FEATS])


def _neighbor_stats(Zq, Ztr, ytr, base_tr, s):
    """For each query row: P_analog + the 3 quality metrics over K neighbors."""
    n = Zq.shape[0]
    p = np.empty(n); conf = np.empty(n); effn = np.empty(n); wmd = np.empty(n)
    for i in range(n):
        d2 = np.sum((Ztr - Zq[i]) ** 2, axis=1)
        idx = np.argpartition(d2, K)[:K]
        dk = np.sqrt(d2[idx])
        p[i] = (ytr[idx].sum() + ALPHA) / (K + 2 * ALPHA)
        conf[i] = abs(p[i] - base_tr)
        w = np.exp(-dk / s) if s > 0 else np.ones_like(dk)
        effn[i] = (w.sum() ** 2) / max(1e-9, np.sum(w ** 2))
        wmd[i] = float(np.sum(w * dk) / max(1e-9, w.sum()))
    return p, {"analog_confidence": conf, "effective_n": effn, "weighted_mean_dist": wmd}


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    obs, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=cfg.tmp_c_int_plausibility.min,
                               tmp_max_c=cfg.tmp_c_int_plausibility.max)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    panel = build_features(obs, labels, cfg.tz, CP_OP)

    per_metric = {m: [] for m in METRICS}
    for ts in TEST_STARTS:
        te = ts + timedelta(days=364)
        tr = panel.filter(panel["date_local"] < ts)
        test = panel.filter((panel["date_local"] >= ts) & (panel["date_local"] <= te))
        if tr.height < 200 or test.height < 50:
            continue
        Xtr = _matrix(tr); mean = np.nanmean(Xtr, axis=0); mean = np.where(np.isnan(mean), 0.0, mean)
        Xtr = np.where(np.isnan(Xtr), mean, Xtr); std = Xtr.std(axis=0); std = np.where(std < 1e-9, 1.0, std)
        Ztr = (Xtr - mean) / std; ytr = tr["target"].to_numpy().astype(int); base_tr = float(ytr.mean())
        Xte = _matrix(test); Xte = np.where(np.isnan(Xte), mean, Xte); Zte = (Xte - mean) / std
        yte = test["target"].to_numpy().astype(int); base = float(yte.mean())
        # s = train-fit median neighbor distance (self-query)
        md_tr = np.empty(tr.height)
        for i in range(tr.height):
            d2 = np.sum((Ztr - Ztr[i]) ** 2, axis=1); d2[i] = np.inf
            md_tr[i] = float(np.median(np.sqrt(d2[np.argpartition(d2, K)[:K]])))
        s = float(np.median(md_tr))
        # train self-query quality metrics -> per-metric high/low cutpoint
        _, q_tr = _neighbor_stats(Ztr, Ztr, ytr, base_tr, s)  # note: includes self; fine for a cutpoint
        p_te, q_te = _neighbor_stats(Zte, Ztr, ytr, base_tr, s)
        for m in METRICS:
            cut = float(np.median(q_tr[m]))
            # higher metric = higher quality for confidence/effective_n; LOWER dist = higher quality
            hi = (q_te[m] >= cut) if m != "weighted_mean_dist" else (q_te[m] <= cut)
            lo = ~hi
            if hi.sum() < 25 or lo.sum() < 25:
                per_metric[m].append({"split": ts.isoformat(), "skip": "thin_bucket"})
                continue
            bh, bl = _brier(p_te[hi], yte[hi]), _brier(p_te[lo], yte[lo])
            lh = _lift10(p_te[hi], yte[hi], base); ll = _lift10(p_te[lo], yte[lo], base)
            per_metric[m].append({
                "split": ts.isoformat(), "n_hi": int(hi.sum()), "n_lo": int(lo.sum()),
                "brier_hi": round(bh, 4), "brier_lo": round(bl, 4),
                "lift_hi": None if lh is None else round(lh, 2), "lift_lo": None if ll is None else round(ll, 2),
                "_g5a": bh <= bl,
                "_g5b": lh is not None and ll is not None and lh >= ll,
            })

    metric_pass = {}
    for m in METRICS:
        valid = [r for r in per_metric[m] if "skip" not in r]
        a = sum(r["_g5a"] for r in valid) >= 2
        b = sum(r["_g5b"] for r in valid) >= 2
        metric_pass[m] = bool(a and b and len(valid) >= 2)
    chosen = next((m for m in METRICS if metric_pass[m]), None)  # prefer analog_confidence order
    out = {"audit": "analog_quality_v0.1", "K": K, "metrics": list(METRICS),
           "per_metric": per_metric, "metric_pass": metric_pass, "chosen_quality_metric": chosen,
           "g5_operationalized": chosen is not None,
           "note": "Same retrieval as v0 (7-feat distance incl rain_persistence_path - verified code==prereg). "
                   "Only the adherence metric changes. If a metric passes, analog high-risk arm is eligible "
                   "for a (separately gated) build. No forecast wiring."}
    (REPO / "reports" / "analog").mkdir(parents=True, exist_ok=True)
    (REPO / "reports" / "analog" / "analog_quality_v0_1.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    (REPO / "reports" / "analog" / "analog_quality_v0_1.md").write_text(_render(out), encoding="ascii")
    print(f"chosen={chosen} pass={metric_pass}")
    for m in METRICS:
        for r in per_metric[m]:
            if "skip" in r:
                print(f"  {m} {r['split']}: {r['skip']}"); continue
            print(f"  {m} {r['split']}: brier hi/lo {r['brier_hi']}/{r['brier_lo']} (g5a {r['_g5a']}) "
                  f"lift hi/lo {r['lift_hi']}/{r['lift_lo']} (g5b {r['_g5b']})")
    return 0


def _render(out: dict) -> str:
    L = ["# analog_quality_v0.1 (operationalize g5; retrieval unchanged)", "",
         f"- K={out['K']}; metrics tested: `{', '.join(out['metrics'])}`. {out['note']}",
         f"- **chosen analog_quality: {out['chosen_quality_metric']}** | g5 operationalized: {out['g5_operationalized']}",
         f"- metric_pass: {out['metric_pass']}", ""]
    for m in out["metrics"]:
        L += [f"## {m}", "", "| split | n hi/lo | Brier hi/lo (g5a) | lift hi/lo (g5b) |",
              "|-------|---------|-------------------|------------------|"]
        for r in out["per_metric"][m]:
            if "skip" in r:
                L.append(f"| {r['split']} | - | {r['skip']} | - |"); continue
            L.append(f"| {r['split']} | {r['n_hi']}/{r['n_lo']} | {r['brier_hi']}/{r['brier_lo']} ({r['_g5a']}) | "
                     f"{r['lift_hi']}/{r['lift_lo']} ({r['_g5b']}) |")
        L.append("")
    L += ["_g5a Brier(high-q)<=Brier(low-q); g5b within-bucket top-decile lift(high)>=low; "
          "accept a metric if both hold >=2/3 splits. Read-only; no forecast change._"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
