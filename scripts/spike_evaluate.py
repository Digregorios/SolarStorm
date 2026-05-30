"""Phase 7 late-spike walk-forward evaluation.

Same expanding split structure as phase4_evaluate (test_starts 2023/2024/2025).
Emits reports/spike/<run_id>.md with PR-AUC, recall@FPR<=0.05, ECE,
base prevalence, and bootstrap CI on PR-AUC (REQ-SPK-3).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from core.contracts.station import load_station_config
from core.eval.cv import expanding_walk_forward_splits
from core.ingest.iem_csv import load_observations
from core.io.timeutil import cp_to_utc, day_local_window
from core.labels.tmax import build_tmax_labels
from core.spike.features import SPIKE_FEATURE_COLUMNS, build_spike_features
from core.spike.model import SpikeModelConfig, fit_spike_model, predict_spike_risk

REPO = Path(__file__).resolve().parents[1]


def _build_spike_panel(
    obs: pl.DataFrame,
    labels: pl.DataFrame,
    *,
    tz_name: str,
    cp_set: list[str],
) -> pl.DataFrame:
    """Build (date, cp) panel with spike features + late_spike_l1 label."""
    dates = sorted(
        d for d in labels.filter(pl.col("day_complete"))["date_local"].to_list()
        if d is not None
    )
    rows: list[dict] = []
    for d in dates:
        for cp in cp_set:
            col_name = f"late_spike_l1__cp_{cp[:2]}"
            lab_row = labels.filter(pl.col("date_local") == d)
            if lab_row.height == 0:
                continue
            label_val = lab_row[col_name][0]
            if label_val is None:
                continue
            feats = build_spike_features(
                obs, date_local=d, cp_hhmm=cp, tz_name=tz_name
            )
            feats["date_local"] = d
            feats["cp"] = cp
            feats["late_spike_l1"] = int(bool(label_val))
            rows.append(feats)
    return pl.DataFrame(rows, infer_schema_length=None)


def _arrays(panel: pl.DataFrame):
    X = np.column_stack([
        panel[c].cast(pl.Float64).to_numpy() for c in SPIKE_FEATURE_COLUMNS
    ])
    y = panel["late_spike_l1"].to_numpy().astype(int)
    return X, y


def _pr_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Precision-Recall AUC (manual, no sklearn dependency for metrics)."""
    order = np.argsort(-y_score)
    yt = y_true[order]
    tp = np.cumsum(yt)
    fp = np.cumsum(1 - yt)
    precision = tp / (tp + fp)
    recall = tp / max(1, int(yt.sum()))
    # trapezoidal
    auc = 0.0
    for i in range(1, len(recall)):
        auc += (recall[i] - recall[i - 1]) * (precision[i] + precision[i - 1]) / 2.0
    return float(auc)


def _recall_at_fpr(y_true: np.ndarray, y_score: np.ndarray, max_fpr: float) -> float:
    """Max recall achievable at FPR <= max_fpr."""
    order = np.argsort(-y_score)
    yt = y_true[order]
    n_pos = int(yt.sum())
    n_neg = len(yt) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.0
    tp = 0
    fp = 0
    best_recall = 0.0
    for label in yt:
        if label == 1:
            tp += 1
        else:
            fp += 1
        fpr = fp / n_neg
        if fpr > max_fpr:
            break
        best_recall = tp / n_pos
    return best_recall


def _ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error."""
    bins = np.linspace(0, 1, n_bins + 1)
    ece_val = 0.0
    for i in range(n_bins):
        mask = (y_prob >= bins[i]) & (y_prob < bins[i + 1])
        if i == n_bins - 1:
            mask = mask | (y_prob == bins[i + 1])
        n_bin = int(mask.sum())
        if n_bin == 0:
            continue
        avg_conf = float(y_prob[mask].mean())
        avg_acc = float(y_true[mask].mean())
        ece_val += (n_bin / len(y_true)) * abs(avg_acc - avg_conf)
    return ece_val


def _bootstrap_pr_auc_ci(
    y_true: np.ndarray, y_score: np.ndarray, *, n_boot: int = 1000, seed: int = 42
) -> tuple[float, float, float]:
    """Bootstrap 95% CI on PR-AUC."""
    rng = np.random.default_rng(seed)
    point = _pr_auc(y_true, y_score)
    boots = np.empty(n_boot)
    n = len(y_true)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boots[i] = _pr_auc(y_true[idx], y_score[idx])
    lo = float(np.quantile(boots, 0.025))
    hi = float(np.quantile(boots, 0.975))
    return point, lo, hi


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    print("[1/4] Loading observations + labels ...")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    print("[2/4] Building spike panel ...")
    panel = _build_spike_panel(
        obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc
    )
    print(f"  panel rows={panel.height}, spike prevalence="
          f"{panel['late_spike_l1'].mean():.4f}")

    splits = expanding_walk_forward_splits(
        history_start=date(2020, 1, 1),
        test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)],
        test_length_days=365,
    )

    run_id = hashlib.sha256(
        datetime.now(timezone.utc).isoformat().encode()
    ).hexdigest()[:12]

    print(f"[3/4] Walk-forward {len(splits)} splits ...")
    results: list[dict] = []
    for s in splits:
        print(f"  {s.name}")
        train = panel.filter(
            (pl.col("date_local") >= s.train_start)
            & (pl.col("date_local") <= s.train_end)
        )
        test = panel.filter(
            (pl.col("date_local") >= s.test_start)
            & (pl.col("date_local") <= s.test_end)
        )
        if train.height < 60 or test.height < 20:
            print(f"    SKIP (train={train.height}, test={test.height})")
            continue
        X_train, y_train = _arrays(train)
        X_test, y_test = _arrays(test)

        model = fit_spike_model(X_train, y_train, config=SpikeModelConfig(seed=42))
        risk = predict_spike_risk(model, X_test)

        prevalence = float(y_test.mean())
        pr_auc_pt, pr_auc_lo, pr_auc_hi = _bootstrap_pr_auc_ci(
            y_test, risk, seed=42
        )
        recall_fpr05 = _recall_at_fpr(y_test, risk, 0.05)
        ece = _ece(y_test, risk)

        ci_excludes_prevalence = pr_auc_lo > prevalence
        results.append({
            "split": s.name,
            "n_train": train.height,
            "n_test": test.height,
            "prevalence": prevalence,
            "pr_auc": pr_auc_pt,
            "pr_auc_ci95_lo": pr_auc_lo,
            "pr_auc_ci95_hi": pr_auc_hi,
            "ci_excludes_prevalence": ci_excludes_prevalence,
            "recall_at_fpr_005": recall_fpr05,
            "ece": ece,
            "best_iteration": model.best_iteration,
        })
        print(f"    PR-AUC={pr_auc_pt:.4f} [{pr_auc_lo:.4f},{pr_auc_hi:.4f}] "
              f"prev={prevalence:.4f} CI>prev={ci_excludes_prevalence}")

    # Emit report
    out_dir = REPO / "reports" / "spike"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_lines = [
        f"# Phase 7 Late-Spike Evaluation (run {run_id})",
        "",
        "| split | n_train | n_test | prevalence | PR-AUC | CI95 | CI>prev | recall@FPR5% | ECE |",
        "|-------|---------|--------|------------|--------|------|---------|--------------|-----|",
    ]
    for r in results:
        md_lines.append(
            f"| {r['split']} | {r['n_train']} | {r['n_test']} | "
            f"{r['prevalence']:.4f} | {r['pr_auc']:.4f} | "
            f"[{r['pr_auc_ci95_lo']:.4f},{r['pr_auc_ci95_hi']:.4f}] | "
            f"{r['ci_excludes_prevalence']} | {r['recall_at_fpr_005']:.4f} | "
            f"{r['ece']:.4f} |"
        )
    md_lines.append("")
    report_path = out_dir / f"{run_id}.md"
    report_path.write_text("\n".join(md_lines), encoding="ascii")
    print(f"\n[4/4] Report: {report_path}")

    # Also emit JSON
    json_path = out_dir / f"{run_id}.json"
    json_path.write_text(
        json.dumps({"run_id": run_id, "splits": results}, indent=2, ensure_ascii=True),
        encoding="ascii",
    )

    all_pass = all(r["ci_excludes_prevalence"] for r in results)
    print(f"\n[verdict] REQ-SPK-3 (CI excludes prevalence): "
          f"{'PASS' if all_pass else 'PARTIAL'} "
          f"({sum(r['ci_excludes_prevalence'] for r in results)}/{len(results)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
