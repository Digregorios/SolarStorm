"""Tests for scripts/diagnose_recent_holdout_failures.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import diagnose_recent_holdout_failures as diag


def _point(k: int) -> dict[str, float]:
    return {str(k): 1.0}


def _row(
    *,
    date_local: str = "2026-05-01",
    cp: str = "20:00",
    truth: int,
    k_cp: int,
    empirical: int,
    source: str,
    climatology: int,
    t_so_far: int,
    dminus1: int,
) -> dict:
    return {
        "date_local": date_local,
        "cp": cp,
        "truth_int": truth,
        "k_cp": k_cp,
        "empirical_bucket_n": 10 if source == "fallback_marginal" else 35,
        "empirical_marginal_n": 120,
        "empirical_n_min_bucket": 30,
        "predictions": {
            "empirical": {
                "p50_int": empirical,
                "prob_dist": _point(empirical),
                "source": source,
                "ic80_low_int": empirical - 1,
                "ic80_high_int": empirical + 1,
            },
            "climatology": {"p50_int": climatology, "prob_dist": _point(climatology)},
            "t_so_far": {"p50_int": t_so_far, "prob_dist": _point(t_so_far)},
            "dminus1": {"p50_int": dminus1, "prob_dist": _point(dminus1)},
        },
    }


def _report(rows: list[dict]) -> dict:
    return {
        "schema_version": "recent_holdout_v1",
        "verdict": "NULL_NOT_BEATEN",
        "config": {"holdout_start": "2026-05-01", "holdout_end": "2026-05-02"},
        "data_windows": {},
        "rows": rows,
    }


def test_truth_minus_kcp_bucket_labels_posthoc_regimes():
    assert diag.truth_minus_kcp_bucket({"truth_int": 10, "k_cp": 10}) == "reached_or_cooling_le_0"
    assert diag.truth_minus_kcp_bucket({"truth_int": 9, "k_cp": 10}) == "reached_or_cooling_le_0"
    assert diag.truth_minus_kcp_bucket({"truth_int": 11, "k_cp": 10}) == "plus_1"
    assert diag.truth_minus_kcp_bucket({"truth_int": 12, "k_cp": 10}) == "late_warming_2plus"
    assert diag.truth_minus_kcp_bucket({"truth_int": 12, "k_cp": None}) == "missing_k_cp"


def test_source_breakdown_exposes_fallback_underperformance():
    rows = [
        _row(truth=16, k_cp=14, empirical=16, source="conditional", climatology=15, t_so_far=14, dminus1=15),
        _row(truth=17, k_cp=15, empirical=17, source="conditional", climatology=15, t_so_far=15, dminus1=15),
        _row(truth=18, k_cp=15, empirical=15, source="fallback_marginal", climatology=16, t_so_far=15, dminus1=18),
        _row(truth=19, k_cp=16, empirical=15, source="fallback_marginal", climatology=16, t_so_far=16, dminus1=19),
    ]

    analysis = diag.analyze_report(_report(rows), Path("synthetic.json"))

    conditional = analysis["by_source"]["conditional"]
    fallback = analysis["by_source"]["fallback_marginal"]
    assert conditional["metrics"]["empirical"]["mae"] == 0.0
    assert conditional["empirical_mae_minus_best_null"] < 0.0
    assert conditional["empirical_bucket_floor"]["eligible_rate"] == 1.0
    assert fallback["metrics"]["empirical"]["mae"] == 3.5
    assert fallback["best_null_by_mae"] == "dminus1"
    assert fallback["empirical_mae_minus_best_null"] > 0.0
    assert fallback["empirical_bucket_floor"]["below_floor_rate"] == 1.0
    assert any(f["code"] == "fallback_marginal_is_negative_value" for f in analysis["findings"])


def test_reached_or_cooling_bucket_identifies_t_so_far_control():
    rows = [
        _row(truth=15, k_cp=15, empirical=17, source="fallback_marginal", climatology=16, t_so_far=15, dminus1=17),
        _row(truth=14, k_cp=15, empirical=17, source="fallback_marginal", climatology=16, t_so_far=15, dminus1=17),
    ]

    analysis = diag.analyze_report(_report(rows), Path("synthetic.json"))

    reached = analysis["by_truth_minus_kcp"]["reached_or_cooling_le_0"]
    assert reached["best_null_by_mae"] == "t_so_far"
    assert reached["metrics"]["t_so_far"]["mae"] < reached["metrics"]["empirical"]["mae"]
    assert any(f["code"] == "already_reached_regime_should_route_to_t_so_far" for f in analysis["findings"])


def test_render_outputs_failure_metrics(tmp_path: Path):
    path = tmp_path / "recent_holdout_synthetic.json"
    path.write_text(
        json.dumps(
            _report([
                _row(truth=18, k_cp=15, empirical=15, source="fallback_marginal", climatology=16, t_so_far=15, dminus1=18),
            ])
        ),
        encoding="ascii",
    )

    diagnosis = diag.diagnose_reports([path])
    md = diag.render_markdown(diagnosis)

    assert diagnosis["schema_version"] == diag.SCHEMA_VERSION
    assert "fallback_marginal" in md
    assert "Empirical Bucket Floor" in md
    assert "truth-k_cp" in md
    assert "empirical_loses_to_null" in md
