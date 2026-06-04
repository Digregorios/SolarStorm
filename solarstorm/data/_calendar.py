"""NZST/DST-aware calendar: local-day windows and checkpoint → UTC conversion."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

# Earliest valid checkpoint hour (local). CPs before this hour are considered
# invalid — they fall in the pre-dawn period before any meaningful trading day.
_CP_WINDOW_START_HOUR = 6


def day_local_window(d: dt.date, tz_name: str) -> tuple[dt.datetime, dt.datetime]:
    """Return UTC [start, end) covering the full local day `d` in `tz_name`.

    On DST transition days the window may be 23h or 25h.
    """
    tz = ZoneInfo(tz_name)
    local_start = dt.datetime.combine(d, dt.time.min, tzinfo=tz)
    local_end = local_start + dt.timedelta(days=1)
    return local_start, local_end


def cp_to_utc(d: dt.date, cp_hhmm: str, tz_name: str) -> dt.datetime:
    """Convert a local-date + HH:MM checkpoint string to a UTC-aware datetime.

    Args:
        d: Local date.
        cp_hhmm: Checkpoint hour as "HH:MM" (e.g. "23:00").
        tz_name: IANA timezone name.

    Returns:
        UTC-aware datetime for that checkpoint.

    Raises:
        ValueError: If the checkpoint hour is before the valid CP window start
            (_CP_WINDOW_START_HOUR) or at/after midnight of the next local day.
    """
    tz = ZoneInfo(tz_name)
    hour = int(cp_hhmm.split(":")[0])
    local_naive = dt.datetime(d.year, d.month, d.day, hour, 0, 0)
    local_aware = local_naive.replace(tzinfo=tz)

    # Valid CP window: [_CP_WINDOW_START_HOUR:00, midnight-next-day)
    cp_window_start = dt.datetime(d.year, d.month, d.day, _CP_WINDOW_START_HOUR, 0, 0, tzinfo=tz)
    cp_window_end = dt.datetime.combine(d, dt.time.min, tzinfo=tz) + dt.timedelta(days=1)
    if not (cp_window_start <= local_aware < cp_window_end):
        raise ValueError(
            f"CP {cp_hhmm} on {d} resolved to {local_aware.isoformat()}, "
            f"outside valid CP window [{cp_window_start.isoformat()}, {cp_window_end.isoformat()})"
        )

    return local_aware
