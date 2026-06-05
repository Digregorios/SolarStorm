"""NZST/DST-aware calendar: local-day windows and checkpoint → UTC conversion."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


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
        ValueError: If the resolved UTC hour falls outside the local-day window.
    """
    tz = ZoneInfo(tz_name)
    hour = int(cp_hhmm.split(":")[0])
    local_naive = dt.datetime(d.year, d.month, d.day, hour, 0, 0)
    local_aware = local_naive.replace(tzinfo=tz)

    window_start, window_end = day_local_window(d, tz_name)
    if not (window_start <= local_aware < window_end):
        raise ValueError(
            f"CP {cp_hhmm} on {d} resolved to {local_aware.isoformat()}, "
            f"outside local-day window [{window_start.isoformat()}, {window_end.isoformat()})"
        )

    return local_aware
