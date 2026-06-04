import polars as pl
import datetime as dt
from solarstorm.eda._regimes import classify_regime


def make_obs(rows: list[tuple[int, float, float, float, float]]):
    """(hour_local, tmp_c, wind_dir, wind_speed_kt, dwp_c, p01i)"""
    return pl.DataFrame([
        {
            "ts_local": dt.datetime(2025, 6, 15, h, 0, 0),
            "tmp_c_int": int(t), "wind_dir_deg": wd, "sknt": ws,
            "dwp_c_int": int(dwp), "p01i": p,
        }
        for h, t, wd, ws, dwp, p in rows
    ])


def test_classify_calm_day():
    obs = make_obs([
        (6, 8, 360, 5, 6, 0.0),
        (9, 10, 350, 5, 7, 0.0),
        (12, 13, 340, 6, 8, 0.0),
        (15, 14, 350, 5, 7, 0.0),
        (18, 12, 360, 4, 6, 0.0),
    ])
    regime, flags = classify_regime(obs)
    assert regime == "calm"
    assert not flags.get("intraday_regime_change", False)


def test_classify_late_warming():
    obs = make_obs([
        (6, 10, 320, 8, 8, 0.0),
        (9, 12, 330, 10, 9, 0.0),
        (12, 14, 340, 12, 10, 0.0),
        (15, 15, 340, 10, 10, 0.0),
        (18, 16, 330, 12, 11, 0.0),
        (21, 19, 320, 15, 10, 0.0),   # jump after 21Z NZST (9Z UTC)
    ])
    regime, flags = classify_regime(obs)
    assert regime == "late_warming"


def test_classify_foehn_nw():
    obs = make_obs([
        (6, 12, 320, 18, 6, 0.0),   # NW wind, dewpoint depression = 6°C
        (9, 14, 330, 20, 8, 0.0),
        (12, 17, 340, 22, 9, 0.0),  # depression > 4°C
        (15, 17, 330, 20, 10, 0.0),
    ])
    regime, flags = classify_regime(obs)
    assert regime == "foehn_nw"
