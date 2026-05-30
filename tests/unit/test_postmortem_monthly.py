"""Unit tests for scripts/postmortem_monthly.summarize (T-X-3)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root on path so scripts module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.postmortem_monthly import summarize


def _make_rows(n: int = 30, base_truth: int = 18):
    """Synthetic forecast rows + labels for the last n days."""
    from datetime import date, timedelta

    today = date(2025, 6, 15)
    forecast_rows = []
    labels = []
    for i in range(n):
        d = (today - timedelta(days=i)).isoformat()
        truth = base_truth + (i % 3)  # vary slightly
        pred = truth if i % 2 == 0 else truth + 1  # 50% match
        forecast_rows.append({"date": d, "p50_int": pred, "confidence": 0.7})
        labels.append({"date": d, "tmax_int": truth})
    # Add prior-30d labels for drift calc
    for i in range(n, n + 30):
        d = (today - timedelta(days=i)).isoformat()
        labels.append({"date": d, "tmax_int": base_truth + 3})
    return forecast_rows, labels


def test_bracket_match_in_range():
    rows, labels = _make_rows()
    result = summarize(rows, labels)
    assert 0.0 <= result["bracket_match"] <= 1.0


def test_drift_field_exists():
    rows, labels = _make_rows()
    result = summarize(rows, labels)
    assert "drift_delta" in result
    assert result["drift_delta"] is not None


def test_ev_field_na():
    rows, labels = _make_rows()
    result = summarize(rows, labels)
    assert result["ev"] == "n/a (live-only, no historical odds)"


def test_ece_computed_when_confidence_present():
    rows, labels = _make_rows()
    result = summarize(rows, labels)
    assert result["ece"] is not None
    assert result["ece_reason"] is None


def test_ece_skipped_when_confidence_missing():
    rows, labels = _make_rows()
    for r in rows:
        del r["confidence"]
    result = summarize(rows, labels)
    assert result["ece"] is None
    assert "missing" in result["ece_reason"]


def test_empty_input():
    result = summarize([], [])
    assert result["bracket_match"] is None
    assert result["n_pairs"] == 0
    assert result["ev"] == "n/a (live-only, no historical odds)"
