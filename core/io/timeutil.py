"""Time utilities (REQ-CON-4).

All internal timestamps are UTC. Conversions to local time use
``zoneinfo.ZoneInfo(tz_name)``. Comparisons between tz-naive and tz-aware
datetimes raise. ASCII-only output.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Pacific/Auckland"


def get_tz(tz_name: str = DEFAULT_TZ) -> ZoneInfo:
    """Return a ``ZoneInfo`` instance, never None."""
    return ZoneInfo(tz_name)


def to_utc(dt: datetime, assume_tz: str | None = None) -> datetime:
    """Coerce a datetime to UTC.

    If the input is tz-naive, ``assume_tz`` must be provided. The IEM CSV
    column ``valid`` is documented as UTC tz-naive; pass ``assume_tz='UTC'``.
    """
    if dt.tzinfo is None:
        if assume_tz is None:
            raise ValueError("Naive datetime without assume_tz; refuse to guess.")
        dt = dt.replace(tzinfo=ZoneInfo(assume_tz))
    return dt.astimezone(timezone.utc)


def to_local(dt_utc: datetime, tz_name: str = DEFAULT_TZ) -> datetime:
    """Convert a tz-aware UTC datetime to the configured local zone."""
    if dt_utc.tzinfo is None:
        raise ValueError("to_local requires tz-aware UTC input.")
    return dt_utc.astimezone(get_tz(tz_name))


def day_local_window(d: date, tz_name: str = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """Return the UTC ``(start, end)`` covering 24h of the local day ``d``.

    The end is exclusive (``[start, end)``). On DST start/end days the wall-clock
    window covers 23h or 25h respectively; this is intentional and matches
    REQ-CON-4 ("cover the full local day").
    """
    tz = get_tz(tz_name)
    local_start = datetime.combine(d, time(0, 0, 0), tzinfo=tz)
    local_end = datetime.combine(d + timedelta(days=1), time(0, 0, 0), tzinfo=tz)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def cp_to_utc(d: date, cp_hhmm: str) -> datetime:
    """Build the UTC datetime for the integer-hour CP ``cp_hhmm`` ('HH:00') on local date ``d``.

    The CP is defined as a UTC integer hour (REQ-CON-6); ``d`` is the *local* date the CP
    targets. Return value is a tz-aware UTC datetime.
    """
    if len(cp_hhmm) != 5 or cp_hhmm[2] != ":":
        raise ValueError(f"Invalid CP format '{cp_hhmm}', expected 'HH:MM'.")
    hh = int(cp_hhmm[:2])
    mm = int(cp_hhmm[3:])
    if mm != 0:
        raise ValueError(f"CP must be on integer hour (REQ-CON-6); got '{cp_hhmm}'.")
    if not 0 <= hh <= 23:
        raise ValueError(f"CP hour out of range: {hh}.")
    start_utc, end_utc = day_local_window(d)
    # The CP targets local date d. We pick the unique UTC HH:00:00 that lies inside d's
    # local-day window [start_utc, end_utc). Because day_local_window covers 23-25h
    # (depending on DST), there are at most two candidates separated by 24h; we prefer
    # the earliest one that is in-window. Out-of-window means the local day does not
    # contain that integer hour - reject explicitly (do NOT silently shift dates).
    candidates = [
        datetime(start_utc.year, start_utc.month, start_utc.day, hh, 0, 0, tzinfo=timezone.utc),
        datetime(start_utc.year, start_utc.month, start_utc.day, hh, 0, 0, tzinfo=timezone.utc)
        + timedelta(days=1),
    ]
    in_window = [c for c in candidates if start_utc <= c < end_utc]
    if not in_window:
        raise RuntimeError(
            f"cp_to_utc: hour {cp_hhmm} UTC has no candidate inside local day "
            f"{d.isoformat()} ({start_utc.isoformat()}..{end_utc.isoformat()}). "
            "This should never happen for an integer-hour CP - check tz_name/DST."
        )
    return in_window[0]


def utc_naive_to_aware(dt: datetime) -> datetime:
    """Annotate a tz-naive datetime as UTC (REQ-CON-4 forbids comparing naive vs aware)."""
    if dt.tzinfo is not None:
        raise ValueError("utc_naive_to_aware called on tz-aware datetime.")
    return dt.replace(tzinfo=timezone.utc)


__all__ = [
    "DEFAULT_TZ",
    "get_tz",
    "to_utc",
    "to_local",
    "day_local_window",
    "cp_to_utc",
    "utc_naive_to_aware",
]
