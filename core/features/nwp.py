"""NWP features (T-4-3, design 4.5.2 + section 19).

For each ``(date_local, cp_utc)`` we compute:
- ``nwp_t2m_at_cp_c``: ensemble mean of ``t2m_c`` at ``valid_time=cp_utc``
- ``nwp_t2m_at_cp_spread_c``: numpy std across the v1 ensemble (>=2 models)
- ``nwp_disagreement_score``: range / k (a normalised spread proxy)
- ``nwp_t2m_at_cp_minus_obs_c``: NWP@cp minus the last observed integer at CP
  (regime-shift proxy; positive => NWP thinks it is warmer than the station)
- **Trajectory features** (Phase 4.1, captured from the same causal pre-CP run
  at multiple leads to give the residual model a "warming pace" signal):
  - ``nwp_t2m_max_pre_cp_c``: ensemble-mean max of t2m over [cp - 5h, cp]
  - ``nwp_t2m_slope_pre_cp_c_per_h``: ensemble-mean OLS slope over [cp - 5h, cp]
  - ``nwp_t2m_range_pre_cp_c``: max - min (warming amplitude in last 5h)
- per-model raw values to allow ablations.

Strict CP causality is enforced upstream by ``select_nwp_ensemble``
(``run_time_utc <= cp_utc - safety_margin``). Trajectory features only consume
rows from the SAME causal run so they cannot leak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

import numpy as np
import polars as pl

from core.ingest.nwp import (
    NwpSelection,
    SAFETY_MARGIN_DEFAULT,
    select_nwp_ensemble,
    select_nwp_v1,
)


@dataclass(frozen=True)
class NwpFeatures:
    nwp_t2m_at_cp_c: float | None
    nwp_t2m_at_cp_spread_c: float | None
    nwp_disagreement_score: float | None
    nwp_t2m_at_cp_minus_obs_c: float | None
    nwp_t2m_max_pre_cp_c: float | None
    nwp_t2m_slope_pre_cp_c_per_h: float | None
    nwp_t2m_range_pre_cp_c: float | None
    nwp_run_time_utc: datetime | None
    nwp_lead_h: int | None
    per_model: dict[str, float | None]


@dataclass(frozen=True)
class MaxTrajAnchor:
    """Result of the max-of-trajectory anchor (design 4.5.2.1 / NWP_SOURCE_VERSION 1.1).

    ``anchor_c`` is the ensemble mean of each model's windowed max; ``spread_c`` is
    the ensemble std of those per-model maxima (same causal source feeds both -
    D6). ``per_model_max`` records each model's max; ``run_time_utc`` is the latest
    selected causal run actually used (for the leakage gate). ``valid_time_utc`` /
    ``lead_h`` are the representative valid timestamp that produced the max anchor;
    for single-model serving this is the exact row used by the residual arm.
    """

    nwp_t2m_maxtraj_c: float | None
    nwp_t2m_maxtraj_spread_c: float | None
    per_model_max: dict[str, float | None]
    run_time_utc: datetime | None
    valid_time_utc: datetime | None
    lead_h: int | None
    n_models: int
    n_valid_steps: int


def select_max_trajectory_anchor(
    snapshots: pl.DataFrame,
    *,
    cp_utc: datetime,
    window_start_utc: datetime,
    window_end_utc: datetime,
    models: Iterable[str],
    safety_margin: timedelta = SAFETY_MARGIN_DEFAULT,
) -> MaxTrajAnchor:
    """Causal max-of-trajectory anchor over a forward valid-time window (design 4.5.2.1).

    For each model: pick the latest causal run (``run_time_utc <= cp_utc -
    safety_margin``) via ``select_nwp_v1``, then take ``max(t2m_c)`` over rows of
    THAT SAME run whose ``valid_time_utc`` falls in ``[window_start_utc,
    window_end_utc]``. Ensemble-mean the per-model maxima; spread = std.

    CAUSAL BY CONSTRUCTION: the window only ever reads valids from the single
    causal ``selected_run``, so a forward window (toward the afternoon Tmax)
    cannot pull a fresher, non-causal run the way an HFAPI stitched series would.
    On HFAPI data this means the window is effectively capped at the run's
    available leads; long forward leads require Single Runs snapshots (T-OPN-5a).

    Raises ``RuntimeError`` (via ``select_nwp_v1``) if a selected row violates the
    causality cutoff - the leakage gate's runtime twin.
    """
    if cp_utc.tzinfo is None or window_start_utc.tzinfo is None or window_end_utc.tzinfo is None:
        raise ValueError("cp_utc and window bounds must be tz-aware UTC")
    if window_end_utc < window_start_utc:
        raise ValueError("window_end_utc must be >= window_start_utc")

    per_model_max: dict[str, float | None] = {}
    maxima: list[float] = []
    runs: list[datetime] = []
    anchor_trace: list[tuple[datetime, int]] = []
    total_steps = 0
    for m in models:
        sub_m = snapshots.filter(pl.col("model") == m)
        # Anchor the run choice on the window's far edge (closest to the peak we
        # want), but causality is enforced against cp_utc inside select_nwp_v1.
        sel = select_nwp_v1(
            sub_m, cp_utc=cp_utc, target_valid_utc=window_end_utc,
            safety_margin=safety_margin,
        )
        if sel is None:
            per_model_max[m] = None
            continue
        run_rows = sub_m.filter(
            (pl.col("run_time_utc") == sel.run_time_utc)
            & (pl.col("valid_time_utc") >= window_start_utc)
            & (pl.col("valid_time_utc") <= window_end_utc)
            & pl.col("t2m_c").is_not_null()
        )
        if run_rows.height == 0:
            per_model_max[m] = None
            continue
        m_max = float(run_rows["t2m_c"].max())
        max_row = (
            run_rows
            .filter(pl.col("t2m_c") == m_max)
            .sort("valid_time_utc")
            .row(0, named=True)
        )
        per_model_max[m] = m_max
        maxima.append(m_max)
        runs.append(sel.run_time_utc)
        anchor_trace.append((max_row["valid_time_utc"], int(max_row["lead_h"])))
        total_steps += run_rows.height

    if not maxima:
        return MaxTrajAnchor(
            nwp_t2m_maxtraj_c=None, nwp_t2m_maxtraj_spread_c=None,
            per_model_max=per_model_max, run_time_utc=None,
            valid_time_utc=None, lead_h=None,
            n_models=0, n_valid_steps=0,
        )
    arr = np.asarray(maxima, dtype=float)
    anchor_valid, anchor_lead = max(anchor_trace, key=lambda t: t[0])
    return MaxTrajAnchor(
        nwp_t2m_maxtraj_c=float(arr.mean()),
        nwp_t2m_maxtraj_spread_c=float(arr.std()) if arr.size > 1 else 0.0,
        per_model_max=per_model_max,
        run_time_utc=max(runs),
        valid_time_utc=anchor_valid,
        lead_h=anchor_lead,
        n_models=int(arr.size),
        n_valid_steps=int(total_steps),
    )


def _slope_per_hour(times_h: list[float], values: list[float]) -> float | None:
    """OLS slope per hour over (t, v) pairs. Returns None if < 2 points."""
    if len(times_h) < 2:
        return None
    n = len(times_h)
    mx = sum(times_h) / n
    my = sum(values) / n
    num = sum((t - mx) * (v - my) for t, v in zip(times_h, values, strict=True))
    den = sum((t - mx) ** 2 for t in times_h)
    if den == 0:
        return None
    return num / den


def compute_nwp_features(
    snapshots: pl.DataFrame,
    *,
    cp_utc: datetime,
    target_valid_utc: datetime,
    models: Iterable[str],
    last_obs_tmp_c: float | None = None,
    safety_margin: timedelta = SAFETY_MARGIN_DEFAULT,
    pre_cp_window_h: int = 5,
) -> NwpFeatures:
    """Compute NWP ensemble features at ``target_valid_utc``.

    For Phase 4 v1, callers should set ``target_valid_utc == cp_utc`` to stay
    fully causal under HFAPI (see design 19.1 + open-meteo cross-check note).

    Trajectory features (max/slope/range over [cp - pre_cp_window_h, cp]) are
    computed from the SAME causal run that supplied the cp value (selected
    above), so they inherit the same ``run_time_utc <= cp - safety_margin``
    guarantee.
    """
    sel = select_nwp_ensemble(
        snapshots, cp_utc=cp_utc, target_valid_utc=target_valid_utc,
        models=list(models), safety_margin=safety_margin,
    )
    per_model: dict[str, float | None] = {}
    t2m_values: list[float] = []
    runs: list[datetime] = []
    leads: list[int] = []
    selected_runs_by_model: dict[str, datetime] = {}
    for m, s in sel.items():
        if s is None or s.t2m_c is None:
            per_model[m] = None
            continue
        per_model[m] = s.t2m_c
        t2m_values.append(s.t2m_c)
        runs.append(s.run_time_utc)
        leads.append(s.lead_h)
        selected_runs_by_model[m] = s.run_time_utc

    if not t2m_values:
        return NwpFeatures(
            nwp_t2m_at_cp_c=None, nwp_t2m_at_cp_spread_c=None,
            nwp_disagreement_score=None, nwp_t2m_at_cp_minus_obs_c=None,
            nwp_t2m_max_pre_cp_c=None, nwp_t2m_slope_pre_cp_c_per_h=None,
            nwp_t2m_range_pre_cp_c=None,
            nwp_run_time_utc=None, nwp_lead_h=None, per_model=per_model,
        )

    n = len(t2m_values)
    mean = sum(t2m_values) / n
    if n == 1:
        spread = 0.0
        disagreement = 0.0
    else:
        var = sum((v - mean) ** 2 for v in t2m_values) / n
        spread = math.sqrt(var)
        disagreement = (max(t2m_values) - min(t2m_values)) / max(abs(mean), 1.0)

    delta_vs_obs = (mean - float(last_obs_tmp_c)) if last_obs_tmp_c is not None else None

    # Trajectory features: pull rows from each model's selected_run, valid_time in
    # [cp - pre_cp_window_h, cp]. Strict causality preserved by reusing the run.
    window_start = cp_utc - timedelta(hours=pre_cp_window_h)
    traj_means_per_hour: dict[datetime, list[float]] = {}
    for m, run in selected_runs_by_model.items():
        sub = snapshots.filter(
            (pl.col("model") == m)
            & (pl.col("run_time_utc") == run)
            & (pl.col("valid_time_utc") >= window_start)
            & (pl.col("valid_time_utc") <= cp_utc)
            & pl.col("t2m_c").is_not_null()
        )
        for row in sub.iter_rows(named=True):
            t = row["valid_time_utc"]
            v = row["t2m_c"]
            traj_means_per_hour.setdefault(t, []).append(float(v))

    traj_max = traj_slope = traj_range = None
    if traj_means_per_hour:
        sorted_times = sorted(traj_means_per_hour.keys())
        traj_mean_curve = [sum(traj_means_per_hour[t]) / len(traj_means_per_hour[t])
                            for t in sorted_times]
        if len(traj_mean_curve) >= 2:
            traj_max = max(traj_mean_curve)
            traj_range = max(traj_mean_curve) - min(traj_mean_curve)
            t_zero = sorted_times[0]
            times_h = [(t - t_zero).total_seconds() / 3600 for t in sorted_times]
            traj_slope = _slope_per_hour(times_h, traj_mean_curve)
        else:
            traj_max = traj_mean_curve[0]
            traj_range = 0.0
            traj_slope = 0.0

    return NwpFeatures(
        nwp_t2m_at_cp_c=float(mean),
        nwp_t2m_at_cp_spread_c=float(spread),
        nwp_disagreement_score=float(disagreement),
        nwp_t2m_at_cp_minus_obs_c=delta_vs_obs,
        nwp_t2m_max_pre_cp_c=None if traj_max is None else float(traj_max),
        nwp_t2m_slope_pre_cp_c_per_h=None if traj_slope is None else float(traj_slope),
        nwp_t2m_range_pre_cp_c=None if traj_range is None else float(traj_range),
        nwp_run_time_utc=max(runs),
        nwp_lead_h=int(leads[-1]),
        per_model=per_model,
    )


__all__ = [
    "NwpFeatures",
    "MaxTrajAnchor",
    "compute_nwp_features",
    "select_max_trajectory_anchor",
]
