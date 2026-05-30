# Phase 5 amendment - Track A.A1: sigma winsorization (conformal_method_version 1.1)

> **Status: PROPOSED (not yet executed).** Per `references/code-reviews/update.txt`
> section 5, a track must not START without explicit approval. This document is the
> required pre-registration artifact (section 4) produced BEFORE code. The hashed
> block below is frozen for tamper-evidence; wiring it into
> `core/eval/preregistration.py` and running `phase5_evaluate` ONCE happens only after
> approval.
>
> Canonical PREREG sha256 (to be pinned as `PHASE5A_COMMITTED_SHA256` at wiring time):
> `ea5b279a70c9b889158c10a867a35a6b49b7859402fa01661cd082b0a6e39c09`

## Hypothesis name

`trackA_a1_sigma_winsor` - tame the heavy `sigma_hat` tail (and the sub-floor spike)
by winsorizing `sigma_hat` to a calib-frozen percentile band, to reduce wide-width-bin
over-coverage WITHOUT changing any gate, the sigma proxy, the splits, or the windows.

## Evidence that motivates exactly this change (read-only diagnostics)

From `reports/phase5_hetero_diagnose.md` (no model/gate touched):

- `sigma_hat = sqrt(p50_var)` is spiked + heavy-tailed: `p25 == p50 == p75 ~= 0.10`
  (about 75% of mass at one value), then `p95 ~= 0.32`, `p99 ~= 0.6`, `max ~= 1.0-1.2`
  (tail ratio `p99/p50 ~= 5-7x`).
- Interval width does NOT track realized error: Pearson `0.05-0.11`, Spearman
  `0.01-0.10` (i.e. ~0).
- Over-coverage is monotone in width and is pure slack. Widest test quartile:
  coverage `1.000`, mean width `10.8-18.7` brackets, mean `|error_int|` `1.0-1.6`,
  `slack = mean_width - (2*mean|e| + 1) = 6.5-14.4` brackets.

Mechanism (derivable a priori from the spike): the normalized score
`u = (y_true_int - y_pred_dec)/sigma_hat` is dominated by the tiny-`sigma` rows, which
inflate the tail quantiles `q_lo, q_hi` (~+/-9). Applied to the minority of large-`sigma`
rows, width `~= (q_hi - q_lo)*sigma` explodes while their realized error stays ~1-2.
Two inflation sources: (a) the sub-floor `sigma` spike inflates `q`; (b) the upper
`sigma` tail inflates the APPLIED width. A1 attacks BOTH by winsorizing `sigma_hat`.

## What changes

- A single new step in the normalized conformal, applied identically in fit and apply:
  after `sigma_hat = sqrt(p50_var)` is imputed (calib median) and floored, it is
  WINSORIZED to `[clip_lo, clip_hi]`, where `clip_lo = percentile(calib sigma_hat, 25)`
  and `clip_hi = percentile(calib sigma_hat, 95)`.
- The clip bounds are computed on CALIB ONLY at fit time and FROZEN onto the
  calibrator; `apply` (test/eval) reuses the same two numbers. No test statistic flows
  back to calib.
- `conformal_method_version` bumps `1.0 -> 1.1`. A new pre-registration hash pins this
  amendment block.
- Winsorized `sigma_hat` is used in BOTH the score `u` (so tiny-`sigma` rows stop
  inflating `q`) and the emitted interval (so large-`sigma` rows stop inflating width).

## What does NOT change

- Coverage gate: target `0.80`, tol `0.04`, band `[0.76, 0.84]`. Untouched.
- Heteroscedasticity gate: per-width-quartile coverage in `[0.70, 0.90]`, 4 bins.
  Untouched (this is the bar we are trying to MEET, not move).
- ECE gate `0.05`. Untouched.
- Sigma PROXY stays `p50_var` (sqrt to stddev). Winsorization RESHAPES the same proxy;
  it does not swap it. Swapping the proxy is a separate, separately-pre-registered
  question (the near-zero width/error correlation hints at it, but it is OUT of scope
  here - one hypothesis per change-set).
- Splits (2023/2024/2025, 365 d), calib windows (per-CP 90 d, seasonal 12 m),
  `c`-selection rule + grid, `Q(x)=floor(x+0.5)`, seeds, determinism. Untouched.

## Acceptance criteria (pre-registered; evaluated once)

1. Wide-bin over-coverage is REDUCED on calib (the widest width-quartile coverage moves
   down toward `[0.70, 0.90]` versus v1.0) while global calib coverage stays near target
   (in `[0.76, 0.84]`).
2. Widths remain NON-DEGENERATE (>= 3 distinct integer widths on calib AND test).

Note: the binding pass/fail for "Phase 5 ready" is still the unchanged het gate on
TEST, reported per split, never pooled.

## Kill criteria (pre-registered; reject the hypothesis if hit)

- If wide-bin behavior improves ONLY by collapsing widths to degenerate (`< 3` distinct
  widths, or width std collapses to ~0), REJECT - this is sharpness destruction, not
  calibration.
- If global calib coverage leaves `[0.76, 0.84]` (the winsorization broke marginal
  coverage), REJECT.
- No re-tuning of `[25, 95]` after seeing the result. If A1 fails on its honest terms,
  the next step is a DIFFERENT pre-registered hypothesis (A2 transform or A3 Mondrian),
  not new percentiles.

## Expected failure modes (honest; stated before the run)

- The narrowest quartile is already marginal (2025 bin1 test coverage `0.783`, near the
  `0.70` floor). Raising the floor (`clip_lo = P25`) narrows bin1 and MAY push it under
  `0.70` - trading a wide-bin failure for a narrow-bin failure. If so, that is a real
  result, reported, not patched.
- Width vs error correlation is ~0, so winsorization treats the tail symptom; it may
  reduce but not eliminate mid-bin over-coverage. A1 is the simplest in-scope hypothesis,
  tried first by design; partial success is an acceptable, informative outcome that
  motivates A3 next.

## Silent-bug checklist (section 6) commitments for the implementation

- Clip bounds frozen on calib; test reuses them (no leakage), mirrored by a unit test.
- `numpy.percentile` deterministic; integer conversion stays `int32`; `hi_int >= lo_int`.
- Missing `p50_var` already imputed+logged upstream; winsorization does not hide it.

The canonical, hashed content is everything between the two markers. Prose outside the
markers (this header and rationale) is NOT hashed.

<<<PREREG
PHASE5_AMENDMENT_TRACK_A_A1
criterion_version: 1.0
amends: phase5_preregistration.md (criterion_version 1.0)
conformal_method_version: 1.1
q_version: 1.0
frozen_date: 2026-05-30

# --- Hypothesis (exactly one) ---
hypothesis.id: trackA_a1_sigma_winsor
hypothesis.scope: heteroscedasticity_only
hypothesis.changes_gate: false
hypothesis.changes_sigma_proxy: false
hypothesis.changes_windows: false

# --- The single method change: winsorize sigma_hat ---
sigma.proxy: p50_var
sigma.is_variance: true
sigma.transform: sqrt
sigma.missing_impute: calib_median
sigma.floor: max(calib_median * 1e-3, 1e-6)
sigma.winsorize: true
sigma.winsorize_clip_lo_pctl: 25
sigma.winsorize_clip_hi_pctl: 95
sigma.winsorize_basis: calib_only
sigma.winsorize_applied_in: [score_u, emitted_interval]
sigma.winsorize_test_reuses_calib_bounds: true

# --- Everything below is INHERITED UNCHANGED from phase5 v1.0 ---
conformal.method: normalized_quantization_aware
conformal.center: y_pred_dec
conformal.evaluated_object: integer_inclusive_bracket_contains_y_true_int
conformal.score: u = (y_true_int - y_pred_dec) / sigma_hat_winsorized
conformal.tails: asymmetric
conformal.p_lo: (1 - c) / 2
conformal.p_hi: 1 - (1 - c) / 2
conformal.endpoint_lo: Q(y_pred_dec + q_lo * sigma_hat_winsorized)
conformal.endpoint_hi: Q(y_pred_dec + q_hi * sigma_hat_winsorized)
conformal.hi_ge_lo: true
conformal.Q: floor(x + 0.5)
c_select.grid_start: 0.50
c_select.grid_stop: 0.96
c_select.grid_step: 0.005
c_select.rule: pick c with calib integer coverage in [band_lo, band_hi] minimizing |coverage - target|
c_select.fallback: if none in band, pick c minimizing |coverage - target|
c_select.tie_break: lowest c wins on equal distance
c_select.test_blind: true

# --- Frozen gate thresholds (NOT loosened; identical to v1.0) ---
gate.coverage_target: 0.80
gate.coverage_tol: 0.04
gate.coverage_band: [0.76, 0.84]
gate.heterosced_coverage_low: 0.70
gate.heterosced_coverage_high: 0.90
gate.heterosced_n_bins: 4
gate.ece_tol: 0.05

# --- Acceptance / kill (pre-registered) ---
accept.reduce_wide_bin_overcoverage_on_calib: true
accept.global_calib_coverage_in_band: true
accept.widths_non_degenerate_min_distinct: 3
kill.reject_if_widths_degenerate: true
kill.reject_if_global_calib_coverage_out_of_band: true
kill.no_percentile_retuning_after_results: true

# --- Run discipline ---
run.execute_phase5_evaluate_times: 1
run.test_is_readout_only: true
PREREG>>>

## Rationale (not hashed)

- **Why winsorize both ends.** The diagnostics show two distinct inflation sources: a
  sub-floor `sigma` spike that inflates the shared quantile `q`, and an upper `sigma`
  tail that inflates the applied width. A one-sided cap (e.g. `[p01, p99]`) would tame
  only the upper width and leave `q` inflated by the near-zero `sigma` rows. `[P25, P95]`
  raises the floor enough to stop the `q` inflation and caps the tail width, which is the
  minimal symmetric change consistent with the measured mechanism.
- **Why not swap the proxy now.** The ~0 width/error correlation suggests `p50_var` is a
  weak difficulty signal, but swapping it is a different hypothesis and the process
  mandates one hypothesis per change-set. A1 is the simplest in-scope move; its honest
  partial-success/failure informs whether A3 (Mondrian by sigma-bucket) is warranted.
- **Why this is not gaming.** The clip rule is fixed ex-ante and derived from the
  mechanism a priori; the percentiles are not tuned to the gate; `c` is calib-only; the
  run is once; the gate thresholds are untouched; kill criteria are pre-committed.
