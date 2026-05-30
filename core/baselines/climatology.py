"""Smoothed monthly climatology for Tmax (design 8 baseline contract).

Climatology is fit **only** on the train split (REQ - design "train-only contract").
Smoothing is a 31-day rolling mean on calendar day-of-year with seasonal wrap.

Also provides ``TmaxHourClimatology`` (design 4.5.2.1): the climatological
distribution of the *local hour* at which Tmax occurs, per month. This is used
ONLY to (a) center the forward max-of-trajectory window and (b) feed a
lead-aware confidence signal - it is **never** the anchor itself (the anchor is
the windowed max of a causal NWP run; the single climatological hour was the
fragile v1.0 anchor this amendment replaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

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


@dataclass(frozen=True)
class TmaxHourClimatology:
    """Distribution of the local hour at which Tmax occurs, per month (design 4.5.2.1).

    ``by_month[m]`` carries ``{"center_h", "lo_h", "hi_h", "n"}`` where the hours
    are LOCAL clock hours (float, e.g. 14.5) and ``[lo_h, hi_h]`` is the
    inter-quantile spread used to size the forward anchor window.

    REGIME DIMENSION (deferred, versioned): design 4.5.2.1 specifies a
    ``(month, regime)`` distribution, but the regime GMM (``nzwn/regimes/gmm_v1.pkl``,
    design section 7) is a Phase-7 artifact that does not exist yet. Conditioning
    on regimes now would mean inventing labels, so v1.1 ships the month-only
    marginal and the regime split is tracked as a future ``NWP_SOURCE_VERSION``
    bump. The API takes ``regime=None`` today and will accept a regime id later
    without a signature change.
    """

    by_month: dict[int, dict[str, float]]
    tz_name: str
    train_window: tuple[date, date]

    def window_local_hours(self, d: date, *, regime: int | None = None) -> tuple[float, float]:
        """Return the ``(lo_h, hi_h)`` LOCAL-hour window for date ``d``'s month.

        ``regime`` is accepted for forward-compat but ignored in v1.1 (see class
        docstring); passing a non-None value raises so a caller cannot silently
        believe regime conditioning is active when it is not.
        """
        if regime is not None:
            raise NotImplementedError(
                "regime-conditioned Tmax-hour requires nzwn/regimes/gmm_v1.pkl "
                "(Phase 7); v1.1 ships the month-only marginal. Tracked as a "
                "future NWP_SOURCE_VERSION bump."
            )
        m = self.by_month[d.month]
        return m["lo_h"], m["hi_h"]

    def window_utc(
        self, d: date, cp_utc: datetime, *, regime: int | None = None
    ) -> tuple[datetime, datetime]:
        """Map the local-hour window for ``d`` to a UTC ``[start, end]`` interval.

        The window is anchored on the local day ``d`` (where Tmax is defined,
        REQ-CON-4). Both bounds are tz-aware UTC. ``cp_utc`` is accepted so future
        versions can clamp the window to causal leads; v1.1 returns the full
        climatological window and leaves causal clamping to the anchor selector.
        """
        lo_h, hi_h = self.window_local_hours(d, regime=regime)
        tz = ZoneInfo(self.tz_name)
        lo_local = datetime.combine(d, time(0, 0), tzinfo=tz) + timedelta(hours=lo_h)
        hi_local = datetime.combine(d, time(0, 0), tzinfo=tz) + timedelta(hours=hi_h)
        return lo_local.astimezone(timezone.utc), hi_local.astimezone(timezone.utc)


def fit_tmax_hour_climatology(
    labels: pl.DataFrame,
    *,
    train_start: date,
    train_end: date,
    tz_name: str = "Pacific/Auckland",
    q_low: float = 0.1,
    q_high: float = 0.9,
) -> TmaxHourClimatology:
    """Fit the per-month local-hour-of-Tmax distribution on the train slice only.

    ``labels`` must contain ``date_local``, ``day_complete`` and ``tmax_ts_local``
    (the tz-aware local timestamp of the day's Tmax, emitted by
    ``build_tmax_labels``). The hour is taken as ``hour + minute/60`` so the
    window center is sub-hourly. Months with < 10 train days fall back to a wide
    default window so an under-sampled month never produces a degenerate point.
    """
    needed = {"date_local", "day_complete", "tmax_ts_local"}
    if not needed.issubset(labels.columns):
        raise ValueError(f"labels must have {sorted(needed)}")
    train = labels.filter(
        (pl.col("date_local") >= train_start)
        & (pl.col("date_local") <= train_end)
        & pl.col("day_complete")
        & pl.col("tmax_ts_local").is_not_null()
    ).with_columns(
        (
            pl.col("tmax_ts_local").dt.hour().cast(pl.Float64)
            + pl.col("tmax_ts_local").dt.minute().cast(pl.Float64) / 60.0
        ).alias("tmax_hour_local"),
        pl.col("date_local").dt.month().alias("month"),
    )
    if train.height < 365:
        raise ValueError(
            f"Tmax-hour climatology needs >= 365 train days (got {train.height})."
        )

    by_month: dict[int, dict[str, float]] = {}
    for m in range(1, 13):
        sub = train.filter(pl.col("month") == m)["tmax_hour_local"].to_numpy()
        if sub.size < 10:
            # Under-sampled month: wide default centred on local mid-afternoon.
            by_month[m] = {"center_h": 14.0, "lo_h": 11.0, "hi_h": 17.0, "n": float(sub.size)}
            continue
        lo = float(np.quantile(sub, q_low))
        hi = float(np.quantile(sub, q_high))
        center = float(np.median(sub))
        # Guard against a zero-width window when Tmax hour is highly concentrated.
        if hi - lo < 2.0:
            lo, hi = center - 1.0, center + 1.0
        by_month[m] = {"center_h": center, "lo_h": lo, "hi_h": hi, "n": float(sub.size)}

    return TmaxHourClimatology(
        by_month=by_month, tz_name=tz_name, train_window=(train_start, train_end)
    )


__all__ = [
    "Climatology",
    "fit_climatology",
    "TmaxHourClimatology",
    "fit_tmax_hour_climatology",
]
