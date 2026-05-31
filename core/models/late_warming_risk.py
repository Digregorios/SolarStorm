"""material_late_warming_risk_model_v0 (Etapa 5): causal pre-CP risk of k_eod - k_cp >= 2.

A late-warming REGIME DETECTOR, not a Tmax forecaster. Predicts ``P(material_late_warming |
features_pre_CP)`` at the operational CP, from the THREE precursors that survived the walk-forward
gate (Etapa 2) plus a season term:

  - delta_06_to_cp   : morning thermal momentum (T at last pre-CP obs - T at nearest <= 06 local)
  - southerly_at_cp  : modal wind quadrant == S over [cp_utc - 3h, cp_utc)  (TIMESTAMP-based, frozen)
  - rain_persistence_path : rain in ALL of {00-06, 06-09, 09-cp} local windows (p01i>0 or RA/SHRA)
  - month sin/cos    : seasonal calibration term

Frozen window definition (reviewer correction, update.txt): the CP window is timestamp-based
``[cp_utc - 3h, cp_utc)`` (not local-hour) to avoid DST / off-cadence ambiguity. Strict
causality: only obs with ``ts_utc < cp_utc`` are read. Deterministic (seed 42; lbfgs + PAVA).

Output is DIAGNOSTIC (prob + risk_bucket). It does NOT touch the center p50 or conformal here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

import numpy as np
import polars as pl
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from core.io.timeutil import cp_to_utc, day_local_window

FEATURE_NAMES = ("delta_06_to_cp", "southerly_at_cp", "rain_persistence_path", "month_sin", "month_cos")
RISK_MODEL_VERSION = "late-warming-risk-v0"
_CP_WINDOW_H = 3


def _quadrant(drct: float | None) -> str | None:
    if drct is None or (isinstance(drct, float) and math.isnan(drct)):
        return None
    d = float(drct) % 360.0
    if d >= 315 or d < 45:
        return "N"
    if d < 135:
        return "E"
    if d < 225:
        return "S"
    return "W"


def _is_rain(wx, p01) -> bool:
    if p01 is not None and not (isinstance(p01, float) and math.isnan(p01)) and float(p01) > 0:
        return True
    if wx:
        u = str(wx).upper()
        return any(t in u for t in ("RA", "SHRA", "DZ", "TS"))
    return False


@dataclass(frozen=True)
class LateWarmingRiskModel:
    logistic: LogisticRegression
    isotonic: IsotonicRegression | None
    feat_means: np.ndarray
    feat_stds: np.ndarray
    feats: tuple[str, ...] = FEATURE_NAMES


def build_features(obs: pl.DataFrame, labels: pl.DataFrame, tz: str, cp_hhmm: str) -> pl.DataFrame:
    """Per day_complete day: the 5 frozen pre-CP features + audit target (k_eod-k_cp>=2).

    All features use only obs with ts_utc in [day_start, cp_utc). The CP window for the wind
    quadrant is the timestamp band [cp_utc - 3h, cp_utc).
    """
    obs = obs.with_columns(pl.col("ts_utc").dt.convert_time_zone(tz).alias("ts_local"))
    lab = {r["date_local"]: r for r in labels.iter_rows(named=True) if r["day_complete"]}
    rows: list[dict] = []
    for d, lr in lab.items():
        if lr["tmax_int"] is None:
            continue
        cp_utc = cp_to_utc(d, cp_hhmm)
        day_start, _ = day_local_window(d, tz_name=tz)
        sub = obs.filter((pl.col("ts_utc") >= day_start) & (pl.col("ts_utc") < cp_utc)).sort("ts_utc")
        if sub.height < 6:
            continue
        ts = sub["ts_utc"].to_list()
        loc_h = sub["ts_local"].dt.hour().to_list()
        drct = sub["drct"].to_list()
        tmp_c = sub["tmp_c_int"].to_list()
        wx = sub["wxcodes"].to_list() if "wxcodes" in sub.columns else [None] * sub.height
        p01 = sub["p01i"].to_list() if "p01i" in sub.columns else [None] * sub.height

        kcp = max((v for v in tmp_c if v is not None), default=None)
        if kcp is None:
            continue
        t06 = next((tmp_c[i] for i in reversed(range(len(loc_h))) if loc_h[i] <= 6 and tmp_c[i] is not None), None)
        t_cp = next((v for v in reversed(tmp_c) if v is not None), None)
        delta_06_cp = (t_cp - t06) if (t06 is not None and t_cp is not None) else None
        # TIMESTAMP-based CP window [cp_utc-3h, cp_utc)
        cp_lo = cp_utc - timedelta(hours=_CP_WINDOW_H)
        cp_quads = [_quadrant(drct[i]) for i in range(len(ts)) if ts[i] >= cp_lo]
        cnt: dict[str, int] = {}
        for q in cp_quads:
            if q is not None:
                cnt[q] = cnt.get(q, 0) + 1
        q_cp = max(cnt.items(), key=lambda kv: kv[1])[0] if cnt else None
        # overnight modal quadrant (00-06 local) for the s_to_n transition feature (v0.1b)
        on_quads = [_quadrant(drct[i]) for i in range(len(loc_h)) if loc_h[i] < 6]
        on_cnt: dict[str, int] = {}
        for q in on_quads:
            if q is not None:
                on_cnt[q] = on_cnt.get(q, 0) + 1
        q_overnight = max(on_cnt.items(), key=lambda kv: kv[1])[0] if on_cnt else None

        def _win_rain(lo, hi):
            idx = [i for i, h in enumerate(loc_h) if lo <= h < hi]
            return any(_is_rain(wx[i], p01[i]) for i in idx) if idx else False
        rain_path = _win_rain(0, 6) and _win_rain(6, 9) and _win_rain(9, 24)

        rows.append({
            "date_local": d, "month": d.month,
            "delta_06_to_cp": delta_06_cp,
            "southerly_at_cp": int(q_cp == "S"),
            "rain_persistence_path": int(rain_path),
            "s_to_n": int(q_overnight == "S" and q_cp == "N"),
            "month_sin": math.sin(2 * math.pi * d.month / 12.0),
            "month_cos": math.cos(2 * math.pi * d.month / 12.0),
            "target": int((int(lr["tmax_int"]) - int(kcp)) >= 2),
        })
    return pl.DataFrame(rows)


def _matrix(df: pl.DataFrame, feats: Sequence[str] = FEATURE_NAMES) -> np.ndarray:
    cols = []
    for c in feats:
        v = df[c].to_numpy().astype(float)
        cols.append(np.where(np.isnan(v), np.nan, v))
    return np.column_stack(cols)


def fit_risk_model(train: pl.DataFrame, *, calib: pl.DataFrame | None = None, seed: int = 42,
                   feats: Sequence[str] = FEATURE_NAMES) -> LateWarmingRiskModel:
    """Fit logistic on TRAIN; calibrate probabilities (isotonic) on held-out CALIB if given."""
    X = _matrix(train, feats)
    y = train["target"].to_numpy().astype(int)
    means = np.nanmean(X, axis=0)
    means = np.where(np.isnan(means), 0.0, means)
    X = np.where(np.isnan(X), means, X)
    stds = X.std(axis=0)
    stds = np.where(stds < 1e-9, 1.0, stds)
    Xs = (X - means) / stds
    lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=seed)
    lr.fit(Xs, y)
    iso = None
    if calib is not None and calib.height >= 50:
        Xc = _matrix(calib, feats)
        Xc = np.where(np.isnan(Xc), means, Xc)
        Xcs = (Xc - means) / stds
        raw = lr.predict_proba(Xcs)[:, 1]
        yc = calib["target"].to_numpy().astype(int)
        if np.unique(yc).size == 2:
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            iso.fit(raw, yc)
    return LateWarmingRiskModel(logistic=lr, isotonic=iso, feat_means=means, feat_stds=stds,
                                feats=tuple(feats))


def predict_risk(model: LateWarmingRiskModel, df: pl.DataFrame) -> np.ndarray:
    X = _matrix(df, model.feats)
    X = np.where(np.isnan(X), model.feat_means, X)
    Xs = (X - model.feat_means) / model.feat_stds
    p = model.logistic.predict_proba(Xs)[:, 1]
    if model.isotonic is not None:
        p = model.isotonic.transform(p)
    return np.clip(np.asarray(p, dtype=float), 0.0, 1.0)


def risk_bucket(p: float, *, lo: float = 0.30, hi: float = 0.50) -> str:
    """low (<lo) / mid / high (>=hi). Thresholds are reporting defaults, not learned here."""
    return "low" if p < lo else ("high" if p >= hi else "mid")


__all__ = [
    "FEATURE_NAMES", "RISK_MODEL_VERSION", "LateWarmingRiskModel",
    "build_features", "fit_risk_model", "predict_risk", "risk_bucket",
]
