"""Per-observation substrate — raw observations enriched with parsed integer columns."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from solarstorm._config import TZ_NAME
from solarstorm.data._metar import parse_tmp_c_int_from_row


def persist_obs(df: pl.DataFrame, data_dir: Path) -> pl.DataFrame:
    """Enrich raw IEM DataFrame with parsed columns and save to obs.parquet.

    Expects ``tmp_c_int`` and ``dq_tmp_c_int`` to already be present (from the
    upstream ingest parse loop).  Adds ``ts_local``, ``dwp_c_int``,
    ``dw_depression_c_int``, and casts skyl* columns to Int64.
    """
    df = df.with_columns(
        pl.col("valid").dt.convert_time_zone(TZ_NAME).alias("ts_local"),
    )

    dwp_vals: list[int | None] = []
    for row in df.iter_rows(named=True):
        _, dwp, _, _ = parse_tmp_c_int_from_row(row["metar"], row.get("tmpf"))
        dwp_vals.append(dwp)

    df = df.with_columns(
        pl.Series("dwp_c_int", dwp_vals, dtype=pl.Int64),
    )
    df = df.with_columns(
        (pl.col("tmp_c_int") - pl.col("dwp_c_int")).alias("dw_depression_c_int"),
    )
    # Flag physically impossible dewpoint > temperature
    df = df.with_columns(
        (pl.col("dwp_c_int") > pl.col("tmp_c_int")).alias("dwp_gt_tmp_flag"),
    )

    for col in df.columns:
        if col.startswith("skyl"):
            df = df.with_columns(pl.col(col).cast(pl.Int64, strict=False))

    df.write_parquet(data_dir / "obs.parquet")
    return df
