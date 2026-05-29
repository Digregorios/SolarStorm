"""Smoothed monthly climatology for Tmax (design 8 baseline contract).

Climatology is fit **only** on the train split (REQ - design "train-only contract").
Smoothing is a 31-day rolling mean on calendar day-of-year with seasonal wrap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl


@dataclass(frozen=True)
class Climatology:
    """Monthly tmax climatology smoothed across day-of-year."""

    by_doy: dict[int, dict[str, float]]
    by_month: dict[int, dict[str, float]]
    train_window: tuple[date, date]
    n_train_days: int

    def tmax_dec_for(self, d: date) -> float:
        """Smoothed mean tmax for the day (decimal degC). Falls back to monthly mean if missing."""
        doy = d.timetuple().tm_yday
        if doy in self.by_doy:
            return self.by_doy[doy]["mean"]
        return self.by_month[d.month]["mean"]

    def percentiles_for(
        self, d: date, *, p_low: float = 0.1, p_high: float = 0.9
    ) -> tuple[float, float]:
        """Return (p10, p90) of tmax decimal for the day's month."""
        m = self.by_month[d.month]
        return m[f"p{int(p_low * 100):02d}"], m[f"p{int(p_high * 100):02d}"]

    def to_dict(self) -> dict[str, object]:
        return {
            "n_train_days": self.n_train_days,
            "train_window": [self.train_window[0].isoformat(), self.train_window[1].isoformat()],
            "n_doy_buckets": len(self.by_doy),
        }


def fit_climatology(
    labels: pl.DataFrame,
    *,
    train_start: date,
    train_end: date,
    smoothing_window_days: int = 31,
) -> Climatology:
    """Fit a smoothed monthly+daily climatology on the train slice only.

    ``labels`` must contain ``date_local`` (pl.Date) and ``tmax_int`` (Int).
    """
    if "date_local" not in labels.columns or "tmax_int" not in labels.columns:
        raise ValueError("labels must have date_local, tmax_int")
    train = labels.filter(
        (pl.col("date_local") >= train_start)
        & (pl.col("date_local") <= train_end)
        & pl.col("day_complete")
        & pl.col("tmax_int").is_not_null()
    )
    n = train.height
    if n < 365:
        raise ValueError(
            f"Climatology requires >= 365 train days (got {n}); "
            "REQ-design 16 v1 mandates >= 12 months."
        )

    train = train.with_columns(
        pl.col("date_local").dt.ordinal_day().alias("doy"),
        pl.col("date_local").dt.month().alias("month"),
    )

    # Per-DOY raw mean
    doy_stats = (
        train.group_by("doy")
        .agg(
            pl.col("tmax_int").mean().alias("raw_mean"),
            pl.col("tmax_int").count().alias("n"),
        )
        .sort("doy")
    )

    # Build a 366-length array, fill missing with seasonal interp.
    means = np.full(367, np.nan)
    for row in doy_stats.iter_rows(named=True):
        means[int(row["doy"])] = float(row["raw_mean"])

    # Linear interp through NaNs (with circular wrap)
    valid_idx = np.where(~np.isnan(means[1:367]))[0] + 1
    if valid_idx.size == 0:
        raise RuntimeError("No valid DOY in train.")
    if valid_idx.size < 366:
        all_idx = np.arange(1, 367)
        means[1:367] = np.interp(all_idx, valid_idx, means[valid_idx])

    # Circular smoothing 31-day window
    half = smoothing_window_days // 2
    series = means[1:367]
    extended = np.concatenate([series[-half:], series, series[:half]])
    kernel = np.ones(smoothing_window_days) / smoothing_window_days
    smoothed = np.convolve(extended, kernel, mode="valid")
    by_doy = {int(doy): {"mean": float(smoothed[doy - 1])} for doy in range(1, 367)}

    # Monthly summary
    month_stats = (
        train.group_by("month")
        .agg(
            pl.col("tmax_int").mean().alias("mean"),
            pl.col("tmax_int").quantile(0.1, "linear").alias("p10"),
            pl.col("tmax_int").quantile(0.5, "linear").alias("p50"),
            pl.col("tmax_int").quantile(0.9, "linear").alias("p90"),
            pl.col("tmax_int").count().alias("n"),
        )
        .sort("month")
    )
    by_month: dict[int, dict[str, float]] = {}
    for row in month_stats.iter_rows(named=True):
        by_month[int(row["month"])] = {
            "mean": float(row["mean"]),
            "p10": float(row["p10"]),
            "p50": float(row["p50"]),
            "p90": float(row["p90"]),
            "n": int(row["n"]),
        }

    return Climatology(
        by_doy=by_doy,
        by_month=by_month,
        train_window=(train_start, train_end),
        n_train_days=n,
    )


__all__ = ["Climatology", "fit_climatology"]
