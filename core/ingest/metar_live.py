"""Live METAR fetch from aviationweather.gov -> pipeline observations (REQ-DAT-1).

An intraday forecaster MUST be able to pull CURRENT observations, not only the frozen
historical IEM CSV. This module fetches raw METAR (30-min cadence) from the NOAA aviation
weather API and parses it into the SAME canonical frame the historical loader produces
(``ts_utc``, ``metar``, ``tmpf``, ``tmp_c_int``, ``dwp_c_int``, ``dq_tmp_c_int``), so the
existing label/feature/forecast path runs on fresh data unchanged.

Endpoint (same pattern for every station):
    https://aviationweather.gov/api/data/metar?ids=<ICAO>&format=raw&hours=<H>

Raw lines look like ``METAR NZWN 301730Z AUTO 01016KT 9999 SCT039/// 15/08 Q1018``. The
``DDHHMMZ`` token carries only day-of-month + time, so it is resolved to a full UTC datetime
against ``now`` (rolling back one month at the month boundary). Temperature integers come from
the raw METAR via the shared ``parse_observations`` (no second source of truth).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

import httpx
import polars as pl

from core.ingest.iem_csv import ParseStats, parse_observations

AVWX_METAR = "https://aviationweather.gov/api/data/metar"
_DDHHMM = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")
# Wind 'dddssKT' (or with gust 'dddssGggKT'); altimeter 'Qdddd' (hPa) or 'Adddd' (inHg/100).
_WIND = re.compile(r"\b(\d{3})(\d{2,3})(?:G\d{2,3})?KT\b")
_Q_HPA = re.compile(r"\bQ(\d{4})\b")
_A_INHG = re.compile(r"\bA(\d{4})\b")


def fetch_metar_raw(station: str, *, hours: int = 96, timeout: float = 60.0) -> str:
    """Fetch raw METAR text for ``station`` over the last ``hours`` (live; one call)."""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(AVWX_METAR, params={"ids": station, "format": "raw", "hours": hours})
        r.raise_for_status()
        return r.text


def _resolve_ts(dd: int, hh: int, mm: int, now_utc: datetime) -> datetime | None:
    """Resolve a METAR DDHHMM token to a full UTC datetime relative to ``now_utc``.

    The METAR carries no month/year, so anchor on ``now``: try the current year-month, then
    roll back one month. Pick the most recent candidate that is not in the future.
    """
    if not (1 <= dd <= 31 and 0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    y, m = now_utc.year, now_utc.month
    for _ in range(2):  # current month, then previous (covers the month boundary)
        try:
            cand = datetime(y, m, dd, hh, mm, tzinfo=timezone.utc)
        except ValueError:
            cand = None
        if cand is not None and cand <= now_utc:
            return cand
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return None


def _wind_qnh(metar: str) -> tuple[float | None, float | None, float | None]:
    """Extract (drct, sknt, alti_inHg) from a raw METAR for build_cp_features compatibility."""
    drct = sknt = alti = None
    w = _WIND.search(metar)
    if w:
        drct = float(int(w.group(1)))
        sknt = float(int(w.group(2)))
    q = _Q_HPA.search(metar)
    a = _A_INHG.search(metar)
    if q:
        alti = float(int(q.group(1))) / 33.8639  # hPa -> inHg (build_cp_features re-multiplies)
    elif a:
        alti = float(int(a.group(1))) / 100.0
    return drct, sknt, alti


def parse_metar_lines(text: str, *, now_utc: datetime | None = None) -> pl.DataFrame:
    """Parse raw METAR lines into a frame with the IEM CSV schema columns used downstream."""
    now_utc = now_utc or datetime.now(timezone.utc)
    rows: list[dict] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.upper().startswith("NO METAR") or "Z" not in ln:
            continue
        m = _DDHHMM.search(ln)
        if not m:
            continue
        ts = _resolve_ts(int(m.group(1)), int(m.group(2)), int(m.group(3)), now_utc)
        if ts is None:
            continue
        # tmpf from the METAR TT/DD (informative only; integer truth comes from the regex parser)
        drct, sknt, alti = _wind_qnh(ln)
        rows.append({"ts_utc": ts, "metar": ln, "tmpf": None,
                     "drct": drct, "sknt": sknt, "alti": alti})
    if not rows:
        return pl.DataFrame(schema={
            "ts_utc": pl.Datetime("us", time_zone="UTC"), "metar": pl.Utf8,
            "tmpf": pl.Float64, "drct": pl.Float64, "sknt": pl.Float64, "alti": pl.Float64,
        })
    df = pl.DataFrame(rows).unique(subset=["ts_utc"], keep="last").sort("ts_utc")
    return df


def fetch_observations(
    station: str, *, hours: int = 96, now_utc: datetime | None = None,
    tmp_min_c: int = -10, tmp_max_c: int = 40,
) -> tuple[pl.DataFrame, ParseStats]:
    """Live one-shot: fetch + parse into the canonical observations frame (+ telemetry)."""
    raw = fetch_metar_raw(station, hours=hours)
    df = parse_metar_lines(raw, now_utc=now_utc)
    return parse_observations(df, tmp_min_c=tmp_min_c, tmp_max_c=tmp_max_c)


def merge_observations(historical: pl.DataFrame, live: pl.DataFrame) -> pl.DataFrame:
    """Union historical + live observation frames, dedup on ts_utc (live wins), sorted."""
    cols = [c for c in historical.columns if c in live.columns]
    out = pl.concat([historical.select(cols), live.select(cols)], how="vertical_relaxed")
    return out.unique(subset=["ts_utc"], keep="last").sort("ts_utc")


__all__ = [
    "AVWX_METAR",
    "fetch_metar_raw",
    "parse_metar_lines",
    "fetch_observations",
    "merge_observations",
]
