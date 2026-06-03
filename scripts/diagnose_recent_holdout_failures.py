#!/usr/bin/env python3
"""Diagnose why recent holdout forecasts fail to beat trivial baselines.

This script reads one or more ``recent_holdout_v1`` JSON reports and emits a
failure taxonomy. It does not retrain, tune thresholds, or promote any model.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

REPORT_JSON = Path("reports/forecast_value/recent_holdout_failure_diagnosis_v1.json")
REPORT_MD = Path("reports/forecast_value/recent_holdout_failure_diagnosis_v1.md")
DEFAULT_INPUT_GLOB = "reports/forecast_value/recent_holdout*.json"
SCHEMA_VERSION = "recent_holdout_failure_diagnosis_v1"
MODELS = ("empirical", "climatology", "t_so_far", "dminus1")
NULL_MODELS = ("climatology", "t_so_far", "dminus1")


def _round(v: float | None, ndigits: int = 4) -> float | None:
    if v is None:
        return None
    return round(float(v), ndigits)


def _mean(vals: Iterable[float]) -> float | None:
    xs = list(vals)
    if not xs:
        return None
    return float(sum(xs) / len(xs))


def _percentile(vals: Iterable[float], p: float) -> float | None:
    xs = sorted(float(v) for v in vals)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    rank = (len(xs) - 1) * (p / 100.0)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - rank) + xs[hi] * (rank - lo)


def _p50(row: dict[str, Any], model: str) -> int | None:
    value = row.get("predictions", {}).get(model, {}).get("p50_int")
    return None if value is None else int(value)


def _prob_dist(row: dict[str, Any], model: str) -> dict[int, float]:
    raw = row.get("predictions", {}).get(model, {}).get("prob_dist") or {}
    return {int(k): float(v) for k, v in raw.items()}


def _abs_err(row: dict[str, Any], model: str) -> int | None:
    pred = _p50(row, model)
    if pred is None:
        return None
    return abs(pred - int(row["truth_int"]))


def _aligned_rps(prob_dist: dict[int, float], truth: int) -> float | None:
    if not prob_dist:
        return None
    keys = [int(k) for k in prob_dist]
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
    usable = [r for r in rows if _p50(r, model) is not None]
    if not usable:
        return {"n": 0, "mae": None, "rmse": None, "bracket_match": None, "rps": None}
    errors = [_abs_err(r, model) for r in usable]
    errs = [float(e) for e in errors if e is not None]
    sq_errs = [e * e for e in errs]
    rps_vals = [
        rps for rps in (_aligned_rps(_prob_dist(r, model), int(r["truth_int"])) for r in usable)
        if rps is not None
    ]
    return {
        "n": len(usable),
        "mae": _round(_mean(errs)),
        "rmse": _round(math.sqrt(float(_mean(sq_errs) or 0.0))),
        "bracket_match": _round(
            _mean(1.0 if int(_p50(r, model)) == int(r["truth_int"]) else 0.0 for r in usable)
        ),
        "rps": _round(_mean(rps_vals)),
    }


def truth_minus_kcp_bucket(row: dict[str, Any]) -> str:
    """Post-hoc regime bucket used only for diagnosis."""
    kcp = row.get("k_cp")
    if kcp is None:
        return "missing_k_cp"
    delta = int(row["truth_int"]) - int(kcp)
    if delta <= 0:
        return "reached_or_cooling_le_0"
    if delta == 1:
        return "plus_1"
    return "late_warming_2plus"


def _empirical_source(row: dict[str, Any]) -> str:
    return str(row.get("predictions", {}).get("empirical", {}).get("source") or "unknown")


def _empirical_ic80(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = []
    for row in rows:
        pred = row.get("predictions", {}).get("empirical", {})
        if pred.get("ic80_low_int") is None or pred.get("ic80_high_int") is None:
            continue
        usable.append(row)
    if not usable:
        return {
            "n": 0,
            "coverage": None,
            "mean_width": None,
            "miss_low_rate": None,
            "miss_high_rate": None,
        }
    hits = []
    widths = []
    miss_low = []
    miss_high = []
    for row in usable:
        truth = int(row["truth_int"])
        pred = row["predictions"]["empirical"]
        lo = int(pred["ic80_low_int"])
        hi = int(pred["ic80_high_int"])
        hits.append(1.0 if lo <= truth <= hi else 0.0)
        widths.append(float(hi - lo + 1))
        miss_low.append(1.0 if truth < lo else 0.0)
        miss_high.append(1.0 if truth > hi else 0.0)
    return {
        "n": len(usable),
        "coverage": _round(_mean(hits)),
        "mean_width": _round(_mean(widths)),
        "miss_low_rate": _round(_mean(miss_low)),
        "miss_high_rate": _round(_mean(miss_high)),
    }


def _bucket_floor(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in rows if r.get("empirical_bucket_n") is not None]
    if not usable:
        return {
            "n": 0,
            "n_min_bucket": None,
            "eligible_rate": None,
            "below_floor_rate": None,
            "bucket_n_p10": None,
            "bucket_n_p50": None,
            "bucket_n_p90": None,
            "marginal_n_p50": None,
        }
    counts = [int(r["empirical_bucket_n"]) for r in usable]
    marginal_counts = [
        int(r["empirical_marginal_n"])
        for r in usable
        if r.get("empirical_marginal_n") is not None
    ]
    floors = Counter(int(r.get("empirical_n_min_bucket", 30)) for r in usable)
    floor = floors.most_common(1)[0][0]
    eligible = [1.0 if c >= floor else 0.0 for c in counts]
    return {
        "n": len(usable),
        "n_min_bucket": floor,
        "eligible_rate": _round(_mean(eligible)),
        "below_floor_rate": _round(1.0 - float(_mean(eligible) or 0.0)),
        "bucket_n_p10": _round(_percentile(counts, 10)),
        "bucket_n_p50": _round(_percentile(counts, 50)),
        "bucket_n_p90": _round(_percentile(counts, 90)),
        "marginal_n_p50": _round(_percentile(marginal_counts, 50)),
    }


def _row_wins(rows: list[dict[str, Any]]) -> dict[str, int]:
    wins = {m: 0 for m in MODELS}
    ties = 0
    for row in rows:
        errs = {m: _abs_err(row, m) for m in MODELS}
        usable = {m: e for m, e in errs.items() if e is not None}
        if not usable:
            continue
        best = min(usable.values())
        best_models = [m for m, e in usable.items() if e == best]
        if len(best_models) > 1:
            ties += 1
        for model in best_models:
            wins[model] += 1
    wins["_ties"] = ties
    return wins


def _model_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {model: _metrics(rows, model) for model in MODELS}


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = _model_metrics(rows)
    empirical_mae = metrics["empirical"]["mae"]
    null_candidates = {
        model: metrics[model]["mae"]
        for model in NULL_MODELS
        if metrics[model]["mae"] is not None
    }
    best_null = min(null_candidates, key=null_candidates.get) if null_candidates else None
    best_null_mae = null_candidates.get(best_null) if best_null else None
    sources = Counter(_empirical_source(row) for row in rows)
    p50_counts = Counter(_p50(row, "empirical") for row in rows if _p50(row, "empirical") is not None)
    p50_mode = p50_counts.most_common(1)[0][0] if p50_counts else None
    p50_mode_count = p50_counts.most_common(1)[0][1] if p50_counts else 0
    return {
        "n": len(rows),
        "metrics": metrics,
        "best_null_by_mae": best_null,
        "empirical_mae_minus_best_null": (
            None if empirical_mae is None or best_null_mae is None
            else _round(float(empirical_mae) - float(best_null_mae))
        ),
        "row_wins_by_abs_error": _row_wins(rows),
        "source_counts": dict(sorted(sources.items())),
        "fallback_marginal_rate": _round(sources.get("fallback_marginal", 0) / len(rows)) if rows else None,
        "conditional_rate": _round(sources.get("conditional", 0) / len(rows)) if rows else None,
        "empirical_p50_mode": p50_mode,
        "empirical_p50_mode_rate": _round(p50_mode_count / len(rows)) if rows else None,
        "empirical_p50_unique_count": len(p50_counts),
        "empirical_ic80": _empirical_ic80(rows),
        "empirical_bucket_floor": _bucket_floor(rows),
    }


def _group(rows: list[dict[str, Any]], key_fn) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)
    return {k: summarize_rows(v) for k, v in sorted(groups.items())}


def _source_cp_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[f"{_empirical_source(row)}|{row.get('cp')}"].append(row)
    return {k: summarize_rows(v) for k, v in sorted(groups.items())}


def _worst_days(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["date_local"])].append(row)
    out = []
    for d, day_rows in groups.items():
        summary = summarize_rows(day_rows)
        out.append({
            "date_local": d,
            "n": len(day_rows),
            "empirical_mae": summary["metrics"]["empirical"]["mae"],
            "best_null_by_mae": summary["best_null_by_mae"],
            "empirical_mae_minus_best_null": summary["empirical_mae_minus_best_null"],
            "fallback_marginal_rate": summary["fallback_marginal_rate"],
            "empirical_p50_mode": summary["empirical_p50_mode"],
        })
    return sorted(
        out,
        key=lambda x: (
            -9999.0 if x["empirical_mae_minus_best_null"] is None else -float(x["empirical_mae_minus_best_null"]),
            x["date_local"],
        ),
    )[:limit]


def _findings(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    overall = analysis["overall"]
    by_source = analysis["by_source"]
    by_delta = analysis["by_truth_minus_kcp"]
    fallback = by_source.get("fallback_marginal")
    conditional = by_source.get("conditional")

    if overall.get("empirical_mae_minus_best_null") is not None and overall["empirical_mae_minus_best_null"] > 0:
        findings.append({
            "code": "empirical_loses_to_null",
            "severity": "P0",
            "evidence": {
                "empirical_mae": overall["metrics"]["empirical"]["mae"],
                "best_null": overall["best_null_by_mae"],
                "delta_mae": overall["empirical_mae_minus_best_null"],
            },
        })
    if fallback and fallback.get("empirical_mae_minus_best_null") is not None and fallback["empirical_mae_minus_best_null"] > 0:
        findings.append({
            "code": "fallback_marginal_is_negative_value",
            "severity": "P0",
            "evidence": {
                "fallback_rate": overall["fallback_marginal_rate"],
                "fallback_empirical_mae": fallback["metrics"]["empirical"]["mae"],
                "fallback_best_null": fallback["best_null_by_mae"],
                "fallback_delta_mae": fallback["empirical_mae_minus_best_null"],
            },
        })
    if conditional and conditional.get("empirical_mae_minus_best_null") is not None and conditional["empirical_mae_minus_best_null"] < 0:
        findings.append({
            "code": "conditional_signal_exists_but_is_sparse",
            "severity": "P1",
            "evidence": {
                "conditional_rate": overall["conditional_rate"],
                "conditional_empirical_mae": conditional["metrics"]["empirical"]["mae"],
                "conditional_best_null": conditional["best_null_by_mae"],
                "conditional_delta_mae": conditional["empirical_mae_minus_best_null"],
            },
        })
    reached = by_delta.get("reached_or_cooling_le_0")
    if reached and reached["best_null_by_mae"] == "t_so_far":
        findings.append({
            "code": "already_reached_regime_should_route_to_t_so_far",
            "severity": "P1",
            "evidence": {
                "n": reached["n"],
                "empirical_mae": reached["metrics"]["empirical"]["mae"],
                "t_so_far_mae": reached["metrics"]["t_so_far"]["mae"],
            },
        })
    late = by_delta.get("late_warming_2plus")
    if late and late.get("empirical_mae_minus_best_null") is not None and late["empirical_mae_minus_best_null"] > 0:
        findings.append({
            "code": "late_warming_regime_not_solved_by_empirical_fallback",
            "severity": "P1",
            "evidence": {
                "n": late["n"],
                "empirical_mae": late["metrics"]["empirical"]["mae"],
                "best_null": late["best_null_by_mae"],
                "delta_mae": late["empirical_mae_minus_best_null"],
            },
        })
    if overall.get("empirical_p50_mode_rate") is not None and overall["empirical_p50_mode_rate"] >= 0.5:
        findings.append({
            "code": "empirical_point_forecast_collapse",
            "severity": "P1",
            "evidence": {
                "p50_mode": overall["empirical_p50_mode"],
                "p50_mode_rate": overall["empirical_p50_mode_rate"],
                "p50_unique_count": overall["empirical_p50_unique_count"],
            },
        })
    return findings


def analyze_report(report: dict[str, Any], source_path: Path) -> dict[str, Any]:
    rows = list(report.get("rows") or [])
    analysis = {
        "source_path": str(source_path),
        "input_schema_version": report.get("schema_version"),
        "input_verdict": report.get("verdict"),
        "config": report.get("config", {}),
        "data_windows": report.get("data_windows", {}),
        "overall": summarize_rows(rows),
        "by_source": _group(rows, _empirical_source),
        "by_cp": _group(rows, lambda r: r.get("cp")),
        "by_truth_minus_kcp": _group(rows, truth_minus_kcp_bucket),
        "by_empirical_p50": _group(rows, lambda r: _p50(r, "empirical")),
        "by_source_and_cp": _source_cp_matrix(rows),
        "worst_days_by_empirical_delta": _worst_days(rows),
    }
    analysis["findings"] = _findings(analysis)
    return analysis


def diagnose_reports(paths: list[Path]) -> dict[str, Any]:
    analyses = {}
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        analyses[path.stem] = analyze_report(report, path)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "notes": [
            "Diagnostic only: reads frozen recent_holdout_v1 outputs; no retraining or model selection.",
            "truth_minus_kcp buckets are post-hoc and must not be used as live promotion evidence.",
            "Null models are climatology, t_so_far, and dminus1.",
        ],
        "inputs": [str(p) for p in paths],
        "reports": analyses,
    }


def render_markdown(diagnosis: dict[str, Any]) -> str:
    lines = [
        "# Recent Holdout Failure Diagnosis v1",
        "",
        "Diagnostic only. This report reads frozen recent holdout outputs and does not retrain, tune, or promote.",
        "",
        "## Executive Summary",
        "",
        "| window | n | verdict | emp MAE | best null | delta MAE | fallback rate | conditional rate | p50 mode | p50 mode rate |",
        "|---|---:|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for name, report in diagnosis["reports"].items():
        overall = report["overall"]
        lines.append(
            f"| {name} | {overall['n']} | {report['input_verdict']} | "
            f"{_fmt(overall['metrics']['empirical']['mae'])} | {overall['best_null_by_mae']} | "
            f"{_fmt(overall['empirical_mae_minus_best_null'])} | "
            f"{_fmt(overall['fallback_marginal_rate'])} | {_fmt(overall['conditional_rate'])} | "
            f"{_fmt(overall['empirical_p50_mode'])} | {_fmt(overall['empirical_p50_mode_rate'])} |"
        )

    lines += ["", "## Findings", ""]
    for name, report in diagnosis["reports"].items():
        lines += [f"### {name}", ""]
        if not report["findings"]:
            lines.append("- No automatic finding emitted.")
        for finding in report["findings"]:
            lines.append(
                f"- {finding['severity']} `{finding['code']}`: "
                f"{json.dumps(finding['evidence'], ensure_ascii=True, sort_keys=True)}"
            )
        lines.append("")

    lines += [
        "## Source Breakdown",
        "",
        "| window | source | n | emp MAE | best null | delta MAE | p50 mode | p50 mode rate | bucket p50 | eligible rate | IC80 cov | IC80 width |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, report in diagnosis["reports"].items():
        for source, summary in report["by_source"].items():
            ic = summary["empirical_ic80"]
            bf = summary["empirical_bucket_floor"]
            lines.append(
                f"| {name} | {source} | {summary['n']} | "
                f"{_fmt(summary['metrics']['empirical']['mae'])} | {summary['best_null_by_mae']} | "
                f"{_fmt(summary['empirical_mae_minus_best_null'])} | "
                f"{_fmt(summary['empirical_p50_mode'])} | {_fmt(summary['empirical_p50_mode_rate'])} | "
                f"{_fmt(bf['bucket_n_p50'])} | {_fmt(bf['eligible_rate'])} | "
                f"{_fmt(ic['coverage'])} | {_fmt(ic['mean_width'])} |"
            )

    lines += [
        "",
        "## Empirical Bucket Floor",
        "",
        "| window | group | n | n_min | eligible rate | below floor | bucket p10 | bucket p50 | bucket p90 | marginal p50 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, report in diagnosis["reports"].items():
        groups = {"overall": report["overall"], **report["by_source"]}
        for group, summary in groups.items():
            bf = summary["empirical_bucket_floor"]
            lines.append(
                f"| {name} | {group} | {bf['n']} | {_fmt(bf['n_min_bucket'])} | "
                f"{_fmt(bf['eligible_rate'])} | {_fmt(bf['below_floor_rate'])} | "
                f"{_fmt(bf['bucket_n_p10'])} | {_fmt(bf['bucket_n_p50'])} | "
                f"{_fmt(bf['bucket_n_p90'])} | {_fmt(bf['marginal_n_p50'])} |"
            )

    lines += [
        "",
        "## truth-k_cp Buckets",
        "",
        "These buckets are post-hoc diagnostics: they use the final truth and are not live-serving signals.",
        "",
        "| window | bucket | n | emp MAE | climatology MAE | t_so_far MAE | dminus1 MAE | best null | delta MAE | fallback rate |",
        "|---|---|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for name, report in diagnosis["reports"].items():
        for bucket, summary in report["by_truth_minus_kcp"].items():
            m = summary["metrics"]
            lines.append(
                f"| {name} | {bucket} | {summary['n']} | "
                f"{_fmt(m['empirical']['mae'])} | {_fmt(m['climatology']['mae'])} | "
                f"{_fmt(m['t_so_far']['mae'])} | {_fmt(m['dminus1']['mae'])} | "
                f"{summary['best_null_by_mae']} | {_fmt(summary['empirical_mae_minus_best_null'])} | "
                f"{_fmt(summary['fallback_marginal_rate'])} |"
            )

    lines += [
        "",
        "## CP Breakdown",
        "",
        "| window | CP | n | emp MAE | best null | delta MAE | fallback rate | p50 mode |",
        "|---|---|---:|---:|---|---:|---:|---:|",
    ]
    for name, report in diagnosis["reports"].items():
        for cp, summary in report["by_cp"].items():
            lines.append(
                f"| {name} | {cp} | {summary['n']} | "
                f"{_fmt(summary['metrics']['empirical']['mae'])} | {summary['best_null_by_mae']} | "
                f"{_fmt(summary['empirical_mae_minus_best_null'])} | "
                f"{_fmt(summary['fallback_marginal_rate'])} | {_fmt(summary['empirical_p50_mode'])} |"
            )

    lines += [
        "",
        "## Worst Days By Empirical Delta",
        "",
        "| window | date | n | emp MAE | best null | delta MAE | fallback rate | p50 mode |",
        "|---|---|---:|---:|---|---:|---:|---:|",
    ]
    for name, report in diagnosis["reports"].items():
        for day in report["worst_days_by_empirical_delta"]:
            lines.append(
                f"| {name} | {day['date_local']} | {day['n']} | "
                f"{_fmt(day['empirical_mae'])} | {day['best_null_by_mae']} | "
                f"{_fmt(day['empirical_mae_minus_best_null'])} | "
                f"{_fmt(day['fallback_marginal_rate'])} | {_fmt(day['empirical_p50_mode'])} |"
            )

    lines += [
        "",
        "## Interpretation Contract",
        "",
        "- If empirical loses to the best null in the overall table, the current empirical path has no demonstrated forecast value in that window.",
        "- If fallback_marginal is both frequent and worse than nulls, the conditional table is too sparse for live value.",
        "- If t_so_far wins when truth-k_cp <= 0, serving should route that already-reached regime before any ML layer is considered.",
        "- If p50 mode rate is high, point forecasts are collapsing to a seasonal/default bracket rather than responding to live state.",
        "",
    ]
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if v is None:
        return "NA"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _default_inputs() -> list[Path]:
    paths = sorted(Path(".").glob(DEFAULT_INPUT_GLOB))
    return [
        p for p in paths
        if "failure_diagnosis" not in p.name and p.suffix == ".json"
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose recent holdout forecast failures.")
    parser.add_argument("--input", type=Path, nargs="*", default=None)
    parser.add_argument("--out-json", type=Path, default=REPORT_JSON)
    parser.add_argument("--out-md", type=Path, default=REPORT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = args.input if args.input is not None and len(args.input) > 0 else _default_inputs()
    if not paths:
        raise SystemExit(f"No input reports found for {DEFAULT_INPUT_GLOB}")
    diagnosis = diagnose_reports(paths)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(diagnosis, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(diagnosis), encoding="ascii")
    print(f"Wrote: {args.out_json}")
    print(f"Wrote: {args.out_md}")
    for name, report in diagnosis["reports"].items():
        overall = report["overall"]
        print(
            "{name}: n={n} emp_mae={mae} best_null={best_null} delta={delta} fallback={fallback}".format(
                name=name,
                n=overall["n"],
                mae=overall["metrics"]["empirical"]["mae"],
                best_null=overall["best_null_by_mae"],
                delta=overall["empirical_mae_minus_best_null"],
                fallback=overall["fallback_marginal_rate"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
