"""GFS GRIB2 S3 byte-range index logic (Phase 4 Option 1; eccodes-FREE on purpose).

This module contains ONLY pure functions: S3 key construction and `.idx` parsing /
byte-range computation. It imports no GRIB libraries, so it is safe to unit-test in
CI without putting eccodes on any import path (REQ-MOD-6 determinism guardrail: the
deterministic runtime must never transitively import eccodes/cfgrib).

Source: AWS Open Data ``noaa-gfs-bdp-pds`` (anonymous HTTPS). Each GFS cycle ships a
``.idx`` sidecar listing every GRIB message with its starting byte offset. To pull
ONLY the 2 m temperature message we read the ``.idx``, find the ``TMP:2 m above
ground`` line, and Range-GET ``[start_byte, next_start-1]`` -- a few hundred KB
instead of the ~500 MB full field (reviewer guardrail: without byte-range this turns
into TBs of transfer).

GFS object layout::

    gfs.<YYYYMMDD>/<HH>/atmos/gfs.t<HH>z.pgrb2.0p25.f<FFF>        # GRIB2, 0.25deg
    gfs.<YYYYMMDD>/<HH>/atmos/gfs.t<HH>z.pgrb2.0p25.f<FFF>.idx    # text index

``.idx`` line format (colon-separated)::

    <msgnum>:<start_byte>:d=<YYYYMMDDHH>:<var>:<level>:<fcst>:
    693:520078025:d=2023060100:TMP:2 m above ground:18 hour fcst:
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

GFS_S3_BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
GFS_CYCLES = (0, 6, 12, 18)  # GFS runs every 6 h


@dataclass(frozen=True)
class IdxMessage:
    """One GRIB message located in a GFS pgrb2 file via its ``.idx``."""

    msgnum: int
    start_byte: int
    end_byte: int | None  # None -> open-ended range to EOF (last message)
    date_str: str  # the d=YYYYMMDDHH token, sans the leading 'd='
    var: str
    level: str
    fcst: str


def gfs_object_key(run_date: date, run_hour: int, fcst_hour: int) -> str:
    """S3 key of the 0.25deg GRIB2 file for one cycle and forecast hour."""
    if run_hour not in GFS_CYCLES:
        raise ValueError(f"run_hour {run_hour} not a GFS cycle {GFS_CYCLES}")
    if fcst_hour < 0:
        raise ValueError(f"fcst_hour must be >= 0; got {fcst_hour}")
    ymd = f"{run_date:%Y%m%d}"
    return (
        f"gfs.{ymd}/{run_hour:02d}/atmos/"
        f"gfs.t{run_hour:02d}z.pgrb2.0p25.f{fcst_hour:03d}"
    )


def gfs_grib_url(run_date: date, run_hour: int, fcst_hour: int) -> str:
    return f"{GFS_S3_BASE}/{gfs_object_key(run_date, run_hour, fcst_hour)}"


def gfs_idx_url(run_date: date, run_hour: int, fcst_hour: int) -> str:
    return f"{gfs_grib_url(run_date, run_hour, fcst_hour)}.idx"


def parse_idx(text: str) -> list[IdxMessage]:
    """Parse a GFS ``.idx`` text into messages with computed end bytes.

    ``end_byte`` is ``next_message.start_byte - 1``; the final message gets
    ``None`` (Range request must be open-ended ``bytes=start-``).
    """
    rows: list[tuple[int, int, str, str, str, str]] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(":")
        if len(parts) < 6:
            raise ValueError(f"malformed .idx line: {ln!r}")
        msgnum = int(parts[0])
        start = int(parts[1])
        date_token = parts[2]
        date_str = date_token[2:] if date_token.startswith("d=") else date_token
        var = parts[3]
        level = parts[4]
        fcst = parts[5]
        rows.append((msgnum, start, date_str, var, level, fcst))
    rows.sort(key=lambda r: r[1])  # by start_byte ascending
    out: list[IdxMessage] = []
    for i, (msgnum, start, date_str, var, level, fcst) in enumerate(rows):
        end = rows[i + 1][1] - 1 if i + 1 < len(rows) else None
        out.append(
            IdxMessage(
                msgnum=msgnum,
                start_byte=start,
                end_byte=end,
                date_str=date_str,
                var=var,
                level=level,
                fcst=fcst,
            )
        )
    return out


def find_tmp_2m(messages: list[IdxMessage]) -> IdxMessage:
    """Return the ``TMP:2 m above ground`` message; raise if absent."""
    for m in messages:
        if m.var == "TMP" and m.level == "2 m above ground":
            return m
    raise LookupError("no 'TMP:2 m above ground' message in .idx")


def byte_range_header(m: IdxMessage) -> str:
    """HTTP Range header value for the message's byte span."""
    if m.end_byte is None:
        return f"bytes={m.start_byte}-"
    return f"bytes={m.start_byte}-{m.end_byte}"


__all__ = [
    "GFS_S3_BASE",
    "GFS_CYCLES",
    "IdxMessage",
    "gfs_object_key",
    "gfs_grib_url",
    "gfs_idx_url",
    "parse_idx",
    "find_tmp_2m",
    "byte_range_header",
]
