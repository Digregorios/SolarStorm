"""DST tests for core.io.timeutil (REQ-CON-4)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from core.io.timeutil import cp_to_utc, day_local_window, get_tz, to_local


# NZ DST 2024: starts 2024-09-29 (clocks +1), ends 2024-04-07 (clocks -1).
# NZ DST 2025: starts 2025-09-28, ends 2025-04-06.

DST_DATES = [
    (date(2024, 4, 6), 24),    # day before DST end (24h, NZDT)
    (date(2024, 4, 7), 25),    # DST end day -> 25h local
    (date(2024, 9, 28), 24),   # day before DST start
    (date(2024, 9, 29), 23),   # DST start day -> 23h local
    (date(2025, 4, 5), 24),
    (date(2025, 4, 6), 25),
    (date(2025, 9, 27), 24),
    (date(2025, 9, 28), 23),
    (date(2024, 7, 15), 24),   # winter, NZST, 24h
    (date(2024, 1, 15), 24),   # summer, NZDT, 24h
]


@pytest.mark.parametrize("d,expected_hours", DST_DATES)
def test_day_local_window_covers_full_local_day(d: date, expected_hours: int):
    start_utc, end_utc = day_local_window(d, tz_name="Pacific/Auckland")
    delta = end_utc - start_utc
    assert delta == timedelta(hours=expected_hours), (
        f"{d}: expected {expected_hours}h, got {delta}"
    )
    assert to_local(start_utc).hour == 0
    assert to_local(start_utc).date() == d


def test_cp_to_utc_within_local_day():
    d = date(2025, 12, 1)  # summer, NZDT (UTC+13)
    cp = cp_to_utc(d, "23:00")
    start_utc, end_utc = day_local_window(d)
    assert start_utc <= cp < end_utc
    # Map back: 23:00 UTC == 12:00 NZDT
    assert to_local(cp).hour == 12


def test_cp_to_utc_winter():
    d = date(2025, 7, 1)  # winter, NZST (UTC+12)
    cp = cp_to_utc(d, "23:00")
    assert to_local(cp).hour == 11


def test_cp_to_utc_rejects_non_integer_hour():
    with pytest.raises(ValueError):
        cp_to_utc(date(2025, 1, 1), "23:30")


def test_cp_to_utc_raises_when_hour_outside_local_day():
    """Sanity guard: if a buggy caller asks for an hour that no UTC HH:00 maps into,
    the function must raise instead of returning a silently-shifted candidate.

    For NZ this never triggers naturally (NZDT/NZST keep all 24 hours present), so
    we monkey-patch ``day_local_window`` to return a 30-minute window that intentionally
    excludes any integer UTC hour.
    """
    import core.io.timeutil as tu

    real = tu.day_local_window
    try:
        def fake(_d, **_kw):
            from datetime import timezone
            base = datetime(2025, 1, 14, 23, 15, tzinfo=timezone.utc)
            return base, base.replace(minute=45)
        tu.day_local_window = fake  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="no candidate inside local day"):
            tu.cp_to_utc(date(2025, 1, 15), "23:00")
    finally:
        tu.day_local_window = real  # type: ignore[assignment]
