#!/usr/bin/env python3
"""Recent holdout backtest with a frozen training cutoff.

This script answers a narrow operational question: if the historical training
CSV stopped before the latest live observations, how did the empirical forecast
perform on the now-complete gap?

Default behavior:
- base CSV: ``NZWN.csv`` defines the training cutoff (last day_complete date)
- eval CSV: ``artifacts/state/NZWN_live_merged.csv`` supplies recent truth
- holdout: complete eval days after the base cutoff

No trading, no promotion decision, no threshold tuning.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import fit_empirical_conditional
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.intervals import discrete_ic
from core.eval.metrics import bracket_match_at_p50, mae, rmse
from core.features.builder import build_cp_features, build_empirical_panel_fast
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels

REPORT_JSON = Path("reports/forecast_value/recent_holdout_v1.json")
REPORT_MD = Path("reports/forecast_value/recent_holdout_v1.md")


def _complete_dates(labels: pl.DataFrame) -> list[date]:
    return [
        r["date_local"]
        for r in labels.filter(pl.col("day_complete") & pl.col("tmax_int").is_not_null())
        .select("date_local")
        .sort("date_local")
        .iter_rows(named=True)
    ]


def _max_complete_date(labels: pl.DataFrame) -> date | None:
    dates = _complete_dates(labels)
    return dates[-1] if dates else None


def _p50(prob_dist: dict[int, float]) -> int:
    return int(max(prob_dist.items(), key=lambda kv: kv[1])[0])


def _point_dist(k: int) -> dict[int, float]:
    return {int(k): 1.0}


def _aligned_rps(prob_dist: dict[int, float], truth: int) -> float:
    """RPS over a support that always contains the observed truth."""
    keys = [int(k) for k in prob_dist.keys()]
    lo = min(min(keys), int(truth))
    hi = max(max(keys), int(truth))
    cum_p = 0.0
    cum_o = 0.0
    score = 0.0
    for k in range(lo, hi + 1):
        cum_p += float(prob_dist.get(k, 0.0))
        cum_o += 1.0 if k == int(truth) else 0.0
        score += (cum_p - cum_o) ** 2
    return float(score)


def _metrics(rows: list[dict[str, Any]], model: str) -> dict[str, Any]:
    usable = [r for r in rows if r["predictions"].get(model, {}).get("p50_int") is not None]
    if not usable:
        return {"n": 0, "mae": None, "rmse": None, "bracket_match": None, "rps": None}
    pred = np.array([r["predictions"][model]["p50_int"] for r in usable], dtype=int)
    truth = np.array([r["truth_int"] for r in usable], dtype=int)
    rps_vals = [
        _aligned_rps(r["predictions"][model]["prob_dist"], r["truth_int"])
        for r in usable
    ]
    out: dict[str, Any] = {
        "n": len(usable),
        "mae": round(float(mae(pred, truth)), 4),
        "rmse": round(float(rmse(pred, truth)), 4),
        "bracket_match": round(float(bracket_match_at_p50(pred, truth)), 4),
        "rps": round(float(np.mean(rps_vals)), 4),
    }
    if model == "empirical":
        hits = []
        widths = []
        for r in usable:
            pred_row = r["predictions"][model]
            hits.append(int(pred_row["ic80_low_int"] <= r["truth_int"] <= pred_row["ic80_high_int"]))
            widths.append(pred_row["ic80_high_int"] - pred_row["ic80_low_int"] + 1)
        out["ic80_coverage"] = round(float(np.mean(hits)), 4)
        out["mean_ic80_width"] = round(float(np.mean(widths)), 4)
    return out


def _metrics_by_cp(rows: list[dict[str, Any]], models: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for cp in sorted({r["cp"] for r in rows}):
        cp_rows = [r for r in rows if r["cp"] == cp]
        out[cp] = {m: _metrics(cp_rows, m) for m in models}
    return out


def _metrics_by_date(rows: list[dict[str, Any]], models: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for d in sorted({r["date_local"] for r in rows}):
        day_rows = [r for r in rows if r["date_local"] == d]
        day_metrics = {m: _metrics(day_rows, m) for m in models}
        mae_candidates = {
            m: stats["mae"]
            for m, stats in day_metrics.items()
            if stats["mae"] is not None
        }
        day_metrics["_best_by_mae"] = min(mae_candidates, key=mae_candidates.get) if mae_candidates else None
        out[d] = day_metrics
    return out


def _wins_by_date(by_date: dict[str, dict[str, Any]], models: list[str]) -> dict[str, int]:
    wins = {m: 0 for m in models}
    for day_metrics in by_date.values():
        best = day_metrics.get("_best_by_mae")
        if isinstance(best, str) and best in wins:
            wins[best] += 1
    return wins


def evaluate_recent_holdout(
    *,
    station_yaml: Path,
    base_csv: Path,
    eval_csv: Path,
    train_start: date,
    train_end: date | None,
    holdout_start: date | None,
    holdout_end: date | None,
    cp_set: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    cfg = load_station_config(station_yaml)
    cps = cp_set or tuple(cfg.cp_set_utc)

    base_obs, base_stats = load_observations(
        base_csv,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    eval_obs, eval_stats = load_observations(
        eval_csv,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    base_labels = build_tmax_labels(base_obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    eval_labels = build_tmax_labels(eval_obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    base_cutoff = _max_complete_date(base_labels)
    eval_complete_max = _max_complete_date(eval_labels)
    if base_cutoff is None:
        raise RuntimeError("base_csv has no complete labels")
    if eval_complete_max is None:
        raise RuntimeError("eval_csv has no complete labels")

    train_end_d = train_end or base_cutoff
    holdout_start_d = holdout_start or (train_end_d + timedelta(days=1))
    holdout_end_d = holdout_end or eval_complete_max

    train_dates = [
        r["date_local"]
        for r in base_labels.filter(
            (pl.col("date_local") >= train_start)
            & (pl.col("date_local") <= train_end_d)
            & pl.col("day_complete")
            & pl.col("tmax_int").is_not_null()
        )
        .select("date_local")
        .sort("date_local")
        .iter_rows(named=True)
    ]
    holdout_labels = eval_labels.filter(
        (pl.col("date_local") >= holdout_start_d)
        & (pl.col("date_local") <= holdout_end_d)
        & pl.col("day_complete")
        & pl.col("tmax_int").is_not_null()
    ).select(["date_local", "tmax_int", "tmin_int", "day_complete"])

    if not train_dates:
        raise RuntimeError("no train dates after applying complete-day filter")
    if holdout_labels.is_empty():
        raise RuntimeError(
            f"no complete holdout labels in {holdout_start_d}..{holdout_end_d}"
        )

    climo = fit_climatology(base_labels, train_start=train_start, train_end=train_end_d)
    empirical_panel = build_empirical_panel_fast(
        base_obs,
        base_labels,
        tz_name=cfg.tz,
        cp_set=cps,
        dates=train_dates,
    )
    empirical = fit_empirical_conditional(
        empirical_panel,
        train_window=(train_start, train_end_d),
    )

    truth_map = {
        r["date_local"]: int(r["tmax_int"])
        for r in holdout_labels.iter_rows(named=True)
    }

    rows: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for d, truth in sorted(truth_map.items()):
        p10, p90 = climo.percentiles_for(d)
        sk = support_K(
            p10,
            p90,
            tmp_min=cfg.tmp_c_int_plausibility.min,
            tmp_max=cfg.tmp_c_int_plausibility.max,
        )
        for cp in cps:
            feats = build_cp_features(
                eval_obs,
                date_local=d,
                cp_hhmm=cp,
                tz_name=cfg.tz,
                labels=eval_labels,
            )
            kcp = feats.features.get("k_cp")
            kcp_for_pred = int(kcp) if kcp is not None else Q(climo.tmax_dec_for(d))
            emp_dist, source = empirical.predict_dist(
                month=d.month,
                cp=cp,
                k_cp=kcp_for_pred,
                support_k=sk,
            )
            emp_bucket = empirical.cond.get((d.month, cp, kcp_for_pred), {})
            emp_marginal = empirical.marginal.get((d.month, cp), {})
            emp_bucket_n = int(sum(emp_bucket.values()))
            emp_marginal_n = int(sum(emp_marginal.values()))
            emp_p50 = _p50(emp_dist)
            low, high = discrete_ic(emp_dist, p_low=0.10, p_high=0.90)
            climo_p50 = Q(climo.tmax_dec_for(d))
            t_dminus1 = feats.features.get("tmax_d_minus_1_int")
            source_counts[source] += 1
            predictions = {
                "empirical": {
                    "p50_int": emp_p50,
                    "prob_dist": emp_dist,
                    "ic80_low_int": int(low),
                    "ic80_high_int": int(high),
                    "source": source,
                },
                "climatology": {
                    "p50_int": int(climo_p50),
                    "prob_dist": _point_dist(int(climo_p50)),
                },
                "t_so_far": {
                    "p50_int": None if kcp is None else int(kcp),
                    "prob_dist": {} if kcp is None else _point_dist(int(kcp)),
                },
                "dminus1": {
                    "p50_int": None if t_dminus1 is None else int(t_dminus1),
                    "prob_dist": {} if t_dminus1 is None else _point_dist(int(t_dminus1)),
                },
            }
            rows.append({
                "date_local": d.isoformat(),
                "cp": cp,
                "truth_int": int(truth),
                "cp_utc": feats.cp_utc.isoformat(),
                "feature_max_ts_utc": feats.feature_max_ts_utc.isoformat(),
                "feature_gap_to_cp_min": int(
                    (feats.cp_utc - feats.feature_max_ts_utc).total_seconds() // 60
                ),
                "k_cp_available": kcp is not None,
                "k_cp": None if kcp is None else int(kcp),
                "empirical_bucket_n": emp_bucket_n,
                "empirical_marginal_n": emp_marginal_n,
                "empirical_n_min_bucket": int(empirical.n_min_bucket),
                "support_k": sk,
                "predictions": predictions,
            })

    models = ["empirical", "climatology", "t_so_far", "dminus1"]
    overall = {m: _metrics(rows, m) for m in models}
    per_cp = _metrics_by_cp(rows, models)
    per_date = _metrics_by_date(rows, models)
    null_models = ["climatology", "t_so_far", "dminus1"]
    best_null = min(
        (m for m in null_models if overall[m]["mae"] is not None),
        key=lambda m: overall[m]["mae"],
    )
    empirical_mae = overall["empirical"]["mae"]
    best_null_mae = overall[best_null]["mae"]
    verdict = "INSUFFICIENT_N"
    if empirical_mae is not None and best_null_mae is not None and empirical_mae >= best_null_mae:
        verdict = "NULL_NOT_BEATEN"
    elif overall["empirical"]["n"] >= 30:
        verdict = "EMPIRICAL_BEATS_NULL"

    return {
        "schema_version": "recent_holdout_v1",
        "status": "ok",
        "verdict": verdict,
        "notes": [
            "This is a recent holdout smoke, not a promotion decision.",
            "Training cutoff is frozen by base_csv last complete day unless --train-end is supplied.",
            "Truth rows require day_complete=true in eval_csv.",
        ],
        "config": {
            "station": cfg.icao,
            "station_yaml": str(station_yaml),
            "base_csv": str(base_csv),
            "eval_csv": str(eval_csv),
            "train_start": train_start.isoformat(),
            "train_end": train_end_d.isoformat(),
            "holdout_start": holdout_start_d.isoformat(),
            "holdout_end": holdout_end_d.isoformat(),
            "cp_set": list(cps),
            "empirical_n_min_bucket": int(empirical.n_min_bucket),
        },
        "data_windows": {
            "base_obs_min": base_obs["ts_utc"].min().isoformat(),
            "base_obs_max": base_obs["ts_utc"].max().isoformat(),
            "eval_obs_min": eval_obs["ts_utc"].min().isoformat(),
            "eval_obs_max": eval_obs["ts_utc"].max().isoformat(),
            "base_complete_max": base_cutoff.isoformat(),
            "eval_complete_max": eval_complete_max.isoformat(),
            "train_complete_days": len(train_dates),
            "holdout_complete_days": holdout_labels.height,
            "base_fallback_rate": base_stats.fallback_rate,
            "eval_fallback_rate": eval_stats.fallback_rate,
        },
        "metrics": {
            "overall": overall,
            "per_cp": per_cp,
            "per_date": per_date,
            "wins_by_date_mae": _wins_by_date(per_date, models),
            "source_counts": dict(source_counts),
            "empirical_fallback_marginal_rate": round(
                float(source_counts.get("fallback_marginal", 0)) / len(rows), 4
            ) if rows else None,
            "best_null_by_mae": best_null,
            "empirical_mae_minus_best_null": (
                None if empirical_mae is None or best_null_mae is None
                else round(float(empirical_mae - best_null_mae), 4)
            ),
        },
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    cfg = report["config"]
    dw = report["data_windows"]
    overall = report["metrics"]["overall"]
    lines = [
        "# Recent Holdout Backtest v1",
        "",
        f"- verdict: **{report['verdict']}**",
        f"- train: {cfg['train_start']}..{cfg['train_end']} ({dw['train_complete_days']} complete days)",
        f"- holdout: {cfg['holdout_start']}..{cfg['holdout_end']} ({dw['holdout_complete_days']} complete days)",
        f"- base obs max: {dw['base_obs_max']}",
        f"- eval obs max: {dw['eval_obs_max']}",
        f"- best null by MAE: {report['metrics']['best_null_by_mae']}",
        f"- empirical MAE - best null MAE: {report['metrics']['empirical_mae_minus_best_null']}",
        f"- empirical fallback_marginal rate: {report['metrics']['empirical_fallback_marginal_rate']}",
        "",
        "## Overall",
        "",
        "| model | n | MAE | RMSE | BM | RPS | IC80 cov | IC80 width |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, m in overall.items():
        lines.append(
            f"| {model} | {m['n']} | {_fmt(m.get('mae'))} | {_fmt(m.get('rmse'))} | "
            f"{_fmt(m.get('bracket_match'))} | {_fmt(m.get('rps'))} | "
            f"{_fmt(m.get('ic80_coverage'))} | {_fmt(m.get('mean_ic80_width'))} |"
        )
    lines += ["", "## Per CP", ""]
    for cp, cp_metrics in report["metrics"]["per_cp"].items():
        lines += [
            f"### CP {cp}",
            "",
            "| model | n | MAE | RMSE | BM | RPS |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for model, m in cp_metrics.items():
            lines.append(
                f"| {model} | {m['n']} | {_fmt(m.get('mae'))} | {_fmt(m.get('rmse'))} | "
                f"{_fmt(m.get('bracket_match'))} | {_fmt(m.get('rps'))} |"
            )
        lines.append("")
    lines += ["", "## Per Day", ""]
    lines += [
        "| date | best_by_mae | empirical MAE | climatology MAE | t_so_far MAE | dminus1 MAE | empirical BM |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for d, day_metrics in report["metrics"]["per_date"].items():
        lines.append(
            f"| {d} | {day_metrics['_best_by_mae']} | "
            f"{_fmt(day_metrics['empirical'].get('mae'))} | "
            f"{_fmt(day_metrics['climatology'].get('mae'))} | "
            f"{_fmt(day_metrics['t_so_far'].get('mae'))} | "
            f"{_fmt(day_metrics['dminus1'].get('mae'))} | "
            f"{_fmt(day_metrics['empirical'].get('bracket_match'))} |"
        )
    lines += [
        "",
        "## Row Detail",
        "",
        "| date | CP | truth | emp | emp_err | source | k_cp | t_so_far_err | dminus1 | dminus1_err | gap_min | IC80 |",
        "|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        emp = row["predictions"]["empirical"]["p50_int"]
        tsf = row["predictions"]["t_so_far"]["p50_int"]
        d1 = row["predictions"]["dminus1"]["p50_int"]
        truth = row["truth_int"]
        ic = f"[{row['predictions']['empirical']['ic80_low_int']},{row['predictions']['empirical']['ic80_high_int']}]"
        lines.append(
            f"| {row['date_local']} | {row['cp']} | {truth} | {emp} | {abs(emp - truth)} | "
            f"{row['predictions']['empirical']['source']} | {_fmt(row['k_cp'])} | "
            f"{_fmt(None if tsf is None else abs(tsf - truth))} | {_fmt(d1)} | "
            f"{_fmt(None if d1 is None else abs(d1 - truth))} | {row['feature_gap_to_cp_min']} | {ic} |"
        )
    lines += [
        "",
        "## Empirical Bucket Diagnostics",
        "",
        f"- n_min_bucket: {cfg['empirical_n_min_bucket']}",
        "- Row details JSON includes empirical_bucket_n and empirical_marginal_n for each forecast.",
        "",
    ]
    lines += [
        "## Source Counts",
        "",
        json.dumps(report["metrics"]["source_counts"], ensure_ascii=True, sort_keys=True),
        "",
        "## Wins By Day MAE",
        "",
        json.dumps(report["metrics"]["wins_by_date_mae"], ensure_ascii=True, sort_keys=True),
        "",
        "## Interpretation",
        "",
        "This report is deliberately small if the live gap is small. It is useful as a",
        "leakage/freshness/value smoke, not as a promotion-grade sample.",
        "",
    ]
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if v is None:
        return "NA"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate recent frozen-cutoff holdout.")
    parser.add_argument("--station-config", type=Path, default=Path("nzwn/config/station.yaml"))
    parser.add_argument("--base-csv", type=Path, default=Path("NZWN.csv"))
    parser.add_argument("--eval-csv", type=Path, default=Path("artifacts/state/NZWN_live_merged.csv"))
    parser.add_argument("--train-start", type=str, default="2020-01-01")
    parser.add_argument("--train-end", type=str, default=None)
    parser.add_argument("--holdout-start", type=str, default=None)
    parser.add_argument("--holdout-end", type=str, default=None)
    parser.add_argument("--cps", type=str, default=None, help="Comma-separated CP hours, e.g. 20,21,22,23.")
    parser.add_argument("--out-json", type=Path, default=REPORT_JSON)
    parser.add_argument("--out-md", type=Path, default=REPORT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cps = None
    if args.cps:
        cps = tuple(f"{int(c.strip()):02d}:00" for c in args.cps.split(",") if c.strip())
    report = evaluate_recent_holdout(
        station_yaml=args.station_config,
        base_csv=args.base_csv,
        eval_csv=args.eval_csv,
        train_start=date.fromisoformat(args.train_start),
        train_end=date.fromisoformat(args.train_end) if args.train_end else None,
        holdout_start=date.fromisoformat(args.holdout_start) if args.holdout_start else None,
        holdout_end=date.fromisoformat(args.holdout_end) if args.holdout_end else None,
        cp_set=cps,
    )
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(report), encoding="ascii")
    print(f"Wrote: {args.out_json}")
    print(f"Wrote: {args.out_md}")
    print(
        "verdict={verdict} n={n} empirical_mae={mae} best_null={best_null}".format(
            verdict=report["verdict"],
            n=report["metrics"]["overall"]["empirical"]["n"],
            mae=report["metrics"]["overall"]["empirical"]["mae"],
            best_null=report["metrics"]["best_null_by_mae"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
