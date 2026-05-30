"""Conformal calibration per CP (Phase 5, design 8.2 / REQ-MOD-4).

Split-conformal prediction that turns a point latent forecast ``T_latent_dec``
into an integer IC80 ``[ic80_low_int, ic80_high_int]`` with (approximately)
``1 - alpha`` marginal coverage. Calibration is done PER CP (every active
``cp_utc``) and OPTIONALLY per ``(month, regime, cp)`` bucket with a documented
``n_min`` (REQ-MOD-4): buckets below ``n_min`` fall back to the per-CP calibrator,
and an unseen CP falls back to the pooled calibrator.

Two nonconformity scores are supported:
- ``"signed"`` (default): separate lower/upper empirical residual quantiles ->
  ASYMMETRIC interval. Naturally corrects a biased point forecast (e.g. the
  documented GFS cold bias) because both offsets shift with the residual median.
- ``"absolute"``: a single ``|residual|`` quantile -> SYMMETRIC interval with the
  classic finite-sample coverage guarantee (``>= 1 - alpha``), at the cost of
  over-covering when residuals are skewed.

The conformal quantile uses the finite-sample rank ``ceil((n+1)(1-alpha))`` (and
``floor((n+1) alpha/2)`` for the lower signed tail). When ``n`` is too small to
certify the requested coverage the rank is clamped to the most extreme observed
residual (the widest data-supported interval) instead of ``+/-inf``, so ``Q``
never sees a non-finite value.

Deterministic (sorting only; no RNG) -> REQ-MOD-6 safe. Model-agnostic: it
consumes ``(truth, point_pred, cp)`` and is unaware of how the point forecast was
produced, so it serves Phase 4's residual model in the success branch AND a
demoted NWP-as-feature model in the Plan-B branch alike. Wiring into the forecast
pipeline and freezing the Phase-5 coverage gate happen later; nothing here tunes a
threshold against results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from core.contracts.quantization import Q, Q_rand

_METHODS = ("signed", "absolute")


@dataclass(frozen=True)
class ConformalConfig:
    """Calibration knobs (design 8.2). ``coverage`` is the two-sided target.

    ``n_min_bucket`` is the documented REQ-MOD-4 bucket floor; ``min_calib`` is the
    smaller floor below which even a per-CP key cannot stand alone and falls back to
    the pooled calibrator.
    """

    coverage: float = 0.80
    method: str = "signed"
    n_min_bucket: int = 200
    min_calib: int = 30


@dataclass(frozen=True)
class IntervalOffsets:
    """Additive offsets applied to the point forecast: ``[yhat + lo, yhat + hi]``."""

    lo_offset: float
    hi_offset: float
    n_calib: int
    certified: bool  # False if n was too small to certify coverage (rank clamped)


@dataclass(frozen=True)
class ConformalCalibrator:
    """Fitted offsets at three granularities, consulted bucket -> cp -> pooled."""

    config: ConformalConfig
    pooled: IntervalOffsets
    by_cp: dict[str, IntervalOffsets] = field(default_factory=dict)
    by_bucket: dict[tuple, IntervalOffsets] = field(default_factory=dict)


@dataclass(frozen=True)
class CoverageReport:
    """Empirical coverage + sharpness of an emitted integer interval set."""

    target: float
    tol: float
    coverage: float
    abs_error: float
    within_tol: bool
    mean_width_brackets: float
    n: int
    by_cp: dict[str, tuple[float, float, int]]  # cp -> (coverage, mean_width, n)


def _offsets_from_residuals(
    residuals: np.ndarray, *, coverage: float, method: str
) -> IntervalOffsets:
    """Conformal lower/upper offsets from calibration residuals ``truth - pred``."""
    r = np.asarray(residuals, dtype=float)
    n = int(r.size)
    if n == 0:
        raise ValueError("cannot calibrate on an empty residual set")
    if np.isnan(r).any():
        raise ValueError("residuals contain NaN; clean inputs before calibrating")
    alpha = 1.0 - coverage

    if method == "absolute":
        s = np.sort(np.abs(r))
        rank = math.ceil((n + 1) * coverage)
        certified = rank <= n
        q = float(s[min(max(rank, 1), n) - 1])
        return IntervalOffsets(lo_offset=-q, hi_offset=q, n_calib=n, certified=certified)

    if method == "signed":
        s = np.sort(r)
        rank_hi = math.ceil((n + 1) * (1.0 - alpha / 2.0))
        rank_lo = math.floor((n + 1) * (alpha / 2.0))
        certified = rank_hi <= n and rank_lo >= 1
        hi = float(s[min(max(rank_hi, 1), n) - 1])
        lo = float(s[min(max(rank_lo, 1), n) - 1])
        if lo > hi:  # defensive; sorted ranks should already order these
            lo, hi = hi, lo
        return IntervalOffsets(lo_offset=lo, hi_offset=hi, n_calib=n, certified=certified)

    raise ValueError(f"method must be one of {_METHODS}; got {method!r}")


def fit_conformal(
    y_true: Sequence[float],
    y_pred_dec: Sequence[float],
    cp: Sequence[str],
    *,
    config: ConformalConfig = ConformalConfig(),
    month: Sequence[int] | None = None,
    regime: Sequence[int | None] | None = None,
) -> ConformalCalibrator:
    """Fit pooled + per-CP (+ optional per-bucket) conformal offsets.

    ``y_pred_dec`` is the continuous point forecast (``T_latent_dec``); residuals
    are ``y_true - y_pred_dec`` in decimal degC. Buckets keyed ``(month, regime,
    cp)`` are only built when ``month`` is supplied and only KEPT when they reach
    ``config.n_min_bucket`` rows; ``regime`` may carry ``None`` per row.
    """
    if config.method not in _METHODS:
        raise ValueError(f"config.method must be one of {_METHODS}; got {config.method!r}")
    if not (0.0 < config.coverage < 1.0):
        raise ValueError(f"coverage must be in (0,1); got {config.coverage}")
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred_dec, dtype=float)
    cps = list(cp)
    if not (yt.size == yp.size == len(cps)):
        raise ValueError(
            f"y_true, y_pred_dec, cp must be same length; got {yt.size}, {yp.size}, {len(cps)}"
        )
    if yt.size == 0:
        raise ValueError("cannot fit on empty data")
    resid = yt - yp

    pooled = _offsets_from_residuals(resid, coverage=config.coverage, method=config.method)

    by_cp: dict[str, IntervalOffsets] = {}
    cp_arr = np.asarray(cps, dtype=object)
    for key in dict.fromkeys(cps):  # stable unique order
        mask = cp_arr == key
        if int(mask.sum()) >= config.min_calib:
            by_cp[key] = _offsets_from_residuals(
                resid[mask], coverage=config.coverage, method=config.method
            )

    by_bucket: dict[tuple, IntervalOffsets] = {}
    if month is not None:
        months = np.asarray(list(month), dtype=object)
        regimes = (
            np.asarray(list(regime), dtype=object)
            if regime is not None
            else np.asarray([None] * yt.size, dtype=object)
        )
        if not (months.size == regimes.size == yt.size):
            raise ValueError("month/regime length must match y_true when provided")
        seen: set[tuple] = set()
        for i in range(yt.size):
            bkey = (int(months[i]), regimes[i], cps[i])
            if bkey in seen:
                continue
            seen.add(bkey)
            bmask = np.array(
                [
                    (int(months[j]) == bkey[0]) and (regimes[j] == bkey[1]) and (cps[j] == bkey[2])
                    for j in range(yt.size)
                ]
            )
            if int(bmask.sum()) >= config.n_min_bucket:
                by_bucket[bkey] = _offsets_from_residuals(
                    resid[bmask], coverage=config.coverage, method=config.method
                )

    return ConformalCalibrator(config=config, pooled=pooled, by_cp=by_cp, by_bucket=by_bucket)


def _offsets_for_row(
    cal: ConformalCalibrator, cp_i: str, month_i: int | None, regime_i: int | None
) -> IntervalOffsets:
    """Resolve offsets for one row: bucket (if present) -> cp -> pooled."""
    if month_i is not None:
        off = cal.by_bucket.get((int(month_i), regime_i, cp_i))
        if off is not None:
            return off
    off = cal.by_cp.get(cp_i)
    if off is not None:
        return off
    return cal.pooled


def interval_dec(
    cal: ConformalCalibrator,
    y_pred_dec: Sequence[float],
    cp: Sequence[str],
    *,
    month: Sequence[int] | None = None,
    regime: Sequence[int | None] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Continuous IC bounds ``(lo_dec, hi_dec)`` before quantization (math hook)."""
    yp = np.asarray(y_pred_dec, dtype=float)
    cps = list(cp)
    if yp.size != len(cps):
        raise ValueError(f"y_pred_dec and cp must match; got {yp.size}, {len(cps)}")
    months = list(month) if month is not None else [None] * yp.size
    regimes = list(regime) if regime is not None else [None] * yp.size
    lo = np.empty(yp.size, dtype=float)
    hi = np.empty(yp.size, dtype=float)
    for i in range(yp.size):
        off = _offsets_for_row(cal, cps[i], months[i], regimes[i])
        lo[i] = yp[i] + off.lo_offset
        hi[i] = yp[i] + off.hi_offset
    return lo, hi


def apply_conformal(
    cal: ConformalCalibrator,
    y_pred_dec: Sequence[float],
    cp: Sequence[str],
    *,
    month: Sequence[int] | None = None,
    regime: Sequence[int | None] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Emit integer IC80 ``(ic80_low_int, ic80_high_int)`` via ``Q`` on the bounds.

    The high bound is clamped ``>= `` the low bound so quantization can never emit
    an inverted interval (design: ``Q`` applied to the continuous IC).
    """
    lo_dec, hi_dec = interval_dec(cal, y_pred_dec, cp, month=month, regime=regime)
    lo_int = np.array([Q(float(v)) for v in lo_dec], dtype=np.int32)
    hi_int = np.array([Q(float(v)) for v in hi_dec], dtype=np.int32)
    hi_int = np.maximum(hi_int, lo_int)
    return lo_int, hi_int


def coverage_report(
    ic80_low_int: Sequence[int],
    ic80_high_int: Sequence[int],
    y_true_int: Sequence[int],
    cp: Sequence[str],
    *,
    target: float = 0.80,
    tol: float = 0.04,
) -> CoverageReport:
    """Empirical coverage of an emitted integer interval set (REQ-MOD-4 gate input).

    ``within_tol`` reflects ``|coverage - target| < tol`` (the REQ-MOD-4 / REQ-AUD-2
    ``|coverage_80 - 0.80| < 0.04`` check). Width is in integer brackets,
    ``hi - lo + 1``.
    """
    lo = np.asarray(ic80_low_int, dtype=int)
    hi = np.asarray(ic80_high_int, dtype=int)
    yt = np.asarray(y_true_int, dtype=int)
    cps = list(cp)
    if not (lo.size == hi.size == yt.size == len(cps)):
        raise ValueError("ic80_low_int, ic80_high_int, y_true_int, cp must be same length")
    if yt.size == 0:
        raise ValueError("cannot report coverage on empty data")
    covered = (lo <= yt) & (yt <= hi)
    widths = (hi - lo + 1).astype(float)
    coverage = float(covered.mean())

    by_cp: dict[str, tuple[float, float, int]] = {}
    cp_arr = np.asarray(cps, dtype=object)
    for key in dict.fromkeys(cps):
        mask = cp_arr == key
        by_cp[key] = (
            float(covered[mask].mean()),
            float(widths[mask].mean()),
            int(mask.sum()),
        )

    abs_error = abs(coverage - target)
    return CoverageReport(
        target=target,
        tol=tol,
        coverage=coverage,
        abs_error=abs_error,
        within_tol=abs_error < tol,
        mean_width_brackets=float(widths.mean()),
        n=int(yt.size),
        by_cp=by_cp,
    )


# --- normalized quantization-aware conformal (Phase 5 amendment) -------------
# Pre-registered in contracts/phase5_preregistration.md (criterion_version 1.0).
# RATIONALE: the prior path calibrated a DECIMAL interval then quantized it with Q,
# but the gate evaluates the INTEGER-INCLUSIVE bracket interval [lo_int, hi_int] that
# must contain y_true_int. Calibrating one object and evaluating another breaks the
# conformal coverage guarantee by construction (diagnosed +0.06..+0.11 coverage gap).
# This method calibrates on the SAME object that is evaluated, with a per-row
# normalized score (sigma_hat(x) -> non-degenerate, heteroscedastic widths) and a
# CONTINUOUS nominal-level knob c (defeats the discrete-w granularity straddle).


@dataclass(frozen=True)
class NormalizedConformalConfig:
    """Knobs for the normalized quantization-aware conformal (frozen amendment).

    The nominal level ``c`` is SELECTED ON CALIB by sweeping ``[c_start, c_stop]`` at
    ``c_step``: pick the ``c`` whose in-sample integer coverage lands in
    ``[band_lo, band_hi]`` minimizing ``|coverage - coverage_target|``; if none lands
    in band, fall back to the ``c`` closest to ``coverage_target``. ``sigma_is_variance``
    means ``sigma_hat`` arrives as a VARIANCE (``p50_var``) and is sqrt'd to a stddev.
    """

    coverage_target: float = 0.80
    band_lo: float = 0.76
    band_hi: float = 0.84
    c_start: float = 0.50
    c_stop: float = 0.96
    c_step: float = 0.005
    sigma_is_variance: bool = True
    method_version: str = "1.0"
    # Track A.A1 amendment (conformal_method_version 1.1; contracts/phase5_amendment.md):
    # winsorize sigma_hat to a CALIB-FROZEN [P_lo, P_hi] percentile band, used in BOTH
    # the score u and the emitted interval. Default OFF -> the v1.0 path is unchanged.
    winsorize: bool = False
    winsor_pctl_lo: float = 25.0
    winsor_pctl_hi: float = 95.0
    # Track P amendment (conformal_method_version 1.3; predictive-uncertainty sigma):
    # when set, the sigma floor is the CALIB percentile of the prepared sigma_hat
    # (frozen on calib, reused on apply via cal.sigma_floor) instead of the default
    # max(median*1e-3, 1e-6). Used for sigma_hat = entropy(prob_dist) where the floor is
    # numerical safety only. Default None -> the v1.0/A1/A3 floor is unchanged.
    sigma_floor_percentile: float | None = None


@dataclass(frozen=True)
class NormalizedConformalCalibrator:
    """Fitted normalized conformal: one ``c`` and two normalized tail quantiles.

    ``sigma_median`` / ``sigma_floor`` are frozen at fit time (from CALIB) so ``apply``
    imputes and floors test ``sigma_hat`` identically - no test statistic leaks back.
    """

    config: NormalizedConformalConfig
    c: float
    q_lo: float
    q_hi: float
    sigma_median: float
    sigma_floor: float
    calib_coverage: float
    in_band: bool
    n_calib: int
    # Winsorization clip bounds frozen from CALIB (None when winsorize is off). ``apply``
    # reuses these EXACT numbers so a different test sigma distribution cannot leak back.
    clip_lo: float | None = None
    clip_hi: float | None = None


def _prepare_sigma(
    sigma_raw: Sequence[float | None],
    *,
    is_variance: bool,
    median: float | None = None,
    floor: float | None = None,
) -> tuple[np.ndarray, float, float]:
    """Normalize a raw uncertainty proxy into a positive per-row ``sigma_hat``.

    Steps (deterministic, no RNG): sqrt if it is a variance; impute missing with the
    CALIB median (passed in on ``apply`` so test reuses the calib statistic); floor at
    ``max(median * 1e-3, 1e-6)`` so no row gets a zero/negative scale. ``median`` and
    ``floor`` are returned so the fit can pin them onto the calibrator.
    """
    s = np.asarray([np.nan if v is None else float(v) for v in sigma_raw], dtype=float)
    if is_variance:
        s = np.sqrt(np.clip(s, 0.0, None))
    if median is None:
        finite = s[np.isfinite(s)]
        med = float(np.median(finite)) if finite.size else 1.0
    else:
        med = float(median)
    if not math.isfinite(med) or med <= 0.0:
        med = 1.0
    s = np.where(np.isfinite(s), s, med)
    fl = float(floor) if floor is not None else max(med * 1e-3, 1e-6)
    s = np.maximum(s, fl)
    return s, med, fl


def _winsorize_sigma(
    sigma: np.ndarray,
    *,
    pctl_lo: float,
    pctl_hi: float,
    clip_lo: float | None = None,
    clip_hi: float | None = None,
) -> tuple[np.ndarray, float, float]:
    """Clip ``sigma`` to ``[clip_lo, clip_hi]`` (Track A.A1, phase5_amendment.md).

    On FIT (``clip_lo``/``clip_hi`` None) the bounds are the ``pctl_lo``/``pctl_hi``
    percentiles of the calib ``sigma`` (deterministic ``numpy.percentile``). On APPLY the
    caller passes the calib-frozen bounds so the test set reuses the SAME numbers - a
    different test sigma distribution cannot move the clip (no leakage). Returns the
    clipped sigma and the bounds actually used.
    """
    if clip_lo is None or clip_hi is None:
        lo = float(np.percentile(sigma, pctl_lo))
        hi = float(np.percentile(sigma, pctl_hi))
        if hi < lo:  # defensive; percentiles are monotone so this should not happen
            lo, hi = hi, lo
    else:
        lo, hi = float(clip_lo), float(clip_hi)
    return np.clip(sigma, lo, hi), lo, hi


def _normalized_int_interval(
    y_pred_dec: np.ndarray, sigma: np.ndarray, q_lo: float, q_hi: float
) -> tuple[np.ndarray, np.ndarray]:
    """Per-row integer-inclusive interval ``[Q(yhat + q_lo*sigma), Q(yhat + q_hi*sigma)]``."""
    lo_int = np.array([Q(float(p + q_lo * s)) for p, s in zip(y_pred_dec, sigma)], dtype=np.int32)
    hi_int = np.array([Q(float(p + q_hi * s)) for p, s in zip(y_pred_dec, sigma)], dtype=np.int32)
    hi_int = np.maximum(hi_int, lo_int)
    return lo_int, hi_int


def _c_grid(config: NormalizedConformalConfig) -> np.ndarray:
    """Deterministic nominal-level sweep grid (inclusive of c_stop within rounding)."""
    n = int(round((config.c_stop - config.c_start) / config.c_step)) + 1
    return np.round(config.c_start + config.c_step * np.arange(n), 6)


def apply_normalized_conformal_qrand(
    cal: "NormalizedConformalCalibrator",
    y_pred_dec: Sequence[float],
    sigma_raw: Sequence[float | None],
    row_ids: Sequence[str],
    *,
    global_seed: int,
    split_name: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Track D.D1: emit integer IC80 using ``Q_rand`` at the two endpoints.

    Identical to ``apply_normalized_conformal`` (same calib-frozen scale, same q_lo/q_hi)
    EXCEPT the deterministic quantizer ``Q`` is replaced by the randomized rounding
    ``Q_rand`` keyed by ``(global_seed, row_id, endpoint_side[, split_name])``. The two
    endpoints use distinct ``endpoint_side`` tags ('lo'/'hi') to decorrelate their draws.
    ``hi_int >= lo_int`` is enforced (fallback ``hi = lo``).
    """
    yp = np.asarray(y_pred_dec, dtype=float)
    raw = list(sigma_raw)
    rids = list(row_ids)
    if not (yp.size == len(raw) == len(rids)):
        raise ValueError(
            f"y_pred_dec, sigma_raw, row_ids must match; got {yp.size}, {len(raw)}, {len(rids)}"
        )
    sigma, _, _ = _prepare_sigma(
        raw,
        is_variance=cal.config.sigma_is_variance,
        median=cal.sigma_median,
        floor=cal.sigma_floor,
    )
    if cal.config.winsorize:
        sigma, _, _ = _winsorize_sigma(
            sigma,
            pctl_lo=cal.config.winsor_pctl_lo,
            pctl_hi=cal.config.winsor_pctl_hi,
            clip_lo=cal.clip_lo,
            clip_hi=cal.clip_hi,
        )
    lo_int = np.empty(yp.size, dtype=np.int32)
    hi_int = np.empty(yp.size, dtype=np.int32)
    for i in range(yp.size):
        rid = rids[i]
        lo_int[i] = Q_rand(
            float(yp[i] + cal.q_lo * sigma[i]),
            global_seed=global_seed, row_id_hex=rid, endpoint_side="lo", split_name=split_name,
        )
        hi_int[i] = Q_rand(
            float(yp[i] + cal.q_hi * sigma[i]),
            global_seed=global_seed, row_id_hex=rid, endpoint_side="hi", split_name=split_name,
        )
    hi_int = np.maximum(hi_int, lo_int)  # contract: hi >= lo, fallback hi = lo
    return lo_int, hi_int


def fit_normalized_conformal(
    y_true_int: Sequence[int],
    y_pred_dec: Sequence[float],
    sigma_raw: Sequence[float | None],
    *,
    config: NormalizedConformalConfig = NormalizedConformalConfig(),
) -> NormalizedConformalCalibrator:
    """Fit on CALIB: pick the nominal level ``c`` per the frozen selection rule.

    Score ``u = (y_true_int - y_pred_dec) / sigma_hat``; tails ``p_lo=(1-c)/2``,
    ``p_hi=1-(1-c)/2``; ``q_lo=quantile(u, p_lo)``, ``q_hi=quantile(u, p_hi)``. For each
    ``c`` the in-sample integer coverage is computed on the SAME calib rows (the object
    the gate evaluates). ``c`` is chosen test-blind. Deterministic (sorting/quantile
    only).
    """
    yt = np.asarray(y_true_int, dtype=float)
    yp = np.asarray(y_pred_dec, dtype=float)
    raw = list(sigma_raw)
    if not (yt.size == yp.size == len(raw)):
        raise ValueError(
            f"y_true_int, y_pred_dec, sigma_raw must be same length; "
            f"got {yt.size}, {yp.size}, {len(raw)}"
        )
    if yt.size == 0:
        raise ValueError("cannot fit normalized conformal on empty data")
    if config.sigma_floor_percentile is not None:
        # Track P: freeze the floor at a CALIB percentile of the prepared sigma_hat. We
        # prepare once with the default floor to apply sqrt/impute and learn the median,
        # take the percentile of that (the default floor ~1e-3 is far below any sane P1
        # for an entropy proxy, so it does not move the percentile), then re-prepare with
        # the frozen percentile floor so the calibrator pins the exact reused number.
        s_tmp, med_tmp, _ = _prepare_sigma(raw, is_variance=config.sigma_is_variance)
        floor_p = float(np.percentile(s_tmp, config.sigma_floor_percentile))
        sigma, med, fl = _prepare_sigma(
            raw, is_variance=config.sigma_is_variance, median=med_tmp, floor=floor_p
        )
    else:
        sigma, med, fl = _prepare_sigma(raw, is_variance=config.sigma_is_variance)
    clip_lo: float | None = None
    clip_hi: float | None = None
    if config.winsorize:
        sigma, clip_lo, clip_hi = _winsorize_sigma(
            sigma, pctl_lo=config.winsor_pctl_lo, pctl_hi=config.winsor_pctl_hi
        )
    u = (yt - yp) / sigma

    best_in_band_pack: tuple[float, float, float, float] | None = None
    best_in_band_dist = math.inf
    closest_pack: tuple[float, float, float, float] | None = None
    closest_dist = math.inf
    for c in _c_grid(config):
        c = float(c)
        p_lo = (1.0 - c) / 2.0
        p_hi = 1.0 - (1.0 - c) / 2.0
        q_lo = float(np.quantile(u, p_lo))
        q_hi = float(np.quantile(u, p_hi))
        lo_int, hi_int = _normalized_int_interval(yp, sigma, q_lo, q_hi)
        cov = float(((lo_int <= yt) & (yt <= hi_int)).mean())
        dist = abs(cov - config.coverage_target)
        pack = (c, q_lo, q_hi, cov)
        if dist < closest_dist:  # strict -> keeps the FIRST (lowest c) on ties
            closest_dist = dist
            closest_pack = pack
        if config.band_lo <= cov <= config.band_hi and dist < best_in_band_dist:
            best_in_band_dist = dist
            best_in_band_pack = pack

    chosen = best_in_band_pack if best_in_band_pack is not None else closest_pack
    c, q_lo, q_hi, cov = chosen
    return NormalizedConformalCalibrator(
        config=config,
        c=c,
        q_lo=q_lo,
        q_hi=q_hi,
        sigma_median=med,
        sigma_floor=fl,
        calib_coverage=cov,
        in_band=best_in_band_pack is not None,
        n_calib=int(yt.size),
        clip_lo=clip_lo,
        clip_hi=clip_hi,
    )


def apply_normalized_conformal(
    cal: NormalizedConformalCalibrator,
    y_pred_dec: Sequence[float],
    sigma_raw: Sequence[float | None],
) -> tuple[np.ndarray, np.ndarray]:
    """Emit integer IC80 ``(lo_int, hi_int)`` for fresh rows using calib-frozen scale."""
    yp = np.asarray(y_pred_dec, dtype=float)
    raw = list(sigma_raw)
    if yp.size != len(raw):
        raise ValueError(f"y_pred_dec and sigma_raw must match; got {yp.size}, {len(raw)}")
    sigma, _, _ = _prepare_sigma(
        raw,
        is_variance=cal.config.sigma_is_variance,
        median=cal.sigma_median,
        floor=cal.sigma_floor,
    )
    if cal.config.winsorize:
        sigma, _, _ = _winsorize_sigma(
            sigma,
            pctl_lo=cal.config.winsor_pctl_lo,
            pctl_hi=cal.config.winsor_pctl_hi,
            clip_lo=cal.clip_lo,
            clip_hi=cal.clip_hi,
        )
    return _normalized_int_interval(yp, sigma, cal.q_lo, cal.q_hi)


# --- Track A.A3: Mondrian conditional conformal by sigma bucket --------------
# Pre-registered in contracts/phase5_amendment_trackA_a3.md (conformal_method_version
# 1.2; a SEPARATE branch off v1.0, NOT bundled with A1's winsorization). RATIONALE: A1
# proved a GLOBAL sigma adjustment cannot move the wide width-bins into band because the
# over-coverage is CONDITIONAL on the sigma_hat regime. A3 makes the asymmetric tail
# quantiles (q_lo, q_hi) conditional on a sigma_hat bucket, with a fixed shrinkage toward
# the global pair to control degrees of freedom. The nominal level c stays GLOBAL per
# split (calib-only); only (q_lo, q_hi) vary by bucket. Buckets, edges, the merge
# decisions and the shrinkage params are all computed on CALIB and frozen; apply reuses
# them (no leakage). Everything else is inherited unchanged from v1.0.


@dataclass(frozen=True)
class MondrianConformalConfig:
    """Knobs for Mondrian conditional conformal (frozen A3 amendment).

    ``c`` is selected on CALIB exactly as v1.0 (global, test-blind). The partition is
    ``n_buckets`` quantile buckets of ``sigma_hat`` (edges via ``numpy.quantile`` with
    ``quantile_method``, frozen on calib; test assigned by ``searchsorted`` on
    ``searchsorted_side``). Buckets below ``min_n_bucket`` are merged into the lower-index
    neighbour deterministically until all survive. Per-bucket quantiles are shrunk toward
    the global pair: ``q_eff = a*q_bucket + (1-a)*q_global``, ``a = n_b/(n_b + n0)``.
    """

    coverage_target: float = 0.80
    band_lo: float = 0.76
    band_hi: float = 0.84
    c_start: float = 0.50
    c_stop: float = 0.96
    c_step: float = 0.005
    sigma_is_variance: bool = True
    method_version: str = "1.2"
    n_buckets: int = 4
    edge_quantiles: tuple[float, ...] = (0.25, 0.50, 0.75)
    quantile_method: str = "linear"
    searchsorted_side: str = "right"
    min_n_bucket: int = 50
    shrinkage_n0: float = 200.0


@dataclass(frozen=True)
class MondrianConformalCalibrator:
    """Fitted Mondrian conformal: one global ``c`` and per-bucket shrunk tail quantiles.

    ``edges`` are the merged interior sigma boundaries frozen from CALIB;
    ``bucket_q_lo``/``bucket_q_hi`` are the effective (shrunk) quantiles for each surviving
    bucket (index = ``searchsorted(edges, sigma, side)``). ``sigma_median``/``sigma_floor``
    are frozen so ``apply`` imputes/floors test sigma identically - nothing leaks back.
    """

    config: MondrianConformalConfig
    c: float
    edges: tuple[float, ...]
    bucket_q_lo: tuple[float, ...]
    bucket_q_hi: tuple[float, ...]
    bucket_n: tuple[int, ...]
    q_lo_global: float
    q_hi_global: float
    sigma_median: float
    sigma_floor: float
    calib_coverage: float
    in_band: bool
    n_calib: int


def _mondrian_edges(sigma: np.ndarray, quantiles: Sequence[float], method: str) -> np.ndarray:
    """Interior bucket boundaries = empirical quantiles of calib ``sigma`` (frozen)."""
    return np.asarray(np.quantile(sigma, list(quantiles), method=method), dtype=float)


def _assign_buckets(sigma: np.ndarray, edges: np.ndarray, side: str) -> np.ndarray:
    """Bucket index in ``[0, len(edges)]`` via ``searchsorted`` on frozen edges."""
    return np.searchsorted(edges, np.asarray(sigma, dtype=float), side=side).astype(int)


def _merge_edges_until_min_n(
    sigma: np.ndarray, edges: np.ndarray, *, min_n: int, side: str
) -> np.ndarray:
    """Drop interior edges until every surviving bucket has ``>= min_n`` calib rows.

    Deterministic: assign rows to the ``len(edges)+1`` buckets; while any bucket is below
    ``min_n``, take the SMALLEST such bucket (lowest index on a count tie) and merge it into
    its adjacent neighbour, PREFERRING the lower-index (left) neighbour - i.e. drop the edge
    on its left if one exists, else the edge on its right. Repeat. With a single bucket left
    (no interior edges) there is nothing to merge and the loop stops; that bucket then holds
    all rows (>= min_n for any non-trivial calib) and A3 reduces exactly to v1.0.
    """
    e = np.asarray(edges, dtype=float).copy()
    while e.size > 0:
        buckets = _assign_buckets(sigma, e, side)
        counts = np.array([int((buckets == b).sum()) for b in range(e.size + 1)])
        below = np.where(counts < min_n)[0]
        if below.size == 0:
            break
        # smallest count among the below-min buckets; lowest index breaks a tie
        b = int(below[np.argmin(counts[below])])
        drop = b - 1 if b > 0 else b  # left edge if a left neighbour exists, else right edge
        e = np.delete(e, drop)
    return e


def _shrunk_bucket_quantiles(
    u: np.ndarray,
    buckets: np.ndarray,
    n_eff_buckets: int,
    *,
    p: float,
    n0: float,
    method: str,
) -> tuple[np.ndarray, float]:
    """Per-bucket quantile of ``u`` at level ``p``, shrunk toward the global quantile.

    Returns ``(q_eff_per_bucket, q_global)`` where
    ``q_eff[b] = a*q_bucket[b] + (1-a)*q_global``, ``a = n_b/(n_b + n0)``. With a single
    bucket ``q_bucket == q_global`` so ``q_eff == q_global`` for any ``a`` (reduces to v1.0).
    """
    q_global = float(np.quantile(u, p, method=method))
    q_eff = np.empty(n_eff_buckets, dtype=float)
    for b in range(n_eff_buckets):
        mask = buckets == b
        n_b = int(mask.sum())
        if n_b == 0:  # should not happen post-merge; shrink fully to global if it does
            q_eff[b] = q_global
            continue
        q_bucket = float(np.quantile(u[mask], p, method=method))
        a = n_b / (n_b + n0)
        q_eff[b] = a * q_bucket + (1.0 - a) * q_global
    return q_eff, q_global


def fit_mondrian_conformal(
    y_true_int: Sequence[int],
    y_pred_dec: Sequence[float],
    sigma_raw: Sequence[float | None],
    *,
    config: MondrianConformalConfig = MondrianConformalConfig(),
) -> MondrianConformalCalibrator:
    """Fit on CALIB: freeze the sigma-bucket partition, then pick global ``c``.

    Pipeline (frozen): ``sigma_hat = sqrt -> impute calib median -> floor -> bucketize``.
    The partition (edges + merge) depends only on ``sigma_hat`` and ``min_n_bucket`` - NOT
    on ``c`` - so it is built once. Then sweep the same ``c`` grid as v1.0; for each ``c``
    the per-bucket tail quantiles are shrunk toward the global pair and the GLOBAL calib
    integer coverage is scored. ``c`` is chosen test-blind by the v1.0 rule (in band
    minimizing ``|cov - target|``; else closest). Deterministic (sorting/quantile only).
    """
    yt = np.asarray(y_true_int, dtype=float)
    yp = np.asarray(y_pred_dec, dtype=float)
    raw = list(sigma_raw)
    if not (yt.size == yp.size == len(raw)):
        raise ValueError(
            f"y_true_int, y_pred_dec, sigma_raw must be same length; "
            f"got {yt.size}, {yp.size}, {len(raw)}"
        )
    if yt.size == 0:
        raise ValueError("cannot fit mondrian conformal on empty data")

    sigma, med, fl = _prepare_sigma(raw, is_variance=config.sigma_is_variance)
    u = (yt - yp) / sigma

    raw_edges = _mondrian_edges(sigma, config.edge_quantiles, config.quantile_method)
    edges = _merge_edges_until_min_n(
        sigma, raw_edges, min_n=config.min_n_bucket, side=config.searchsorted_side
    )
    buckets = _assign_buckets(sigma, edges, config.searchsorted_side)
    n_eff = int(edges.size + 1)
    bucket_n = np.array([int((buckets == b).sum()) for b in range(n_eff)])

    best_in_band: tuple | None = None
    best_in_band_dist = math.inf
    closest: tuple | None = None
    closest_dist = math.inf
    for c in _c_grid_mondrian(config):
        c = float(c)
        p_lo = (1.0 - c) / 2.0
        p_hi = 1.0 - (1.0 - c) / 2.0
        q_lo_eff, q_lo_g = _shrunk_bucket_quantiles(
            u, buckets, n_eff, p=p_lo, n0=config.shrinkage_n0, method=config.quantile_method
        )
        q_hi_eff, q_hi_g = _shrunk_bucket_quantiles(
            u, buckets, n_eff, p=p_hi, n0=config.shrinkage_n0, method=config.quantile_method
        )
        row_q_lo = q_lo_eff[buckets]
        row_q_hi = q_hi_eff[buckets]
        lo_int, hi_int = _normalized_int_interval_vec(yp, sigma, row_q_lo, row_q_hi)
        cov = float(((lo_int <= yt) & (yt <= hi_int)).mean())
        dist = abs(cov - config.coverage_target)
        pack = (c, tuple(q_lo_eff.tolist()), tuple(q_hi_eff.tolist()), q_lo_g, q_hi_g, cov)
        if dist < closest_dist:  # strict -> keeps the FIRST (lowest c) on ties
            closest_dist = dist
            closest = pack
        if config.band_lo <= cov <= config.band_hi and dist < best_in_band_dist:
            best_in_band_dist = dist
            best_in_band = pack

    chosen = best_in_band if best_in_band is not None else closest
    c, q_lo_eff_t, q_hi_eff_t, q_lo_g, q_hi_g, cov = chosen
    return MondrianConformalCalibrator(
        config=config,
        c=c,
        edges=tuple(float(x) for x in edges.tolist()),
        bucket_q_lo=q_lo_eff_t,
        bucket_q_hi=q_hi_eff_t,
        bucket_n=tuple(int(x) for x in bucket_n.tolist()),
        q_lo_global=float(q_lo_g),
        q_hi_global=float(q_hi_g),
        sigma_median=med,
        sigma_floor=fl,
        calib_coverage=cov,
        in_band=best_in_band is not None,
        n_calib=int(yt.size),
    )


def apply_mondrian_conformal(
    cal: MondrianConformalCalibrator,
    y_pred_dec: Sequence[float],
    sigma_raw: Sequence[float | None],
) -> tuple[np.ndarray, np.ndarray]:
    """Emit integer IC80 ``(lo_int, hi_int)`` using the calib-frozen partition + quantiles.

    Test sigma is imputed/floored with the calib median/floor, assigned to a bucket via the
    SAME frozen edges + side, and the bucket's frozen shrunk quantiles are applied. The test
    distribution never re-derives edges, buckets, or quantiles (no leakage).
    """
    yp = np.asarray(y_pred_dec, dtype=float)
    raw = list(sigma_raw)
    if yp.size != len(raw):
        raise ValueError(f"y_pred_dec and sigma_raw must match; got {yp.size}, {len(raw)}")
    sigma, _, _ = _prepare_sigma(
        raw,
        is_variance=cal.config.sigma_is_variance,
        median=cal.sigma_median,
        floor=cal.sigma_floor,
    )
    edges = np.asarray(cal.edges, dtype=float)
    buckets = _assign_buckets(sigma, edges, cal.config.searchsorted_side)
    q_lo = np.asarray(cal.bucket_q_lo, dtype=float)[buckets]
    q_hi = np.asarray(cal.bucket_q_hi, dtype=float)[buckets]
    return _normalized_int_interval_vec(yp, sigma, q_lo, q_hi)


def _normalized_int_interval_vec(
    y_pred_dec: np.ndarray, sigma: np.ndarray, q_lo: np.ndarray, q_hi: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Per-row integer interval with PER-ROW tail quantiles (Mondrian).

    Same endpoint math as the global ``_normalized_int_interval`` but ``q_lo``/``q_hi`` vary
    per row (each row uses its bucket's shrunk quantile). ``hi_int >= lo_int`` enforced.
    """
    lo_int = np.array(
        [Q(float(p + ql * s)) for p, s, ql in zip(y_pred_dec, sigma, q_lo)], dtype=np.int32
    )
    hi_int = np.array(
        [Q(float(p + qh * s)) for p, s, qh in zip(y_pred_dec, sigma, q_hi)], dtype=np.int32
    )
    hi_int = np.maximum(hi_int, lo_int)
    return lo_int, hi_int


def _c_grid_mondrian(config: MondrianConformalConfig) -> np.ndarray:
    """Deterministic nominal-level sweep grid (mirrors the v1.0 ``_c_grid``)."""
    n = int(round((config.c_stop - config.c_start) / config.c_step)) + 1
    return np.round(config.c_start + config.c_step * np.arange(n), 6)


__all__ = [
    "ConformalConfig",
    "IntervalOffsets",
    "ConformalCalibrator",
    "CoverageReport",
    "fit_conformal",
    "interval_dec",
    "apply_conformal",
    "coverage_report",
    "NormalizedConformalConfig",
    "NormalizedConformalCalibrator",
    "fit_normalized_conformal",
    "apply_normalized_conformal",
    "apply_normalized_conformal_qrand",
    "MondrianConformalConfig",
    "MondrianConformalCalibrator",
    "fit_mondrian_conformal",
    "apply_mondrian_conformal",
]
