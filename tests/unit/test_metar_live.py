"""Live METAR parse: timestamp resolution + canonical schema (offline; no network)."""

from __future__ import annotations

from datetime import datetime, timezone

from core.ingest.metar_live import parse_metar_lines

_NOW = datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc)
_RAW = (
    "METAR NZWN 301730Z AUTO 01016KT 9999 SCT039/// 15/08 Q1018\n"
    "METAR NZWN 300600Z AUTO 02010KT 9999 SCT044/// 13/09 Q1021\n"
    "METAR NZWN 282300Z AUTO 36012KT 9999 FEW040 M01/M03 Q1015\n"  # month-prior day, negative T
    "\n"
)


def test_parse_resolves_timestamps_and_schema():
    df = parse_metar_lines(_RAW, now_utc=_NOW)
    assert df.height == 3
    assert df["ts_utc"].to_list()[0] == datetime(2026, 5, 28, 23, 0, tzinfo=timezone.utc)
    assert df["ts_utc"].to_list()[-1] == datetime(2026, 5, 30, 17, 30, tzinfo=timezone.utc)
    assert set(["ts_utc", "metar", "tmpf", "drct", "sknt", "alti"]).issubset(df.columns)
    # wind + QNH extracted from the latest line (01016KT, Q1018)
    last = df.filter(df["ts_utc"] == datetime(2026, 5, 30, 17, 30, tzinfo=timezone.utc)).row(0, named=True)
    assert last["drct"] == 10.0 and last["sknt"] == 16.0 and last["alti"] is not None


def test_future_token_rolls_back_a_month():
    # 'now' = May 30 18:00. A token for day 30 at 20:00 is later today (future) -> previous
    # month (April 30 20:00 exists).
    df = parse_metar_lines("METAR NZWN 302000Z AUTO 01010KT 9999 12/08 Q1010\n", now_utc=_NOW)
    assert df.height == 1
    assert df["ts_utc"].to_list()[0] == datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc)


def test_empty_input_yields_typed_empty_frame():
    df = parse_metar_lines("\nNO METAR found\n", now_utc=_NOW)
    assert df.height == 0 and "ts_utc" in df.columns
