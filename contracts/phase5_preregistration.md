# Phase 5 pre-registration (criterion_version = 1.0)

> **Frozen 2026-05-30** before running `scripts/phase5_evaluate.py` under the
> conformal METHOD amendment. Authority: code review
> `references/code-reviews/update.txt`, design 8.2/8.3, REQ-MOD-4 / REQ-CONF-1..3 /
> REQ-AUD-5.
>
> This document has TEETH, exactly like the Phase 4 pre-registration.
> `core/eval/preregistration.py::phase5_preregistration_sha256` hashes the canonical
> block delimited by the `<<<PREREG` / `PREREG>>>` markers below. `phase5_evaluate`
> recomputes that hash at runtime and **exits non-zero if it differs from
> `PHASE5_COMMITTED_SHA256`**. Editing anything between the markers WILL fail the
> evaluator until the committed hash is deliberately updated in the same change.

## Why this amendment exists (changelog; not hashed)

- **Object mismatch (the fix).** Phase 5 previously calibrated a DECIMAL conformal
  interval `[pred + lo_off, pred + hi_off]` and then quantized each endpoint with
  `Q`, but the gate evaluates the INTEGER-INCLUSIVE bracket interval
  `[lo_int, hi_int]` that must contain `y_true_int`. Calibrating one object and
  evaluating another breaks the conformal coverage guarantee by construction. The
  diagnose-first run (`reports/phase5_diagnose.json`) measured a +0.056..+0.110
  coverage gap between the decimal and integer objects and confirmed the decimal
  object is sound in-sample (~0.82 on calib).
- **The fix.** Calibrate on the SAME object that is evaluated: normalized
  quantization-aware conformal. Per-row score `u = (y_true_int - y_pred_dec)/sigma_hat`
  with `sigma_hat = sqrt(p50_var)`; asymmetric tail quantiles `q_lo, q_hi`; the
  emitted interval is `[Q(pred + q_lo*sigma), Q(pred + q_hi*sigma)]`. A CONTINUOUS
  nominal-level knob `c` defeats the discrete integer-`w` granularity straddle (a
  global integer half-width could not land in `[0.76, 0.84]` on 2/3 splits), so no
  randomized conformal is required.
- **sigma_hat = p50_var, not nwp_spread.** In the current panel `nwp_spread` is
  effectively constant (diagnostic: `const == nwp_spread`, 2 distinct widths), which
  would degenerate the heteroscedasticity gate. `p50_var` yields 12-21 distinct
  widths (real per-row variation). Changing the sigma proxy later requires a NEW
  pre-registration (it is a new hypothesis), not a silent swap.
- **Honest limitations expected (not gates to massage).** Split 2024 has calib->test
  drift (test decimal coverage 0.896): a correctly calib-tuned method will still
  over-cover on 2024 (non-exchangeability). Split 2023 has a separate confidence-ECE
  problem driven by training scarcity (~21 months; GFS archive floor 2021-03-22),
  tracked separately and NOT bundled into the coverage fix.

The canonical, hashed content is everything between the two markers. Prose outside
the markers (this header, the changelog) is NOT hashed.

<<<PREREG
PHASE5_PREREGISTRATION
criterion_version: 1.0
conformal_method_version: 1.0
q_version: 1.0
frozen_date: 2026-05-30

# --- Seeds (REQ-MOD-6 determinism) ---
seeds:
  python_random: 42
  numpy: 42
threading.omp_num_threads: 1

# --- Fold boundaries (expanding walk-forward; mirrors Phase 4) ---
folds.history_start: 2020-01-01
folds.test_length_days: 365
folds.test_starts: [2023-01-01, 2024-01-01, 2025-01-01]
cp_operational_utc: "23:00"
cp_set_utc: ["20:00", "21:00", "22:00", "23:00"]

# --- Calibration slice (causal tail of each split's train window) ---
calib.per_cp_window_days: 90
calib.seasonal_window_months: 12

# --- Conformal METHOD (the amendment; object = integer-inclusive bracket) ---
conformal.method: normalized_quantization_aware
conformal.center: y_pred_dec
conformal.evaluated_object: integer_inclusive_bracket_contains_y_true_int
conformal.score: u = (y_true_int - y_pred_dec) / sigma_hat
conformal.sigma_proxy: p50_var
conformal.sigma_is_variance: true
conformal.sigma_transform: sqrt
conformal.sigma_missing_impute: calib_median
conformal.sigma_floor: max(calib_median * 1e-3, 1e-6)
conformal.tails: asymmetric
conformal.p_lo: (1 - c) / 2
conformal.p_hi: 1 - (1 - c) / 2
conformal.endpoint_lo: Q(y_pred_dec + q_lo * sigma_hat)
conformal.endpoint_hi: Q(y_pred_dec + q_hi * sigma_hat)
conformal.hi_ge_lo: true
conformal.Q: floor(x + 0.5)

# --- Nominal-level c selection (CALIB ONLY; test is readout only) ---
c_select.grid_start: 0.50
c_select.grid_stop: 0.96
c_select.grid_step: 0.005
c_select.rule: pick c with calib integer coverage in [band_lo, band_hi] minimizing |coverage - target|
c_select.fallback: if none in band, pick c minimizing |coverage - target| (closest to target)
c_select.tie_break: lowest c (narrowest) wins on equal distance
c_select.test_blind: true

# --- Frozen gate thresholds (NOT loosened after results) ---
gate.coverage_target: 0.80
gate.coverage_tol: 0.04
gate.coverage_band: [0.76, 0.84]
gate.heterosced_coverage_low: 0.70
gate.heterosced_coverage_high: 0.90
gate.heterosced_n_bins: 4
gate.ece_tol: 0.05
gate.min_confidence_default: 0.55

# --- Verdict ---
verdict.phase5_ready_requires: [coverage_within_tol_all_splits, heteroscedasticity_passed_all_splits, confidence_ece_within_tol]
verdict.no_threshold_loosening_after_results: true
verdict.no_window_retuning_after_results: true
verdict.no_sigma_swap_to_pass: true

# --- Honest-limitation tracks (reported, not patched) ---
track.drift_2024: separate_prereg_required (seasonal/Mondrian redesign is a new hypothesis)
track.ece_2023: separate (scarcity-driven; regularization/pooling/accept, not bundled)
PREREG>>>

## Rationale (not hashed)

- **Why calibrate on the integer object.** The conformal coverage guarantee holds for
  the nonconformity score that is calibrated. Since the gate scores integer-inclusive
  containment, the calibrated object must be the integer bracket interval. The decimal
  calibrate-then-quantize path is provably miscalibrated for this gate.
- **Why a continuous c instead of an integer half-width.** A single global integer `w`
  jumps coverage in large steps (e.g. ~0.74 -> ~0.88) that straddle `[0.76, 0.84]`.
  The continuous `c` plus per-row `sigma_hat` scaling recovers fine effective
  resolution, so the band is attainable on calib without randomized conformal.
- **Why this is not gaming.** Object-matching is the correct calibration target a
  priori (derivable before seeing whether the gate passes); `c` is chosen on calib
  only; the run is executed once; the gate thresholds are untouched. The honest
  expected outcome is "object mismatch fixed; 2024 fails on drift; 2023 ECE is
  scarcity; Phase 5 not ready (2/3) under the current design."
