"""Phase 5 coordination contract: the shared prediction-panel schema + the
pre-registered gate thresholds that calibration (conformal), confidence audit,
and the decision engine all consume (design 8.2 / 8.3, REQ-MOD-4 / REQ-CONF-1..3 /
REQ-AUD-5).

This module is the SINGLE SOURCE OF TRUTH for the interface between the parallel
Phase-5 workstreams so they cannot drift apart:

  A. prediction panel builder  -> PRODUCES rows of ``PHASE5_PANEL_COLUMNS``
  B. heteroscedasticity gate    -> CONSUMES (ic80 widths, coverage) per width-quartile
  C. confidence audit emitter   -> CONSUMES confidence + bracket_correct
  D. decision engine            -> CONSUMES confidence_score + MIN_CONFIDENCE_*

The thresholds below are PRE-REGISTERED (they live in the spec/design and
``nzwn/config/model.yaml`` already), NOT frozen after seeing results. The empirical
gate is *applied* only in the integration step (``scripts/phase5_evaluate.py``);
nothing here tunes a bar against an observed outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

# --- panel layering ----------------------------------------------------------
# Layer 1 (RAW, produced by workstream A): everything derivable from a walk-forward
# run of the Phase-4 residual model BEFORE calibration. ``y_pred_dec`` is the latent
# point forecast (``predict_latent``); ``prob_dist`` is its band-aware softmax
# (``latent_to_prob_dist``); ``bracket_correct = 1{Q(y_pred_dec) == y_true_int}``.
#
# Layer 2 (POST-CONFORMAL, added by the integrator): ``ic80_low_int`` / ``ic80_high_int``
# from ``apply_conformal``. Confidence fitting (C) needs Layer 2, so in the parallel
# phase C builds against SYNTHETIC ic80 arrays of this same shape.

RAW_PANEL_COLUMNS: tuple[str, ...] = (
    "split",          # str  walk-forward split name, e.g. "2023-01-01_to_2023-12-31"
    "role",           # str  ROLE_CALIB | ROLE_TEST (calib = conformal residual set)
    "date_local",     # pl.Date
    "cp",             # str  CP label (same string space as cfg.cp_set_utc)
    "cp_utc",         # pl.Datetime(UTC)  for the frozen-obs / leakage audit
    "nwp_run_time_utc",  # pl.Datetime(UTC) | null  for the leakage audit
    "month",          # int  1..12
    "regime",         # int | null  ALWAYS null in Phase 5 (regime GMM is Phase 7)
    "y_true_int",     # int  realized Tmax bracket
    "y_pred_dec",     # float  latent point forecast (= p50 decimal)
    "nwp_spread",     # float | null  ensemble disagreement (nwp_t2m_maxtraj_spread_c)
    "p50_var",        # float | null  Var(y_pred_dec) over EARLIER CPs same day; null at 1st CP
    "bracket_correct",  # int 0/1  1{Q(y_pred_dec) == y_true_int} (confidence label)
)

# prob_dist (dict[int,float]) travels ALONGSIDE the frame as a python list aligned
# row-for-row, because polars has no native dict column; A returns (panel, prob_dists).
PROB_DIST_SIDE_KEY = "prob_dist"

POST_CONFORMAL_COLUMNS: tuple[str, ...] = ("ic80_low_int", "ic80_high_int")

PHASE5_PANEL_COLUMNS: tuple[str, ...] = RAW_PANEL_COLUMNS + POST_CONFORMAL_COLUMNS

ROLE_CALIB = "calib"
ROLE_TEST = "test"
ROLES = (ROLE_CALIB, ROLE_TEST)

RAW_PANEL_SCHEMA: dict[str, pl.DataType] = {
    "split": pl.Utf8,
    "role": pl.Utf8,
    "date_local": pl.Date,
    "cp": pl.Utf8,
    "cp_utc": pl.Datetime("us", time_zone="UTC"),
    "nwp_run_time_utc": pl.Datetime("us", time_zone="UTC"),
    "month": pl.Int32,
    "regime": pl.Int32,
    "y_true_int": pl.Int32,
    "y_pred_dec": pl.Float64,
    "nwp_spread": pl.Float64,
    "p50_var": pl.Float64,
    "bracket_correct": pl.Int32,
}


# --- pre-registered gate thresholds (NOT post-hoc) ---------------------------
# T-5-1 (REQ-MOD-4): empirical IC80 coverage must sit within tol of target.
COVERAGE_TARGET = 0.80
COVERAGE_TOL = 0.04  # |coverage - 0.80| < 0.04
COVERAGE_BAND_LO = COVERAGE_TARGET - COVERAGE_TOL  # 0.76
COVERAGE_BAND_HI = COVERAGE_TARGET + COVERAGE_TOL  # 0.84

# --- conformal METHOD amendment (criterion_version 1.0; phase5_preregistration.md) -
# The IC80 interval is produced by NORMALIZED QUANTIZATION-AWARE conformal: the
# calibrator is fit on the SAME integer-inclusive bracket object the gate evaluates
# (not a decimal interval that is later quantized). Frozen knobs below; the c-grid and
# selection rule are pre-registered so nothing is tuned against the test split.
CONFORMAL_METHOD = "normalized_quantization_aware"
CONFORMAL_METHOD_VERSION = "1.0"
SIGMA_PROXY = "p50_var"        # per-row sigma_hat(x); nwp_spread is signal-free here
SIGMA_IS_VARIANCE = True       # p50_var is a variance -> sqrt to a stddev
C_GRID_START = 0.50
C_GRID_STOP = 0.96
C_GRID_STEP = 0.005

# T-5-3 (REQ-AUD-5) heteroscedasticity gate: bin rows by IC80-width quartile and
# require every bin's coverage inside [LOW, HIGH]. Fails if one bin violates while
# another is inside (interval width that does not track difficulty).
HETEROSCED_COVERAGE_LOW = 0.70
HETEROSCED_COVERAGE_HIGH = 0.90
HETEROSCED_N_BINS = 4  # quartiles of IC width

# T-5-4 (REQ-CONF-1): confidence calibration error gate (reported in audit).
ECE_TOL = 0.05

# T-5-6 (REQ-CONF-3): the OPERATIONAL min-confidence cutoff is LEARNED downstream
# (REQ-DEC-3), NOT fixed here. This is only the config DEFAULT used until the
# learned value exists; the decision engine reads it from model.yaml.
MIN_CONFIDENCE_DEFAULT = 0.55

# Selective bracket_match coverage points reported by the confidence audit (T-5-5).
CONFIDENCE_COVERAGE_POINTS: tuple[float, ...] = (0.25, 0.50, 0.75, 1.00)


@dataclass(frozen=True)
class Phase5Contract:
    """Bundle so callers can pass one object instead of many constants."""

    coverage_target: float = COVERAGE_TARGET
    coverage_tol: float = COVERAGE_TOL
    heterosced_low: float = HETEROSCED_COVERAGE_LOW
    heterosced_high: float = HETEROSCED_COVERAGE_HIGH
    heterosced_n_bins: int = HETEROSCED_N_BINS
    ece_tol: float = ECE_TOL
    min_confidence_default: float = MIN_CONFIDENCE_DEFAULT


__all__ = [
    "RAW_PANEL_COLUMNS",
    "POST_CONFORMAL_COLUMNS",
    "PHASE5_PANEL_COLUMNS",
    "PROB_DIST_SIDE_KEY",
    "RAW_PANEL_SCHEMA",
    "ROLE_CALIB",
    "ROLE_TEST",
    "ROLES",
    "COVERAGE_TARGET",
    "COVERAGE_TOL",
    "COVERAGE_BAND_LO",
    "COVERAGE_BAND_HI",
    "CONFORMAL_METHOD",
    "CONFORMAL_METHOD_VERSION",
    "SIGMA_PROXY",
    "SIGMA_IS_VARIANCE",
    "C_GRID_START",
    "C_GRID_STOP",
    "C_GRID_STEP",
    "HETEROSCED_COVERAGE_LOW",
    "HETEROSCED_COVERAGE_HIGH",
    "HETEROSCED_N_BINS",
    "ECE_TOL",
    "MIN_CONFIDENCE_DEFAULT",
    "CONFIDENCE_COVERAGE_POINTS",
    "Phase5Contract",
]
