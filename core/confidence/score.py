"""Calibrated confidence score (Phase 5, design 8.3 / REQ-CONF-1..2).

``confidence_score = sigmoid(w . phi)`` post-calibrated by isotonic regression, where
``phi`` aggregates the REQ-CONF-2 minimum signal set (per forecast row):

  phi0  -entropy(prob_dist)            peaked bracket distribution -> confident
  phi1  -(ic80_high - ic80_low)        narrow IC80 -> confident
  phi2  -nwp_spread                     ensemble agreement -> confident (optional)
  phi3  -Var(p50 of earlier CPs)        CP-to-CP stability -> confident (optional)
  phi4  +distance-to-threshold          p50 sits centered in its bracket -> confident
  phi5  -spike_risk                     late-spike risk lowers confidence (Phase 7, REQ-CONF-2)

Three signals are *optional per row*: ``nwp_spread`` (no NWP that period), ``p50_var``
(the first CP of a day has no earlier p50), and ``spike_risk`` (no spike model wired).
They arrive as ``None`` and are imputed to the FITTED train mean, so a missing signal
contributes exactly zero after centering -- never a magic sentinel. A column that is
missing for ALL rows has zero variance and is neutralized (std clamped to 1 ->
standardized to all-zeros).

Weights ``w`` are learned by L2 logistic regression against ``bracket_correct`` and
the scores are calibrated by isotonic regression (REQ-CONF-1). Both are deterministic
(lbfgs + PAVA, no RNG -> REQ-MOD-6 safe). This module builds the STRUCTURE and the
REQ-CONF-1 audit metrics (ECE + the mandatory ``bracket_match @ coverage`` table); it
freezes NO threshold. The documented ECE<=0.05 gate (REQ-CONF-1) and the low-confidence
NO_TRADE cutoff (REQ-CONF-3, learned via REQ-DEC-3) are applied downstream, never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from core.contracts.quantization import Q

PHI_NAMES = (
    "neg_entropy",
    "neg_ic_width",
    "neg_nwp_spread",
    "neg_p50_var",
    "dist_to_threshold",
    "neg_spike_risk",
)
_N_PHI = len(PHI_NAMES)


@dataclass(frozen=True)
class ConfidenceConfig:
    """Calibration knobs (design 8.3). ``ece_tol`` mirrors the REQ-CONF-1 documented
    0.05 audit gate -- it is REPORTED here, never enforced as a build failure."""

    l2: float = 1.0  # ridge strength; sklearn C = 1 / l2
    isotonic: bool = True  # post-hoc isotonic calibration of the logistic score
    ece_bins: int = 10
    ece_tol: float = 0.05


@dataclass(frozen=True)
class FittedConfidence:
    """Standardizer + logistic weights + optional isotonic map (consulted by predict)."""

    config: ConfidenceConfig
    feat_means: np.ndarray  # (5,) train means used for imputation + centering
    feat_stds: np.ndarray  # (5,) train stds (zero-variance clamped to 1)
    logistic: LogisticRegression
    isotonic: IsotonicRegression | None
    phi_names: tuple[str, ...] = PHI_NAMES


@dataclass(frozen=True)
class ConfidenceReport:
    """REQ-CONF-1 audit surface: ECE + selective ``bracket_match @ coverage`` table."""

    ece: float
    ece_bins: int
    ece_tol: float
    ece_within_tol: bool  # ece <= ece_tol (REQ-CONF-1 documented 0.05); reported only
    n: int
    bracket_match_by_coverage: dict[float, tuple[float, int]]  # cov -> (match_rate, n_kept)


def entropy(prob_dist: dict[int, float]) -> float:
    """Shannon entropy (nats) of a discrete bracket distribution; 0 for a point mass."""
    p = np.array(list(prob_dist.values()), dtype=float)
    p = p[p > 0.0]
    if p.size == 0:
        return 0.0
    p = p / p.sum()  # defensive renormalize
    return float(-(p * np.log(p)).sum())


def distance_to_threshold(p50_dec: float) -> float:
    """Distance from the continuous p50 to the nearer bracket edge ``k +/- 0.5``.

    ``0.5`` when p50 sits at a bracket center (most confident), ~``0`` at an edge.
    """
    k = Q(float(p50_dec))
    d = min(float(p50_dec) - (k - 0.5), (k + 0.5) - float(p50_dec))
    return max(0.0, d)


def _raw_phi(
    prob_dist: Sequence[dict[int, float]],
    ic80_low_int: Sequence[int],
    ic80_high_int: Sequence[int],
    p50_dec: Sequence[float],
    nwp_spread: Sequence[float | None] | None,
    p50_var: Sequence[float | None] | None,
    spike_risk: Sequence[float | None] | None = None,
) -> np.ndarray:
    """Assemble the raw (n, 6) phi matrix; optional signals carry ``np.nan`` when absent."""
    n = len(prob_dist)
    lo = np.asarray(ic80_low_int, dtype=float)
    hi = np.asarray(ic80_high_int, dtype=float)
    p50 = np.asarray(p50_dec, dtype=float)
    if not (lo.size == hi.size == p50.size == n):
        raise ValueError("prob_dist, ic80_low_int, ic80_high_int, p50_dec must be same length")

    spread = (
        np.array([np.nan if v is None else float(v) for v in nwp_spread], dtype=float)
        if nwp_spread is not None
        else np.full(n, np.nan, dtype=float)
    )
    pvar = (
        np.array([np.nan if v is None else float(v) for v in p50_var], dtype=float)
        if p50_var is not None
        else np.full(n, np.nan, dtype=float)
    )
    spike = (
        np.array([np.nan if v is None else float(v) for v in spike_risk], dtype=float)
        if spike_risk is not None
        else np.full(n, np.nan, dtype=float)
    )
    if spread.size != n or pvar.size != n or spike.size != n:
        raise ValueError("nwp_spread / p50_var / spike_risk length must match when provided")

    x = np.empty((n, _N_PHI), dtype=float)
    x[:, 0] = [-entropy(pd) for pd in prob_dist]
    x[:, 1] = -(hi - lo)
    x[:, 2] = -spread
    x[:, 3] = -pvar
    x[:, 4] = [distance_to_threshold(v) for v in p50]
    x[:, 5] = -spike
    return x


def _standardize_fit(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Column means/stds over finite entries; impute NaN->mean, clamp std==0 -> 1.

    Means are computed manually (not ``nanmean``) so an all-missing column yields 0
    without a RuntimeWarning -- it is then neutralized by the std clamp below.
    """
    finite = ~np.isnan(x)
    counts = finite.sum(axis=0)
    sums = np.where(finite, x, 0.0).sum(axis=0)
    means = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    xc = np.where(np.isnan(x), means, x)
    stds = xc.std(axis=0)
    stds = np.where(stds > 1e-12, stds, 1.0)
    return (xc - means) / stds, means, stds


def _standardize_apply(x: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    xc = np.where(np.isnan(x), means, x)
    return (xc - means) / stds


def fit_confidence(
    prob_dist: Sequence[dict[int, float]],
    ic80_low_int: Sequence[int],
    ic80_high_int: Sequence[int],
    p50_dec: Sequence[float],
    bracket_correct: Sequence[int],
    *,
    nwp_spread: Sequence[float | None] | None = None,
    p50_var: Sequence[float | None] | None = None,
    spike_risk: Sequence[float | None] | None = None,
    config: ConfidenceConfig = ConfidenceConfig(),
) -> FittedConfidence:
    """Fit the standardizer + L2 logistic weights (+ optional isotonic calibration).

    ``bracket_correct`` is the temporal-holdout label ``1{p50_int hits the realized
    bracket}`` (REQ-CONF-1). Both classes must be present, else confidence cannot be
    calibrated. ``nwp_spread`` / ``p50_var`` / ``spike_risk`` are per-row and may contain ``None``.
    """
    y = np.asarray(bracket_correct, dtype=int)
    if y.size != len(prob_dist):
        raise ValueError("bracket_correct must match prob_dist length")
    if y.size == 0:
        raise ValueError("cannot fit confidence on empty data")
    if set(np.unique(y).tolist()) - {0, 1}:
        raise ValueError("bracket_correct must be binary 0/1")
    if np.unique(y).size < 2:
        raise ValueError("bracket_correct must contain both classes to calibrate confidence")

    x_raw = _raw_phi(prob_dist, ic80_low_int, ic80_high_int, p50_dec, nwp_spread, p50_var, spike_risk)
    x_std, means, stds = _standardize_fit(x_raw)

    logistic = LogisticRegression(C=1.0 / config.l2, solver="lbfgs", max_iter=1000)
    logistic.fit(x_std, y)

    iso: IsotonicRegression | None = None
    if config.isotonic:
        raw_p = logistic.predict_proba(x_std)[:, 1]
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(raw_p, y)

    return FittedConfidence(
        config=config, feat_means=means, feat_stds=stds, logistic=logistic, isotonic=iso
    )


def confidence_score(
    fitted: FittedConfidence,
    prob_dist: Sequence[dict[int, float]],
    ic80_low_int: Sequence[int],
    ic80_high_int: Sequence[int],
    p50_dec: Sequence[float],
    *,
    nwp_spread: Sequence[float | None] | None = None,
    p50_var: Sequence[float | None] | None = None,
    spike_risk: Sequence[float | None] | None = None,
) -> np.ndarray:
    """Calibrated ``confidence_score`` in ``[0, 1]`` for each forecast row."""
    x_raw = _raw_phi(prob_dist, ic80_low_int, ic80_high_int, p50_dec, nwp_spread, p50_var, spike_risk)
    x_std = _standardize_apply(x_raw, fitted.feat_means, fitted.feat_stds)
    p = fitted.logistic.predict_proba(x_std)[:, 1]
    if fitted.isotonic is not None:
        p = fitted.isotonic.transform(p)
    return np.clip(np.asarray(p, dtype=float), 0.0, 1.0)


def ece(confidence: Sequence[float], bracket_correct: Sequence[int], *, bins: int = 10) -> float:
    """Expected Calibration Error: sum_b (n_b/n) * |acc_b - conf_b| over equal-width bins."""
    c = np.asarray(confidence, dtype=float)
    y = np.asarray(bracket_correct, dtype=float)
    if c.size != y.size:
        raise ValueError("confidence and bracket_correct must be same length")
    if c.size == 0:
        raise ValueError("cannot compute ECE on empty data")
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(c, edges[1:-1]), 0, bins - 1)
    total = 0.0
    n = c.size
    for b in range(bins):
        m = idx == b
        nb = int(m.sum())
        if nb:
            total += (nb / n) * abs(float(y[m].mean()) - float(c[m].mean()))
    return float(total)


def bracket_match_by_coverage(
    confidence: Sequence[float],
    bracket_correct: Sequence[int],
    *,
    coverages: Sequence[float] = (0.25, 0.50, 0.75, 1.00),
) -> dict[float, tuple[float, int]]:
    """Selective ``bracket_match`` on the most-confident fraction (REQ-CONF-1 table).

    ``coverage`` -> (match_rate among the top-confidence ``coverage`` of rows, n_kept).
    ``1.0`` is overall accuracy; smaller coverages should match BETTER if confidence
    is informative (the risk-coverage promise).
    """
    c = np.asarray(confidence, dtype=float)
    y = np.asarray(bracket_correct, dtype=float)
    if c.size != y.size:
        raise ValueError("confidence and bracket_correct must be same length")
    if c.size == 0:
        raise ValueError("cannot compute bracket_match on empty data")
    order = np.argsort(-c, kind="stable")  # most confident first, deterministic ties
    y_sorted = y[order]
    n = c.size
    out: dict[float, tuple[float, int]] = {}
    for cov in coverages:
        if not (0.0 < cov <= 1.0):
            raise ValueError(f"coverage must be in (0, 1]; got {cov}")
        k = max(1, int(round(cov * n)))
        out[float(cov)] = (float(y_sorted[:k].mean()), k)
    return out


def confidence_report(
    confidence: Sequence[float],
    bracket_correct: Sequence[int],
    *,
    config: ConfidenceConfig = ConfidenceConfig(),
) -> ConfidenceReport:
    """Bundle the REQ-CONF-1 audit metrics (ECE + selective bracket_match)."""
    e = ece(confidence, bracket_correct, bins=config.ece_bins)
    return ConfidenceReport(
        ece=e,
        ece_bins=config.ece_bins,
        ece_tol=config.ece_tol,
        ece_within_tol=e <= config.ece_tol,
        n=int(np.asarray(confidence).size),
        bracket_match_by_coverage=bracket_match_by_coverage(confidence, bracket_correct),
    )


__all__ = [
    "PHI_NAMES",
    "ConfidenceConfig",
    "FittedConfidence",
    "ConfidenceReport",
    "entropy",
    "distance_to_threshold",
    "fit_confidence",
    "confidence_score",
    "ece",
    "bracket_match_by_coverage",
    "confidence_report",
]
