"""Tmax labels (REQ-CON-3/4/7, REQ-SPK-1, design 4.4).

For each local date ``d`` we compute:

- ``tmax_int``: max of ``tmp_c_int`` (T_obs_int) over the 24h local window.
- ``tmin_int``: min over the same window.
- ``day_complete`` per REQ-CON-7.
- ``late_spike_l1__cp_HH``: one bool per CP in CP_SET; ``True`` iff
  ``k_eod != k_cp(d, cp)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, List

import polars as pl

from core.io.timeutil import cp_to_utc, day_local_window


@dataclass(frozen=True)
class DayCompleteParams:
    min_obs: int = 40
    max_gap_minutes: int = 120
    min_quartile_coverage: int = 1


def _quartile_coverage(times_local: list[datetime]) -> bool:
    """Whether each 6h-quartile of the local day has >= 1 observation."""
    quartiles = [0, 6, 12, 18]
    counts = [0, 0, 0, 0]
    for t in times_local:
        h = t.hour
        for i, q in enumerate(quartiles):
            if q <= h < q + 6:
                counts[i] += 1
                break
    return all(c >= 1 for c in counts)


def _max_gap_minutes(timestamps: list[datetime]) -> int:
    if len(timestamps) < 2:
        return 24 * 60
    sorted_ts = sorted(timestamps)
    gaps = [
        int((b - a).total_seconds() // 60)
        for a, b in zip(sorted_ts, sorted_ts[1:], strict=False)
    ]
    return max(gaps) if gaps else 24 * 60


def _is_day_complete(
    times_utc: list[datetime],
    times_local: list[datetime],
    params: DayCompleteParams,
) -> tuple[bool, dict[str, object]]:
    n = len(times_utc)
    gap = _max_gap_minutes(times_utc)
    quart_ok = _quartile_coverage(times_local)
    ok = (
        n >= params.min_obs
        and gap <= params.max_gap_minutes
        and quart_ok
    )
    return ok, {"n_obs": n, "max_gap_min": gap, "quartile_ok": quart_ok}


def build_tmax_labels(
    obs: pl.DataFrame,
    *,
    tz_name: str,
    cp_set_utc: Iterable[str],
    day_complete_params: DayCompleteParams | None = None,
) -> pl.DataFrame:
    """Aggregate observations into per-day labels.

    ``obs`` must contain at minimum: ``ts_utc`` (UTC tz-aware), ``tmp_c_int``,
    ``dq_tmp_c_int``. Rows with ``dq_tmp_c_int == 'missing'`` are excluded from
    label aggregation but contribute to ``n_obs_total``.
    """
    if "ts_utc" not in obs.columns or "tmp_c_int" not in obs.columns:
        raise ValueError("obs must contain ts_utc and tmp_c_int.")
    params = day_complete_params or DayCompleteParams()
    cps = list(cp_set_utc)

    # Convert ts_utc to local once and add tmp_c_dec (from tmpf F->C if missing)
    if "tmp_c_dec" in obs.columns:
        df = obs
    else:
        if "tmpf" in obs.columns:
            df = obs.with_columns(
                ((pl.col("tmpf") - 32.0) * 5.0 / 9.0).alias("tmp_c_dec")
            )
        else:
            df = obs.with_columns(pl.lit(None, dtype=pl.Float64).alias("tmp_c_dec"))
    df = df.with_columns(
        pl.col("ts_utc").dt.convert_time_zone(tz_name).alias("ts_local"),
    ).with_columns(
        pl.col("ts_local").dt.date().alias("date_local"),
    )

    # ts_local can land on the previous/next local date relative to UTC; group on date_local.
    grouped = df.group_by("date_local", maintain_order=True).agg(
        [
            pl.col("ts_utc").alias("ts_list_utc"),
            pl.col("ts_local").alias("ts_list_local"),
            pl.col("tmp_c_int").alias("tmp_list"),
            pl.col("tmp_c_dec").alias("tmp_dec_list"),
            pl.col("dq_tmp_c_int").alias("dq_list"),
        ]
    )

    out_rows: list[dict[str, object]] = []
    grouped_dicts = grouped.to_dicts()
    for row in grouped_dicts:
        d_local: date = row["date_local"]
        ts_utc_list: list[datetime] = list(row["ts_list_utc"])
        ts_local_list: list[datetime] = list(row["ts_list_local"])
        tmp_list = list(row["tmp_list"])
        tmp_dec_list = list(row["tmp_dec_list"])
        dq_list = list(row["dq_list"])

        # Filter out 'missing' for label computation
        valid = [
            (tu, tl, t, td)
            for tu, tl, t, td, dq in zip(
                ts_utc_list, ts_local_list, tmp_list, tmp_dec_list, dq_list, strict=True
            )
            if t is not None and dq != "missing"
        ]
        n_total = len(ts_utc_list)
        if not valid:
            base = {
                "date_local": d_local,
                "tmax_int": None,
                "tmin_int": None,
                "tmax_ts_utc": None,
                "tmax_ts_local": None,
                "n_obs_total": n_total,
                "n_obs_valid": 0,
                "day_complete": False,
                "max_gap_min": _max_gap_minutes(ts_utc_list),
                "quartile_ok": _quartile_coverage(ts_local_list),
            }
            for cp in cps:
                base[_l1_col(cp)] = None
            out_rows.append(base)
            continue
        valid.sort(key=lambda r: r[0])
        # tmax_int from integer; tmax_ts from decimal (representative of true peak when ties)
        tmax_int = max(r[2] for r in valid)
        tmin_int = min(r[2] for r in valid)
        # Pick the timestamp where decimal tmpf is highest among rows tied at tmax_int
        tied = [r for r in valid if r[2] == tmax_int]
        if any(r[3] is not None for r in tied):
            ranked = sorted(
                [r for r in tied if r[3] is not None],
                key=lambda r: r[3],
                reverse=True,
            )
            tmax_idx_row = ranked[0]
        else:
            tmax_idx_row = tied[0]
        tmax_ts_utc = tmax_idx_row[0]
        tmax_ts_local = tmax_idx_row[1]

        ok, info = _is_day_complete(ts_utc_list, ts_local_list, params)

        row_out: dict[str, object] = {
            "date_local": d_local,
            "tmax_int": int(tmax_int),
            "tmin_int": int(tmin_int),
            "tmax_ts_utc": tmax_ts_utc,
            "tmax_ts_local": tmax_ts_local,
            "n_obs_total": n_total,
            "n_obs_valid": len(valid),
            "day_complete": bool(ok),
            "max_gap_min": int(info["max_gap_min"]),
            "quartile_ok": bool(info["quartile_ok"]),
        }
        # Per-CP late spike L1
        for cp in cps:
            cp_utc = cp_to_utc(d_local, cp)
            k_cp_pool = [t for tu, _tl, t, _td in valid if tu < cp_utc]
            if not k_cp_pool:
                row_out[_l1_col(cp)] = None
                continue
            k_cp = max(k_cp_pool)
            k_eod = tmax_int
            row_out[_l1_col(cp)] = bool(k_eod != k_cp)
        out_rows.append(row_out)

    schema = _label_schema(cps, tz_name=tz_name)
    return pl.DataFrame(out_rows, schema=schema)


def _l1_col(cp: str) -> str:
    """Column name ``late_spike_l1__cp_HH``."""
    return f"late_spike_l1__cp_{cp[:2]}"


def _label_schema(cps: list[str], tz_name: str = "Pacific/Auckland") -> dict[str, pl.DataType]:
    schema: dict[str, pl.DataType] = {
        "date_local": pl.Date,
        "tmax_int": pl.Int32,
        "tmin_int": pl.Int32,
        "tmax_ts_utc": pl.Datetime("us", time_zone="UTC"),
        "tmax_ts_local": pl.Datetime("us", time_zone=tz_name),
        "n_obs_total": pl.Int32,
        "n_obs_valid": pl.Int32,
        "day_complete": pl.Boolean,
        "max_gap_min": pl.Int32,
        "quartile_ok": pl.Boolean,
    }
    for cp in cps:
        schema[_l1_col(cp)] = pl.Boolean
    return schema


def k_cp(obs_for_day: pl.DataFrame, cp_utc: datetime) -> int | None:
    """Compute ``k_cp = max(tmp_c_int for ts_utc < cp_utc)`` over the day's observations."""
    if obs_for_day.height == 0:
        return None
    sub = obs_for_day.filter(
        (pl.col("ts_utc") < cp_utc) & (pl.col("dq_tmp_c_int") != "missing")
    ).select("tmp_c_int").drop_nulls()
    if sub.height == 0:
        return None
    return int(sub["tmp_c_int"].max())


__all__ = [
    "DayCompleteParams",
    "build_tmax_labels",
    "k_cp",
]
