"""Permanent CI leakage gate for NWP selections (review D5/D6, plan item 5).

The Phase-4 evaluator computes the frozen-observation NWP check at runtime
(``audits.phases.nwp_timestamps.run_phase``), but a runtime-only check rots: if a
future refactor stops calling it, causality regressions ship silently. This test
pins the invariant directly - every selected NWP row MUST satisfy
``run_time_utc <= cp_utc - safety_margin`` - so it stays green every phase and
fails loudly the moment a non-causal selection appears.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from audits.phases.nwp_timestamps import run_phase


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


CP = _utc(2024, 6, 1, 23, 0)
MARGIN = timedelta(minutes=60)
CUTOFF = CP - MARGIN  # 22:00 UTC


def test_causal_selection_passes():
    """run_time exactly at the cutoff is allowed (<=)."""
    selections = [
        {"cp_utc": CP, "run_time_utc": _utc(2024, 6, 1, 22, 0), "model": "ensemble"},
        {"cp_utc": CP, "run_time_utc": _utc(2024, 6, 1, 18, 0), "model": "ecmwf_ifs_hres"},
    ]
    res = run_phase(nwp_selections=selections, safety_margin=MARGIN)
    assert res["passed"] is True
    assert res["details"]["n_violations"] == 0


def test_one_minute_past_cutoff_is_a_violation():
    """22:01 > 22:00 cutoff -> the row leaks a too-fresh run."""
    selections = [
        {"cp_utc": CP, "run_time_utc": _utc(2024, 6, 1, 22, 1), "model": "ncep_gfs_global"},
    ]
    res = run_phase(nwp_selections=selections, safety_margin=MARGIN)
    assert res["passed"] is False
    assert res["details"]["n_violations"] == 1
    assert res["details"]["violations_sample"][0]["model"] == "ncep_gfs_global"


def test_post_cp_run_is_a_violation():
    """A run issued AFTER the CP is the canonical leakage case."""
    selections = [
        {"cp_utc": CP, "run_time_utc": _utc(2024, 6, 2, 0, 0), "model": "ensemble"},
    ]
    res = run_phase(nwp_selections=selections, safety_margin=MARGIN)
    assert res["passed"] is False
    assert res["details"]["n_violations"] == 1


def test_mixed_batch_reports_only_the_leaks():
    selections = [
        {"cp_utc": CP, "run_time_utc": _utc(2024, 6, 1, 12, 0), "model": "a"},   # ok
        {"cp_utc": CP, "run_time_utc": _utc(2024, 6, 1, 23, 30), "model": "b"},  # leak
        {"cp_utc": CP, "run_time_utc": _utc(2024, 6, 1, 21, 0), "model": "c"},   # ok
    ]
    res = run_phase(nwp_selections=selections, safety_margin=MARGIN)
    assert res["passed"] is False
    assert res["details"]["n_checked"] == 3
    assert res["details"]["n_violations"] == 1
    assert res["details"]["violations_sample"][0]["model"] == "b"


def test_missing_field_is_flagged_not_silently_passed():
    selections = [{"cp_utc": CP, "model": "no_run_time"}]
    res = run_phase(nwp_selections=selections, safety_margin=MARGIN)
    assert res["passed"] is False
    assert res["details"]["n_violations"] == 1


def test_empty_selection_is_inconclusive_not_pass():
    """No selections -> passed is None (inconclusive), never a silent True."""
    res = run_phase(nwp_selections=[], safety_margin=MARGIN)
    assert res["passed"] is None
