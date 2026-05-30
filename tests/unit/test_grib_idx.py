"""Unit tests for GFS .idx byte-range logic (eccodes-free; CI-safe).

These guard the part of the Option-1 GRIB path that runs WITHOUT eccodes: key
construction, .idx parsing, TMP:2m selection, and Range header computation. Keeping
this logic pure means CI can verify it while eccodes/cfgrib stay strictly off the
runtime import graph (REQ-MOD-6 determinism guardrail).
"""

from __future__ import annotations

from datetime import date

import pytest

from core.ingest.grib_idx import (
    GFS_S3_BASE,
    byte_range_header,
    find_tmp_2m,
    gfs_grib_url,
    gfs_idx_url,
    gfs_object_key,
    parse_idx,
)

# A trimmed but realistic GFS .idx excerpt (byte offsets monotonic, out of order on
# purpose to exercise the sort).
_IDX = """\
1:0:d=2023060100:PRES:surface:18 hour fcst:
693:520078025:d=2023060100:TMP:2 m above ground:18 hour fcst:
694:520600000:d=2023060100:RH:2 m above ground:18 hour fcst:
2:200000:d=2023060100:HGT:surface:18 hour fcst:
"""


def test_object_key_and_urls():
    key = gfs_object_key(date(2023, 6, 1), 0, 18)
    assert key == "gfs.20230601/00/atmos/gfs.t00z.pgrb2.0p25.f018"
    assert gfs_grib_url(date(2023, 6, 1), 0, 18) == f"{GFS_S3_BASE}/{key}"
    assert gfs_idx_url(date(2023, 6, 1), 0, 18) == f"{GFS_S3_BASE}/{key}.idx"


def test_object_key_rejects_noncycle_hour():
    with pytest.raises(ValueError):
        gfs_object_key(date(2023, 6, 1), 3, 0)


def test_object_key_rejects_negative_fcst():
    with pytest.raises(ValueError):
        gfs_object_key(date(2023, 6, 1), 0, -1)


def test_parse_idx_sorts_and_computes_end_bytes():
    msgs = parse_idx(_IDX)
    # sorted by start_byte: 0, 200000, 520078025, 520600000
    starts = [m.start_byte for m in msgs]
    assert starts == sorted(starts)
    # end_byte = next.start - 1, last is None
    assert msgs[0].end_byte == 199999
    assert msgs[1].end_byte == 520078024
    assert msgs[-1].end_byte is None
    assert msgs[0].date_str == "2023060100"


def test_find_tmp_2m_selects_the_right_message():
    msgs = parse_idx(_IDX)
    tmp = find_tmp_2m(msgs)
    assert tmp.var == "TMP"
    assert tmp.level == "2 m above ground"
    assert tmp.start_byte == 520078025
    # next message after TMP starts at 520600000 -> end is that minus 1
    assert tmp.end_byte == 520599999


def test_find_tmp_2m_raises_when_absent():
    msgs = parse_idx(
        "1:0:d=2023060100:PRES:surface:18 hour fcst:\n"
        "2:100:d=2023060100:RH:2 m above ground:18 hour fcst:\n"
    )
    with pytest.raises(LookupError):
        find_tmp_2m(msgs)


def test_byte_range_header_bounded_and_open_ended():
    msgs = parse_idx(_IDX)
    tmp = find_tmp_2m(msgs)
    assert byte_range_header(tmp) == "bytes=520078025-520599999"
    last = msgs[-1]
    assert last.end_byte is None
    assert byte_range_header(last) == f"bytes={last.start_byte}-"


def test_parse_idx_rejects_malformed_line():
    with pytest.raises(ValueError):
        parse_idx("1:0:d=2023060100:TMP\n")
