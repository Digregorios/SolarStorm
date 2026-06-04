import datetime as dt
from zoneinfo import ZoneInfo
from solarstorm.data._calendar import cp_to_utc, day_local_window

NZST = ZoneInfo("Pacific/Auckland")

def test_day_local_window_standard_day():
    d = dt.date(2025, 6, 15)  # winter, no DST
    start, end = day_local_window(d, "Pacific/Auckland")
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert (end - start) == dt.timedelta(hours=24)

def test_cp_to_utc_23z_standard():
    d = dt.date(2025, 6, 15)
    result = cp_to_utc(d, "23:00", "Pacific/Auckland")
    assert result.hour == 23
    assert result.tzinfo is not None
    # 23:00 NZST = 11:00 UTC
    assert result.utcoffset() == dt.timedelta(hours=12)

def test_cp_to_utc_20z_standard():
    d = dt.date(2025, 6, 15)
    result = cp_to_utc(d, "20:00", "Pacific/Auckland")
    assert result.hour == 20

def test_cp_to_utc_rejects_out_of_window():
    d = dt.date(2025, 6, 15)
    try:
        cp_to_utc(d, "05:00", "Pacific/Auckland")
        assert False, "should have raised"
    except ValueError:
        pass
