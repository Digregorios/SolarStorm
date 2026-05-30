"""Phase 5 workstream A: the prediction-panel "data spine" (design 8.2, REQ-MOD-4).

This module turns a Phase-4 walk-forward run (a fitted residual LightGBM applied
to already-built Phase-4 feature rows) into the RAW Phase-5 panel rows defined by
``core.contracts.phase5.RAW_PANEL_COLUMNS`` / ``RAW_PANEL_SCHEMA``. It is Layer 1
of the panel: everything derivable from the model BEFORE conformal calibration.
The integrator adds Layer 2 (``ic80_low_int`` / ``ic80_high_int``) downstream.

Two entry points:

  ``build_phase5_rows``    pure, deterministic, no I/O - the unit-tested core. Given
                           a polars frame of Phase-4 feature rows plus a fitted LGBM
                           and its NWP anchor array, it emits one panel row per input
                           row, schema-exact, plus the row-aligned ``prob_dist`` list.

  ``build_phase5_panel``   higher-level orchestrator that mirrors the Phase-4
                           expanding walk-forward (``scripts.phase4_evaluate``): per
                           split it fits the residual LGBM on the train window, then
                           emits role=calib rows from a held-out CALIBRATION slice and
                           role=test rows from the test window. It needs real data
                           (``NZWN.csv`` + NWP snapshots) so it is guarded against the
                           unit test and is not exercised without those inputs.

The ``prob_dist`` (dict[int,float]) cannot live in a polars column, so the builder
returns a tuple ``(panel: pl.DataFrame, prob_dists: list[dict[int,float]])`` aligned
row-for-row, per the shared contract (``PROB_DIST_SIDE_KEY``).

CAUSALITY of ``p50_var``: for each row it is the variance of ``y_pred_dec`` over the
EARLIER CPs of the SAME ``date_local`` only - CPs whose ``cp_utc`` is strictly before
the current row's ``cp_utc``. It is NULL for the first CP of a day (no earlier CP to
vary against). Later CPs of the same day are NEVER used; doing so would leak a future
forecast into a feature the confidence model consumes.

Determinism: seed 42 everywhere; no unseeded RNG on any production path.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl

from core.baselines.support import support_K
from core.contracts.phase5 import (
    RAW_PANEL_COLUMNS,
    RAW_PANEL_SCHEMA,
    ROLE_CALIB,
    ROLE_TEST,
    ROLES,
)
from core.contracts.quantization import Q
from core.models.loss import latent_to_prob_dist
from core.models.residual_lgbm import predict_latent

# Phase-4 feature-row columns this builder reads. Kept as a contract so a missing
# column fails loudly here instead of producing a silently wrong panel.
REQUIRED_PANEL_COLUMNS: tuple[str, ...] = (
    "date_local",
    "cp",
    "cp_utc",
    "nwp_run_time_utc",
    "target_tmax_int",
    "nwp_t2m_maxtraj_c",
    "nwp_t2m_maxtraj_spread_c",
)

SEED = 42


def _causal_p50_var(
    date_local: list,
    cp_utc: list,
    y_pred_dec: np.ndarray,
) -> list[float | None]:
    """Var(``y_pred_dec``) over EARLIER CPs of the same ``date_local`` (causal).

    "Earlier" = strictly smaller ``cp_utc`` within the same local date. The first CP
    of a day has no earlier CP -> NULL. Ties on ``cp_utc`` (should not happen for a
    well-formed CP set) are treated as NOT earlier, so a duplicate CP cannot leak its
    own value into the statistic. Variance is the population variance (ddof=0) and is
    NULL (not 0.0) for a single earlier CP, since one point has no spread - keeping the
    "needs >= 2 earlier CPs" semantics explicit for the downstream confidence model.
    """
    n = len(date_local)
    out: list[float | None] = [None] * n
    # Group row indices by local date, preserving input order.
    by_day: dict[date, list[int]] = {}
    for i, d in enumerate(date_local):
        by_day.setdefault(d, []).append(i)
    for _, idxs in by_day.items():
        for i in idxs:
            t_i = cp_utc[i]
            earlier = [j for j in idxs if cp_utc[j] < t_i]
            if len(earlier) >= 2:
                vals = np.asarray([y_pred_dec[j] for j in earlier], dtype=float)
                out[i] = float(np.var(vals))
            else:
                out[i] = None
    return out


def build_phase5_rows(
    panel: pl.DataFrame,
    *,
    role: str,
    split_name: str,
    lgbm,
    nwp_anchor: np.ndarray,
    tau: float,
    mode: str,
    support_by_date,
    predict_fn=predict_latent,
) -> tuple[pl.DataFrame, list[dict[int, float]]]:
    """Build RAW Phase-5 rows from a Phase-4 feature frame + fitted model (pure).

    Parameters
    ----------
    panel:
        Polars frame of already-built Phase-4 feature rows. MUST contain
        ``REQUIRED_PANEL_COLUMNS`` plus the LGBM's own ``feature_columns`` (so the
        feature matrix ``X`` can be assembled in the model's column order). Rows are
        emitted one-for-one in the frame's existing order.
    role:
        ``ROLE_CALIB`` or ``ROLE_TEST`` (from the contract).
    split_name:
        Walk-forward split label written to the ``split`` column.
    lgbm:
        Fitted ``FittedResidualLgbm`` (or any object accepted by ``predict_fn``). Its
        ``feature_columns`` attribute selects the X columns when present; otherwise the
        caller-supplied order is taken from ``lgbm.feature_columns`` and must exist.
    nwp_anchor:
        Per-row NWP anchor array (``nwp_t2m_maxtraj_c``) passed to ``predict_fn``;
        length must equal ``panel.height``.
    tau, mode:
        Band-aware softmax temperature / mode for ``latent_to_prob_dist``.
    support_by_date:
        Mapping ``date -> list[int]`` giving the integer support K for that day's
        ``prob_dist`` (typically built from the causal climatology percentiles via
        ``support_K``). A missing date is an error - the support must be precomputed
        causally upstream, never inferred here from the prediction.
    predict_fn:
        Injection point for testing; defaults to the real ``predict_latent``.

    Returns
    -------
    (panel_out, prob_dists):
        ``panel_out`` columns == ``RAW_PANEL_COLUMNS`` with dtypes == ``RAW_PANEL_SCHEMA``;
        ``prob_dists`` is a python list of dict[int,float] aligned row-for-row.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}; got {role!r}")
    missing = [c for c in REQUIRED_PANEL_COLUMNS if c not in panel.columns]
    if missing:
        raise ValueError(f"panel is missing required columns: {missing}")

    feature_columns = tuple(getattr(lgbm, "feature_columns"))
    missing_feat = [c for c in feature_columns if c not in panel.columns]
    if missing_feat:
        raise ValueError(f"panel is missing model feature columns: {missing_feat}")

    n = panel.height
    anchor = np.asarray(nwp_anchor, dtype=float)
    if anchor.shape[0] != n:
        raise ValueError(
            f"nwp_anchor length {anchor.shape[0]} != panel height {n}"
        )

    if n == 0:
        empty = pl.DataFrame(schema=dict(RAW_PANEL_SCHEMA))
        return empty.select(list(RAW_PANEL_COLUMNS)), []

    # Assemble X in the model's feature-column order, then latent point forecast.
    X = np.column_stack(
        [panel[c].to_numpy().astype(float) for c in feature_columns]
    )
    y_pred_dec = np.asarray(predict_fn(lgbm, X, anchor), dtype=float)

    date_local = panel["date_local"].to_list()
    cp_utc = panel["cp_utc"].to_list()
    y_true = panel["target_tmax_int"].to_numpy()

    # prob_dist + bracket_correct per row.
    prob_dists: list[dict[int, float]] = []
    bracket_correct: list[int] = []
    y_true_int: list[int] = []
    for i in range(n):
        d = date_local[i]
        if d not in support_by_date:
            raise KeyError(f"support_by_date has no entry for date {d!r}")
        sk = list(support_by_date[d])
        pd_i = latent_to_prob_dist(float(y_pred_dec[i]), sk, tau=tau, mode=mode)
        prob_dists.append(pd_i)
        yt = int(y_true[i])
        y_true_int.append(yt)
        bracket_correct.append(int(Q(float(y_pred_dec[i])) == yt))

    p50_var = _causal_p50_var(date_local, cp_utc, y_pred_dec)
    months = [int(d.month) for d in date_local]
    spread = panel["nwp_t2m_maxtraj_spread_c"].to_list()

    out = pl.DataFrame(
        {
            "split": pl.Series([split_name] * n, dtype=pl.Utf8),
            "role": pl.Series([role] * n, dtype=pl.Utf8),
            "date_local": panel["date_local"].cast(pl.Date),
            "cp": panel["cp"].cast(pl.Utf8),
            "cp_utc": panel["cp_utc"].cast(pl.Datetime("us", time_zone="UTC")),
            "nwp_run_time_utc": panel["nwp_run_time_utc"].cast(
                pl.Datetime("us", time_zone="UTC")
            ),
            "month": pl.Series(months, dtype=pl.Int32),
            # regime is ALWAYS null in Phase 5 (regime GMM is Phase 7).
            "regime": pl.Series([None] * n, dtype=pl.Int32),
            "y_true_int": pl.Series(y_true_int, dtype=pl.Int32),
            "y_pred_dec": pl.Series([float(v) for v in y_pred_dec], dtype=pl.Float64),
            "nwp_spread": pl.Series(
                [None if v is None else float(v) for v in spread], dtype=pl.Float64
            ),
            "p50_var": pl.Series(p50_var, dtype=pl.Float64),
            "bracket_correct": pl.Series(bracket_correct, dtype=pl.Int32),
        }
    )
    out = out.select(list(RAW_PANEL_COLUMNS))
    # Enforce the contract schema exactly (order + dtype) so drift fails loudly.
    if out.schema != RAW_PANEL_SCHEMA:
        raise AssertionError(
            f"panel schema {dict(out.schema)} != contract {dict(RAW_PANEL_SCHEMA)}"
        )
    return out, prob_dists


def _support_by_date_from_climo(
    dates,
    climo,
    *,
    tmp_min: int,
    tmp_max: int,
) -> dict:
    """Build ``support_by_date`` from a causal climatology (one K-list per unique date).

    Mirrors the Phase-4 ``_evaluate_split`` support construction: per date the climo
    p10/p90 feed ``support_K`` with the plausibility bounds. The climatology MUST be
    the per-split train-only (causal) one - never a test-spanning fit.
    """
    out: dict = {}
    for d in dict.fromkeys(dates):  # unique, order-preserving
        p10, p90 = climo.percentiles_for(d)
        out[d] = support_K(p10, p90, tmp_min=tmp_min, tmp_max=tmp_max)
    return out


def build_phase5_panel(
    *,
    nzwn_csv=None,
    nwp_root=None,
    config_dir=None,
    _allow_real_data: bool = False,
) -> tuple[pl.DataFrame, list[dict[int, float]]]:
    """Orchestrate the full walk-forward Phase-5 panel (REAL data; guarded).

    Mirrors ``scripts.phase4_evaluate``: build the Phase-4 panel + causal per-split
    climatology, then for each expanding walk-forward split:

      1. Fit the residual LGBM on the split's TRAIN window (NWP-anchored rows).
      2. Emit ``role=calib`` rows from the CALIBRATION slice (see rule below).
      3. Emit ``role=test`` rows from the split's TEST window.

    CALIBRATION-SLICE RULE
    ----------------------
    The calibration slice is the LAST ``conformal.seasonal_window_months`` (= 12, from
    ``nzwn/config/model.yaml``) months of each split's TRAIN window:

        calib_window = [train_end - (seasonal_days - 1) days, train_end]

    The slice is emitted at the WIDER seasonal span so the integrator can build BOTH
    Phase-5 conformal calibrators from the same panel without a second walk-forward run:
    the per-CP calibrator subsets the recent ``conformal.per_cp_window_days`` (= 90)
    days, and the seasonal cross-check calibrator uses the full 12-month slice. It is
    (a) strictly causal - entirely inside the train window, never touching test - and
    (b) disjoint from the test window. The LGBM is still fit on the FULL train window
    (including the calib slice); only the residual set is the held-out tail. This is the
    standard split-conformal arrangement adapted to the expanding walk-forward.

    This path is SLOW and needs real inputs, so it refuses to run unless
    ``_allow_real_data=True``. The unit test exercises ``build_phase5_rows`` directly
    and never reaches here.
    """
    if not _allow_real_data:
        raise RuntimeError(
            "build_phase5_panel touches real data (NZWN.csv + NWP snapshots) and is "
            "guarded: pass _allow_real_data=True to run the full walk-forward. The "
            "unit test exercises build_phase5_rows directly instead."
        )

    # Imports are deferred so the unit test never pays for them and the guarded path
    # is the only place the heavy Phase-4 harness is pulled in.
    from datetime import date as _date
    from pathlib import Path

    import yaml

    from core.baselines.climatology import (
        fit_climatology,
        fit_tmax_hour_climatology,
    )
    from core.contracts.station import load_station_config
    from core.eval.cv import expanding_walk_forward_splits
    from core.features.training_panel import build_training_panel
    from core.ingest.iem_csv import load_observations
    from core.ingest.nwp import read_snapshots
    from core.ingest.nwp_client import NCEP_GFS
    from core.labels.tmax import build_tmax_labels
    from core.models.residual_lgbm import ResidualLgbmConfig, fit_residual_lgbm
    from scripts.phase4_evaluate import (
        PHASE4_FEATURES,
        _arrays,
        _rebuild_climo_features,
        assert_causal_climo,
    )

    repo = Path(__file__).resolve().parents[1]
    nzwn_csv = Path(nzwn_csv) if nzwn_csv is not None else repo / "NZWN.csv"
    nwp_root = Path(nwp_root) if nwp_root is not None else repo / "artifacts" / "raw" / "nwp"
    config_dir = Path(config_dir) if config_dir is not None else repo / "nzwn" / "config"

    cfg = load_station_config(config_dir / "station.yaml")
    with open(config_dir / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    tau = float(mcfg["prob_dist"]["tau"])
    mode = str(mcfg["prob_dist"]["mode"])
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])
    seasonal_window_months = int(mcfg["conformal"]["seasonal_window_months"])
    # Emit the calib slice at the WIDER seasonal span so the integrator can derive
    # both the per-CP (90d) and seasonal (12m) calibrators from one panel.
    calib_days = max(per_cp_window_days, round(seasonal_window_months * 30.4375))
    tmp_min = cfg.tmp_c_int_plausibility.min
    tmp_max = cfg.tmp_c_int_plausibility.max

    obs, _ = load_observations(nzwn_csv, tmp_min_c=tmp_min, tmp_max_c=tmp_max)
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    climo_broad = fit_climatology(
        labels, train_start=_date(2020, 1, 1), train_end=_date(2024, 12, 31)
    )
    nwp_snaps = read_snapshots(
        station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root
    )
    thc = fit_tmax_hour_climatology(
        labels, train_start=_date(2020, 1, 1), train_end=_date(2022, 12, 31), tz_name=cfg.tz
    )
    panel = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=cfg.tz, cp_set=cfg.cp_set_utc,
        nwp_snapshots=nwp_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc,
    )

    cfg_lgbm = ResidualLgbmConfig(
        feature_columns=PHASE4_FEATURES,
        n_estimators=500, learning_rate=0.05, num_leaves=31, min_data_in_leaf=20,
        tau=tau, mode=mode,
    )
    splits = expanding_walk_forward_splits(
        history_start=_date(2020, 1, 1),
        test_starts=[_date(2023, 1, 1), _date(2024, 1, 1), _date(2025, 1, 1)],
        test_length_days=365,
    )

    panels: list[pl.DataFrame] = []
    prob_dists: list[dict[int, float]] = []
    for s in splits:
        pooled = panel.filter(panel["cp"].is_in(cfg.cp_set_utc))
        train = pooled.filter(
            (pooled["date_local"] >= s.train_start) & (pooled["date_local"] <= s.train_end)
        )
        test = pooled.filter(
            (pooled["date_local"] >= s.test_start) & (pooled["date_local"] <= s.test_end)
        )
        train_ok = train.filter(train["nwp_t2m_maxtraj_c"].is_not_null())
        test_ok = test.filter(test["nwp_t2m_maxtraj_c"].is_not_null())

        # Causal per-split climatology (train-only) for support + climo feature.
        train_labels = (
            train.select(["date_local", "target_tmax_int"])
            .unique(subset=["date_local"])
            .rename({"target_tmax_int": "tmax_int"})
            .with_columns(pl.lit(True).alias("day_complete"))
        )
        climo = fit_climatology(
            train_labels, train_start=s.train_start, train_end=s.train_end
        )

        # Calibration slice = last per_cp_window_days of the train window (causal).
        from datetime import timedelta as _td

        calib_start = s.train_end - _td(days=calib_days - 1)
        calib_ok = train_ok.filter(train_ok["date_local"] >= calib_start)

        assert_causal_climo(climo, test_ok["date_local"].to_list())
        train_ok = _rebuild_climo_features(train_ok, climo)
        calib_ok = _rebuild_climo_features(calib_ok, climo)
        test_ok = _rebuild_climo_features(test_ok, climo)

        X_train, y_train = _arrays(train_ok, PHASE4_FEATURES)
        anchor_train = train_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
        lgbm = fit_residual_lgbm(X_train, y_train, anchor_train, config=cfg_lgbm)

        for role, frame in ((ROLE_CALIB, calib_ok), (ROLE_TEST, test_ok)):
            if frame.height == 0:
                continue
            anchor = frame["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
            support_by_date = _support_by_date_from_climo(
                frame["date_local"].to_list(), climo, tmp_min=tmp_min, tmp_max=tmp_max
            )
            sub_panel, sub_dists = build_phase5_rows(
                frame, role=role, split_name=s.name, lgbm=lgbm, nwp_anchor=anchor,
                tau=tau, mode=mode, support_by_date=support_by_date,
            )
            panels.append(sub_panel)
            prob_dists.extend(sub_dists)

    full = pl.concat(panels, how="vertical") if panels else pl.DataFrame(
        schema=dict(RAW_PANEL_SCHEMA)
    ).select(list(RAW_PANEL_COLUMNS))
    return full, prob_dists


__all__ = [
    "REQUIRED_PANEL_COLUMNS",
    "build_phase5_rows",
    "build_phase5_panel",
]
