"""Tmax labels: daily aggregation, CP-level k_cp, remaining_warming, settlement."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import polars as pl

from solarstorm._config import CP_SET_UTC, TZ_NAME, TMP_C_INT_PLAUSIBILITY
from solarstorm.data._calendar import cp_to_utc


@dataclass
class DayCompleteParams:
    min_obs: int = 40
    max_gap_minutes: int = 120
    min_quartile_coverage: int = 1


def risco_de_flip(tmax_dec: float) -> float:
    """Distance from the nearest .5°C rounding boundary (P1+P4).

    0.0 = exactly on a .5 boundary (no flip risk).
    0.5 = exactly at integer (max flip risk — 0.1°C decides bracket).
    """
    return round(0.5 - abs(tmax_dec - round(tmax_dec)), 10)


def remaining_warming(*, tmax: int, k_cp: int) -> int:
    """How much warming remains after the checkpoint. Core target from Onda 3."""
    return tmax - k_cp


def build_tmax_labels(
    obs: pl.DataFrame,
    params: DayCompleteParams,
) -> pl.DataFrame:
    """Aggregate intraday observations into per-local-date Tmax labels.

    Expects obs with columns: valid (datetime[UTC]), tmp_c_int, dq_tmp_c_int,
    tmpf, metar.

    Returns one row per local date with tmax_int, tmax_dec, tmax_hour,
    day_complete, and per-CP k_cp columns.
    """
    obs = obs.with_columns(
        pl.col("valid").dt.convert_time_zone(TZ_NAME).alias("ts_local"),
    ).with_columns(
        pl.col("ts_local").dt.date().alias("date_local"),
        pl.col("ts_local").dt.hour().alias("hour_local"),
    )

    valid = obs.filter(pl.col("dq_tmp_c_int") != "missing")

    # --- Daily aggregates ---
    daily = valid.group_by("date_local").agg([
        pl.col("tmp_c_int").max().alias("tmax_int"),
        pl.col("tmpf").max().alias("tmpf_max"),
        pl.col("tmp_c_int").min().alias("tmin_int"),
        pl.col("tmpf").min().alias("tmpf_min"),
        pl.col("ts_local").count().alias("n_obs"),
        pl.col("ts_local").sort().diff().dt.total_minutes().max().alias("max_gap_min"),
        # Tmax hour: hour_local at which tmp_c_int == max (first occurrence)
        pl.col("hour_local")
          .sort_by("tmp_c_int", descending=True)
          .first()
          .alias("tmax_hour_local"),
    ])

    # Tmax decimal from tmpf (P1: internal decimal, not integer)
    daily = daily.with_columns(
        ((pl.col("tmpf_max") - 32.0) * 5.0 / 9.0).alias("tmax_dec"),
        ((pl.col("tmpf_min") - 32.0) * 5.0 / 9.0).alias("tmin_dec"),
    )

    # day_complete gate
    daily = daily.with_columns(
        (
            (pl.col("n_obs") >= params.min_obs)
            & (pl.col("max_gap_min").fill_null(0) <= params.max_gap_minutes)
        ).alias("day_complete")
    )

    # --- Per-CP k_cp ---
    for cp_str in CP_SET_UTC:
        col_name = f"k_cp__cp_{cp_str.replace(':', '')}"
        kcp_rows = []
        for row in daily.iter_rows(named=True):
            d = row["date_local"]
            # cp is tz-aware (Pacific/Auckland); convert to UTC so the `<`
            # comparison against the UTC-typed `valid` column is well-typed.
            cp = cp_to_utc(d, cp_str, TZ_NAME).astimezone(dt.timezone.utc)
            # Subset obs for this date where ts_utc < cp_utc
            day_obs = obs.filter(
                (pl.col("date_local") == d)
                & (pl.col("valid") < cp)
                & (pl.col("dq_tmp_c_int") != "missing")
            )
            if day_obs.height > 0:
                kcp_rows.append({"date_local": d, col_name: int(day_obs["tmp_c_int"].max())})
            else:
                kcp_rows.append({"date_local": d, col_name: None})

        kcp_map = pl.DataFrame(
            kcp_rows,
            schema={"date_local": pl.Date, col_name: pl.Int64},
        )
        daily = daily.join(kcp_map, on="date_local", how="left")

    # --- tmax_hour: local hour-of-day integer of the max (test contract) ---
    daily = daily.with_columns(
        pl.col("tmax_hour_local").alias("tmax_hour")
    )

    # --- Tmax hour in UTC ---
    daily = daily.with_columns(
        pl.when(pl.col("tmax_hour_local").is_not_null())
          .then(
              pl.col("date_local").cast(pl.Utf8)
              + " " + pl.col("tmax_hour_local").cast(pl.Utf8).str.zfill(2)
              + ":00:00"
          )
          .otherwise(None)
          .alias("tmax_hour_str")
    )
    daily = daily.with_columns(
        pl.col("tmax_hour_str").str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S")
        .dt.replace_time_zone(TZ_NAME)
        .dt.convert_time_zone("UTC")
        .alias("tmax_hour_utc")
    )

    # --- 24h scan: flag Tmax at atypical hours (P2, audit #9) ---
    daily = daily.with_columns(
        ((pl.col("tmax_hour_local") < 6) | (pl.col("tmax_hour_local") > 18))
        .alias("tmax_atypical_hour")
    )

    # --- risco_de_flip (P1+P4) ---
    daily = daily.with_columns(
        pl.col("tmax_dec").map_elements(risco_de_flip, return_dtype=pl.Float64).alias("risco_de_flip")
    )

    return daily
