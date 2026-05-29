"""Training panel for Phase 3 Ridge.

Wraps ``build_cp_features`` to emit a feature matrix with the columns the Ridge
model consumes plus the integer label target and the decimal delta target.

Causality is enforced upstream by ``build_cp_features`` (REQ-CON-5, REQ-AUD-4).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Iterable

import polars as pl

from core.baselines.climatology import Climatology
from core.features.builder import build_cp_features


# Feature columns emitted (locked v0.1.1 for Phase 3).
FEATURE_COLUMNS = (
    "k_cp",
    "clim_tmax_c_dec",
    "slope_3h_c_per_h",
    "slope_6h_c_per_h",
    "last_obs_tmp_c_int",
    "tmax_d_minus_1_int",
    "tmin_d_minus_1_int",
    "wind_dir_sin",
    "wind_dir_cos",
    "wind_speed_kt",
    "qnh_hpa",
    "month_sin",
    "month_cos",
)

# Subset used by the "no-temperature" ablation (REQ-AUD-2 secao 18 v1).
# Removes anchors that essentially carry T directly.
NO_TEMPERATURE_FEATURES = (
    "slope_3h_c_per_h",
    "slope_6h_c_per_h",
    "wind_dir_sin",
    "wind_dir_cos",
    "wind_speed_kt",
    "qnh_hpa",
    "month_sin",
    "month_cos",
)


def build_training_panel(
    observations: pl.DataFrame,
    labels: pl.DataFrame,
    *,
    climo: Climatology,
    tz_name: str,
    cp_set: Iterable[str],
    dates: Iterable[date] | None = None,
    drop_incomplete: bool = True,
) -> pl.DataFrame:
    """Build the (date_local, cp) training panel with features + target.

    Returns a DataFrame with one row per ``(date_local, cp)`` pair where:
    - ``target_tmax_int`` = integer label (truth, from ``labels``)
    - ``target_delta`` = ``target_tmax_int - clim_tmax_c_dec`` (Ridge target)
    - all of ``FEATURE_COLUMNS``
    - bookkeeping: ``date_local``, ``cp``, ``cp_utc``, ``feature_max_ts_utc``, ``day_complete``
    """
    cp_set = list(cp_set)
    if dates is None:
        dates = labels["date_local"].drop_nulls().unique().to_list()

    label_map: dict[date, dict[str, object]] = {}
    if labels.height:
        for row in labels.select(["date_local", "tmax_int", "day_complete"]).iter_rows(named=True):
            d = row["date_local"]
            if d is not None:
                label_map[d] = row

    rows: list[dict[str, object]] = []
    for d in dates:
        if d is None:
            continue
        lab = label_map.get(d)
        tmax_int = lab["tmax_int"] if lab is not None else None
        day_complete = bool(lab["day_complete"]) if lab is not None else False
        if drop_incomplete and (not day_complete or tmax_int is None):
            continue
        clim_dec = float(climo.tmax_dec_for(d))
        m_sin = math.sin(2 * math.pi * d.month / 12.0)
        m_cos = math.cos(2 * math.pi * d.month / 12.0)
        for cp in cp_set:
            # build_cp_features raises RuntimeError on causality violations
            # (REQ-CON-5); we let it propagate (review-v2 #N5: removed dead
            # try/except that was a literal no-op).
            f = build_cp_features(
                observations, date_local=d, cp_hhmm=cp, tz_name=tz_name, labels=labels
            )
            wind_dir = f.features.get("wind_dir_deg")
            ws = f.features.get("wind_speed_kt")
            if wind_dir is None or ws is None:
                wd_sin = wd_cos = None
            else:
                rad = math.radians(float(wind_dir))
                wd_sin = math.sin(rad)
                wd_cos = math.cos(rad)
            row_out: dict[str, object] = {
                "date_local": d,
                "cp": cp,
                "cp_utc": f.cp_utc,
                "feature_max_ts_utc": f.feature_max_ts_utc,
                "day_complete": day_complete,
                # target
                "target_tmax_int": int(tmax_int) if tmax_int is not None else None,
                "target_delta": (
                    float(tmax_int) - clim_dec if tmax_int is not None else None
                ),
                # features
                "k_cp": f.features.get("k_cp"),
                "clim_tmax_c_dec": clim_dec,
                "slope_3h_c_per_h": f.features.get("slope_3h_c_per_h"),
                "slope_6h_c_per_h": f.features.get("slope_6h_c_per_h"),
                "last_obs_tmp_c_int": f.features.get("last_obs_tmp_c_int"),
                "tmax_d_minus_1_int": f.features.get("tmax_d_minus_1_int"),
                "tmin_d_minus_1_int": f.features.get("tmin_d_minus_1_int"),
                "wind_dir_sin": wd_sin,
                "wind_dir_cos": wd_cos,
                "wind_speed_kt": ws,
                "qnh_hpa": f.features.get("qnh_hpa"),
                "month_sin": m_sin,
                "month_cos": m_cos,
            }
            rows.append(row_out)
    return pl.DataFrame(rows)


__all__ = ["FEATURE_COLUMNS", "NO_TEMPERATURE_FEATURES", "build_training_panel"]
