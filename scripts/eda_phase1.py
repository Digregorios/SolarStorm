"""Phase 1 EDA tables (T-1-8).

Generates 4 CSVs + reports/eda/intro.md with 10 key numbers.

Tables:
  - tmax_hour_local_by_month.csv     (hour percentiles per month)
  - early_peak_by_month.csv          (rate of tmax_hour < 12 and outliers in [0,6) U [22,24))
  - coverage_by_month.csv            (n_total, n_complete, ratio - REQ-CON-7)
  - tmax_distribution_by_month.csv   ((month, k, count))
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from core.contracts.station import load_station_config
from core.ingest.iem_csv import load_observations
from core.labels.tmax import build_tmax_labels


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    cfg = load_station_config(repo / "nzwn" / "config" / "station.yaml")
    obs, stats = load_observations(
        repo / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    out = repo / "reports" / "eda"
    out.mkdir(parents=True, exist_ok=True)

    # 1) tmax_hour_local_by_month
    df = labels.filter(
        pl.col("day_complete") & pl.col("tmax_ts_local").is_not_null()
    ).with_columns(
        pl.col("date_local").dt.month().alias("month"),
        pl.col("tmax_ts_local").dt.hour().alias("hour"),
    )
    hour_table = (
        df.group_by("month")
        .agg(
            pl.col("hour").quantile(0.10, "linear").alias("p10"),
            pl.col("hour").quantile(0.25, "linear").alias("p25"),
            pl.col("hour").quantile(0.50, "linear").alias("p50"),
            pl.col("hour").quantile(0.75, "linear").alias("p75"),
            pl.col("hour").quantile(0.90, "linear").alias("p90"),
            pl.len().alias("n"),
        )
        .sort("month")
    )
    hour_table.write_csv(out / "tmax_hour_local_by_month.csv")

    # 2) early_peak (hour < 12) and outlier (hour in [0,6) U [22,24))
    early = (
        df.with_columns(
            (pl.col("hour") < 12).alias("early_peak"),
            ((pl.col("hour") < 6) | (pl.col("hour") >= 22)).alias("outlier_hour"),
        )
        .group_by("month")
        .agg(
            pl.col("early_peak").sum().alias("n_early_peak"),
            pl.col("outlier_hour").sum().alias("n_outlier_hour"),
            pl.len().alias("n"),
        )
        .with_columns(
            (pl.col("n_early_peak") / pl.col("n")).alias("rate_early_peak"),
            (pl.col("n_outlier_hour") / pl.col("n")).alias("rate_outlier_hour"),
        )
        .sort("month")
    )
    early.write_csv(out / "early_peak_by_month.csv")

    # 3) coverage_by_month (year x month)
    cov = (
        labels.with_columns(
            pl.col("date_local").dt.year().alias("year"),
            pl.col("date_local").dt.month().alias("month"),
        )
        .group_by(["year", "month"])
        .agg(
            pl.len().alias("n_total"),
            pl.col("day_complete").sum().alias("n_complete"),
        )
        .with_columns((pl.col("n_complete") / pl.col("n_total")).alias("ratio"))
        .sort(["year", "month"])
    )
    cov.write_csv(out / "coverage_by_month.csv")

    # 4) tmax_distribution_by_month
    dist = (
        labels.filter(pl.col("day_complete") & pl.col("tmax_int").is_not_null())
        .with_columns(pl.col("date_local").dt.month().alias("month"))
        .group_by(["month", "tmax_int"])
        .agg(pl.len().alias("count"))
        .sort(["month", "tmax_int"])
    )
    dist.write_csv(out / "tmax_distribution_by_month.csv")

    # Key numbers for intro.md
    n_days = labels.height
    n_complete = int(labels["day_complete"].sum())
    coverage = n_complete / n_days if n_days else 0.0
    median_hour = float(df["hour"].median())
    early_peak_rate = float(early.select(
        (pl.col("n_early_peak").sum() / pl.col("n").sum()).alias("r")
    )["r"][0])
    outlier_rate = float(early.select(
        (pl.col("n_outlier_hour").sum() / pl.col("n").sum()).alias("r")
    )["r"][0])
    overall_p50 = int(labels.filter(pl.col("day_complete"))["tmax_int"].median())
    overall_min = int(labels.filter(pl.col("day_complete"))["tmax_int"].min())
    overall_max = int(labels.filter(pl.col("day_complete"))["tmax_int"].max())
    fallback_rate = stats.fallback_rate
    n_obs = obs.height

    intro = f"""# EDA intro - Phase 1 (T-1-8, REQ-MET-2, REQ-CON-7)

## 10 key numbers

1. n_obs (raw IEM rows): {n_obs}
2. parser fallback_rate: {fallback_rate:.6f}
3. n_days: {n_days}
4. n_day_complete: {n_complete} ({coverage:.4f})
5. tmax_int median (complete days): {overall_p50}
6. tmax_int min: {overall_min}
7. tmax_int max: {overall_max}
8. tmax_hour_local median: {median_hour}
9. early_peak_rate (hour < 12): {early_peak_rate:.4f}
10. outlier_hour_rate (hour in [0,6) U [22,24)): {outlier_rate:.4f}

## Tables

- `tmax_hour_local_by_month.csv` - p10..p90 of local Tmax hour per month
- `early_peak_by_month.csv` - rate of early peak / outlier hour per month
- `coverage_by_month.csv` - day_complete ratio per (year, month)
- `tmax_distribution_by_month.csv` - histogram (month, k, count)
"""
    (out / "intro.md").write_text(intro, encoding="ascii")
    print(intro)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
