"""AR(7) online corrector: no-leakage updates, dedupe, backup persistence (Phase 6)."""

from __future__ import annotations

import json

import pytest

from core.online.ar import AROnlineCorrector, DuplicateUpdateError


def test_prediction_uses_only_past_residuals():
    c = AROnlineCorrector(order=3, enabled=True)
    assert c.predict_correction() == 0.0  # empty -> no correction
    # Each prediction must reflect ONLY residuals appended before it (strictly past).
    c.update(date_local="2025-01-01", cp_utc="23:00", residual=3.0)
    assert c.predict_correction() == 3.0
    c.update(date_local="2025-01-02", cp_utc="23:00", residual=1.0)
    assert c.predict_correction() == pytest.approx(2.0)  # mean(3,1)


def test_buffer_respects_order_window():
    c = AROnlineCorrector(order=2, enabled=True)
    for i, r in enumerate([1.0, 2.0, 9.0]):
        c.update(date_local=f"2025-01-0{i+1}", cp_utc="23:00", residual=r)
    # Only the last 2 residuals (2,9) remain in the AR(2) window.
    assert c.predict_correction() == pytest.approx(5.5)


def test_disabled_corrector_is_a_noop():
    c = AROnlineCorrector(order=7, enabled=False)
    c.update(date_local="2025-01-01", cp_utc="23:00", residual=5.0)
    assert c.predict_correction() == 0.0


def test_duplicate_update_rejected():
    c = AROnlineCorrector(order=7, enabled=True)
    c.update(date_local="2025-01-01", cp_utc="23:00", residual=2.0)
    with pytest.raises(DuplicateUpdateError):
        c.update(date_local="2025-01-01", cp_utc="23:00", residual=2.0)
    # same date, different cp is allowed
    c.update(date_local="2025-01-01", cp_utc="22:00", residual=1.0)


def test_save_backs_up_existing_state_then_roundtrips(tmp_path):
    c = AROnlineCorrector(order=4, enabled=True)
    c.update(date_local="2025-01-01", cp_utc="23:00", residual=2.0)
    c.save(tmp_path, "2025-01-01")
    assert not (tmp_path / "2025-01-01.bak.json").exists()  # first write, no backup

    # second save backs up the prior state
    c.update(date_local="2025-01-02", cp_utc="23:00", residual=4.0)
    c.save(tmp_path, "2025-01-01")
    bak = json.loads((tmp_path / "2025-01-01.bak.json").read_text(encoding="ascii"))
    assert bak["buffer"] == [2.0]  # backup holds the pre-update state

    reloaded = AROnlineCorrector.load(tmp_path, "2025-01-01")
    assert reloaded.predict_correction() == pytest.approx(3.0)  # mean(2,4)
    # dedupe survives a round-trip: the persisted keys still block a repeat
    with pytest.raises(DuplicateUpdateError):
        reloaded.update(date_local="2025-01-01", cp_utc="23:00", residual=0.0)
