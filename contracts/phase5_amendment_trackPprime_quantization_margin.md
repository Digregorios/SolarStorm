# Phase 5 amendment - Track P': quantization margin (distance-to-threshold) as the difficulty axis (conformal_method_version 1.4)

> **Status: APPROVED for Passo 3 (wire + tests + sanity + one-shot).** Per
> `references/code-reviews/update.txt` (2026-05-30) the reviewer (A) directed opening Track P'
> BEFORE Track D as a new docs-before-code difficulty-axis change with a single frozen proxy =
> the **distance-to-threshold / quantization margin** registered below; (B) confirmed sanity
> check (3) (22Z/23Z focus Spearman `>= 0.10`) STAYS BINDING at the same floor; (C) required
> ONE read-only auditability add (no threshold change): the sanity report must emit `n_subset`,
> `abs_error_int` tie diagnostics, and an AUXILIARY non-binding Kendall tau-b on the focus
> subset; and (D) authorized Passo 3 - wire `PHASE5PP_COMMITTED_SHA256` +
> `assert_phase5pp_preregistration_committed()` + unit tests in the SAME change-set, run sanity
> (1)(2)(3) calib-only, and ONLY if all pass run `phase5_evaluate` EXACTLY ONCE; if any sanity
> check fails, register "proxy rejected" and STOP (no re-tuning).
>
> Canonical PREREG sha256 (pinned as `PHASE5PP_COMMITTED_SHA256` at wiring time):
> `e4fb58abb8ce63b67527ba4b906c6ab783506220e27c75023a91cc63db07c4e4`

## Hypothesis name

`trackPprime_quantization_margin_sigma` - the REQ-AUD-5 bottleneck is in the DIFFICULTY AXIS
in the late-CP regime, and Track P proved the model's OWN emitted distribution carries no
usable difficulty signal there (entropy did not rank-order `|error_int|`; Spearman
`0.0414 / 0.0663 / 0.0049`, all below the `0.10` floor). Track P' replaces `sigma_hat` with a
proxy tied DIRECTLY to the discrete object being evaluated: the rounding `Q(x) = floor(x +
0.5)` is maximally unstable when the decimal forecast sits near a `.5` boundary, so the
distance of `y_pred_dec` to that boundary is a candidate difficulty axis that does not depend
on the (flattened) `prob_dist` at all.

## Framing (read this before the method)

- This is a **difficulty-axis change, NOT a spike fix and NOT a tuning of Track P.** Exactly
  one variable moves: the definition of `sigma_hat`. Track P (entropy) is rejected and closed;
  this is a SEPARATE branch off the v1.0 baseline, not a tweak to entropy's definition, floor,
  or sanity threshold.
- **Why distance-to-threshold, and why now (reviewer rationale).** The reviewer chose this
  over Track D (randomized / smoothed discrete object) because the Passo 1 audit localizes the
  binding over-coverage to the moderately-wide, large-`n` bin (`n` = 98/127/161) - a real
  operational regime (late CP 22:00Z/23:00Z), with no evidence of an INEVITABLE discrete-object
  straddle that only RNG could fix. The diagnosis is "the difficulty axis is not ordering
  error", so the principled next move is a better axis, not a bigger, harder-to-audit change.
  Track D remains the fallback only after one or two honest P' rejections, or if a P' passes
  sanity yet the het gate still fails in a way that implies inevitable straddle.
- **Why this axis specifically.** `Q(x) = floor(x + 0.5)` flips the emitted integer as
  `y_pred_dec` crosses a half-integer, so the integer prediction is least stable - and the
  realized integer error is plausibly largest - exactly when `frac(y_pred_dec)` is near `0.5`.
  This couples the difficulty axis to the integer-inclusive bracket object the gate evaluates,
  with no RNG and no dependence on the predictive distribution.

## What changes (exactly one hypothesis)

The single method change is the definition of `sigma_hat`. NOTHING else moves.

- BEFORE (v1.0 / A1 / A3 baseline): `sigma_hat = sqrt(p50_var)`, imputed by calib median,
  floored. (Track P used `sigma_hat = entropy(prob_dist)`; rejected.)
- AFTER (Track P'): `sigma_hat = quantization margin instability` of the per-row decimal
  forecast `y_pred_dec`:
  - `frac = y_pred_dec - floor(y_pred_dec)` (the fractional part, in `[0, 1)`);
  - `margin = abs(frac - 0.5)` (distance to the `.5` rounding boundary, in `[0, 0.5]`;
    `0` = exactly on the boundary, `0.5` = exactly on an integer);
  - `sigma_hat = 0.5 - margin` (in `[0, 0.5]`; LARGER = closer to the boundary = harder).
  The orientation is deliberately the "uncertainty grows near the threshold" form (the
  reviewer's parenthetical alternative), because in the normalized score
  `u = (y_true_int - y_pred_dec) / sigma_hat` a difficulty axis must be LARGER on harder rows
  for the learned tail quantiles to widen the right intervals. The positive-sign monotonicity
  sanity check below is what enforces (and could falsify) this orientation.
- `sigma_hat` is ALWAYS defined (a deterministic function of `y_pred_dec` alone; no NULL/impute
  branch); it is floored at a calib-frozen `sigma_floor` (P1) for numerical safety, which here
  also caps the `sigma_hat -> 0` rows far from the boundary so the score `u` cannot blow up.
- It is LABEL-INVARIANT in the same sense the reviewer required of Track P: it depends only on
  the fractional part of the forecast, not on which integer the support sits near, so it does
  not saturate or shift merely because the center/support moves between CPs.
- The conformal score form, the asymmetric tails, the GLOBAL `(q_lo, q_hi)`, the `c`-selection
  rule + grid, `Q(x) = floor(x + 0.5)`, and the interval endpoints are the v1.0 method - just
  evaluated with the new `sigma_hat`. There is NO Mondrian, NO winsorization, NO per-bucket
  conditioning, NO randomization.
- `conformal_method_version` bumps `1.0 -> 1.4`. (A1 = `1.1`, A3 = `1.2`, Track P = `1.3`;
  Track P' is a SEPARATE branch off the v1.0 baseline and is `1.4`.)

### Determinism / causality of the new proxy (frozen, pre-registered)

- `y_pred_dec` is the model's emitted decimal forecast for that row, built causally upstream;
  its fractional part introduces NO future information - it is a deterministic function of the
  same per-row forecast already emitted.
- `sigma_floor` is computed on CALIB ONLY (P1 of calib `sigma_hat`) and FROZEN; test reuses the
  frozen floor. The test distribution never influences the floor.
- No RNG anywhere; same calib input -> identical `sigma_floor`, identical scores, identical
  `c`, identical intervals.

### MANDATORY read-only sigma-hat sanity checks (BEFORE the one-shot; calib-only, binding)

These are axis SANITY checks, not tuning. They run read-only on CALIB ONLY and MUST pass
before the single `phase5_evaluate` run is permitted. If any fails, the one-shot is NOT
executed and Track P' is rejected in favour of a DIFFERENT pre-registered proxy (or Track D).

1. **Monotonicity vs the difficulty label (global, per split).** Compute
   `abs_error_int = |y_true_int - Q(y_pred_dec)|` on calib, and require the Spearman rank
   correlation `rho(sigma_hat, abs_error_int)` on calib, PER SPLIT, to be POSITIVE and
   `>= sanity.monotonicity_min_rho`. A difficulty axis that does not rank-order the model's own
   integer error is not a difficulty axis.
2. **No per-CP collapse.** For each CP (and explicitly for 22:00 and 23:00, the regime where
   the over-coverage lives), the calib `sigma_hat` distribution must have
   `>= sanity.by_cp_min_distinct` distinct values.
3. **Monotonicity IN the bottleneck regime (focus, per split).** The reviewer's optional-but-
   recommended check, adopted here as BINDING: restrict to the 22:00 + 23:00 calib rows and
   require `rho(sigma_hat, abs_error_int)` on that subset, PER SPLIT, to be POSITIVE and
   `>= sanity.focus_monotonicity_min_rho`. Rationale (reviewer): "Se o proxy nao ordena
   dificuldade no regime onde o problema vive, ele nao serve." The focus threshold is set EQUAL
   to the global floor (`0.10`); the reviewer confirmed (update.txt 2026-05-30) it STAYS binding
   at `0.10`.

### Read-only auditability of the focus check (reviewer-required; NOT pass/fail)

To interpret a focus-check failure correctly (and avoid a false negative driven by weak
statistics on a small, tie-heavy subset), the sanity report MUST additionally emit, for the
22:00 + 23:00 calib subset, PER SPLIT - WITHOUT changing any threshold or the pass/fail logic:

- `n_subset`: the number of calib rows in `{22:00, 23:00}`.
- tie diagnostics on `abs_error_int`: the count of DISTINCT `|error_int|` values in the subset
  (the integer error is heavily tied at `0`, which can make Spearman unstable).
- `kendall_tau_b(sigma_hat, abs_error_int)` on the subset as an AUXILIARY, READ-ONLY,
  NON-BINDING metric. tau-b is tie-corrected and more stable than Spearman under heavy ties, so
  it explains a borderline Spearman; it NEVER overrides the binding Spearman pass/fail. The
  pass/fail decision is the Spearman `>= 0.10` of check (3) and nothing else.

The sanity thresholds are frozen in the hashed block; they are NOT re-tuned after looking. A
failed sanity check is an honest, informative reject of THIS proxy (open a new one), never a
reason to relax the threshold.

## What does NOT change

- Coverage gate: target `0.80`, tol `0.04`, band `[0.76, 0.84]`. Untouched.
- Heteroscedasticity gate: per-width-quartile coverage in `[0.70, 0.90]`, 4 bins, per split,
  never pooled. Untouched (the bar Track P' is trying to MEET, not move).
- ECE gate `0.05`. Untouched (ECE is Track C; not bundled here).
- The het-gate width binning (rank-quantiles over distinct widths) - the frozen normative
  definition in `docs/req_aud5_normative.md`. Untouched.
- Splits (2023/2024/2025, 365 d), calib windows (per-CP 90 d), `c`-selection rule + grid,
  `Q(x) = floor(x + 0.5)`, seeds, determinism. Untouched.
- The conformal method family (normalized quantization-aware, GLOBAL asymmetric tails).
  Only the `sigma_hat` input changes.

## Acceptance criteria (pre-registered; evaluated once)

0. (Pre-condition) ALL THREE MANDATORY sanity checks above PASS on calib, per split. If not,
   the one-shot is not run.
1. The heteroscedasticity gate PASSES per split on TEST (every width-quartile coverage in
   `[0.70, 0.90]`) - the binding bar.
2. Global calib coverage stays in `[0.76, 0.84]`.
3. Widths remain NON-DEGENERATE (`>= 3` distinct integer widths on calib AND test).

## Kill criteria (pre-registered; reject the hypothesis if hit)

- If a MANDATORY sanity check fails, REJECT (do not run the one-shot) - the proxy does not
  carry difficulty signal in the relevant regime.
- If widths collapse to degenerate (`< 3` distinct widths, or width std `~ 0`), REJECT -
  sharpness destruction, not calibration.
- If global calib coverage leaves `[0.76, 0.84]`, REJECT.
- No re-tuning of the margin definition / orientation, the floor percentile, the sanity
  thresholds, or the `c`-rule after seeing the result. If Track P' fails on its honest terms,
  the next step is a DIFFERENT pre-registered hypothesis (a second P', e.g. `1 - max_prob`, or
  Track D), not a tweak to this one.

## Expected failure modes (honest; stated before the run)

- **The forecasts may cluster away from `.5`.** If the model systematically emits near-integer
  (or near-half) decimals, `sigma_hat = 0.5 - |frac - 0.5|` could be near-constant within a CP,
  failing the per-CP distinct check - informative: the rounding boundary is not exercised.
- **Margin may not rank error.** Integer error can be driven by model BIAS (a shifted center)
  rather than rounding instability, in which case `rho(sigma_hat, |error_int|)` is near zero or
  negative and the monotonicity check fails - the honest, pre-one-shot reject, exactly as for
  Track P.
- **Global-but-not-focus.** The axis could order error globally yet NOT inside the 22:00/23:00
  regime where the gate fails; the focus check (3) is designed to catch precisely this and
  reject before spending the one-shot.
- **Flooring compresses the easy tail.** Rows far from the boundary have `sigma_hat -> 0` and
  are lifted to the P1 floor; this is numerical safety, not tuning, and is frozen on calib.
- `abs_error_int` is integer-valued with heavy ties at `0`; Spearman is tie-corrected
  (average ranks), so the ties are handled honestly rather than dropped.

## Minimal test checklist (to add in the SAME change-set that wires + runs Track P')

Per `references/code-reviews/update.txt` ("testes unitarios: no-leak, determinismo, sanity"):

- **no-leak:** `sigma_floor` and the sanity thresholds are computed/declared on calib ONLY and
  frozen; `apply` on a test set whose `sigma_hat` distribution differs reuses the SAME frozen
  floor and the SAME global `(q_lo, q_hi)`; test never re-estimates the floor or the quantiles,
  and the sanity checks never touch test.
- **determinism:** same calib input -> identical `sigma_floor`, identical Spearman rho (global
  and focus), identical `c`, identical emitted intervals (re-run equality).
- **margin closed-form:** `margin = |frac - 0.5|` and `sigma_hat = 0.5 - margin` match the
  closed form on hand-checked decimals (incl. the corners: `frac = 0.5 -> sigma_hat = 0.5`,
  `frac = 0.0 -> sigma_hat = 0.0`, `frac -> 1.0 -> sigma_hat -> 0.0`); label-invariance under
  an integer shift of `y_pred_dec`; `sigma_hat >= sigma_floor` after flooring.
- **sanity (unit-level):** the global and focus monotonicity helpers return known Spearman
  values on constructed monotone fixtures; the per-CP distinct-count helper detects a
  constructed collapsed-CP fixture; a missing focus CP fails.
- **reduction sanity:** with `sigma_hat` forced constant the method reduces to a fixed-width
  global interval and the degenerate-proxy / collapsed sanity path is reachable and detected.

The canonical, hashed content is everything between the two markers. Prose outside the markers
(this header and rationale) is NOT hashed.

<<<PREREG
PHASE5_AMENDMENT_TRACK_P_PRIME
criterion_version: 1.0
amends: phase5_preregistration.md (criterion_version 1.0)
conformal_method_version: 1.4
q_version: 1.0
frozen_date: 2026-05-30

# --- Hypothesis (exactly one) ---
hypothesis.id: trackPprime_quantization_margin_sigma
hypothesis.scope: difficulty_axis_only
hypothesis.framing: difficulty_axis_change_not_spike_fix
hypothesis.branch_off: phase5_v1.0_baseline
hypothesis.supersedes_trackP: false
hypothesis.changes_gate: false
hypothesis.changes_sigma_proxy: true
hypothesis.changes_windows: false
hypothesis.includes_winsorization: false
hypothesis.includes_mondrian: false
hypothesis.includes_entropy: false
hypothesis.includes_randomization: false

# --- The single method change: sigma_hat = quantization margin instability ---
sigma.proxy_before: sqrt(p50_var)
sigma.proxy_after: quantization_margin(y_pred_dec)
sigma.frac_definition: frac = y_pred_dec - floor(y_pred_dec)
sigma.margin_definition: margin = abs(frac - 0.5)
sigma.sigma_hat_formula: sigma_hat = 0.5 - margin
sigma.sigma_hat_range: [0.0, 0.5]
sigma.orientation: larger_sigma_hat_is_closer_to_rounding_threshold_harder
sigma.depends_on: y_pred_dec_only
sigma.label_invariant: true
sigma.always_defined: true
sigma.impute_required: false
sigma.floor_basis: calib_only
sigma.floor_percentile: 1
sigma.floor_frozen_on_calib: true
sigma.is_variance: false
sigma.uses_rng: false

# --- MANDATORY read-only sigma sanity checks (calib-only; BEFORE the one-shot) ---
sanity.required_before_oneshot: true
sanity.basis: calib_only_per_split
sanity.difficulty_label: abs_error_int = |y_true_int - Q(y_pred_dec)|
sanity.monotonicity_metric: spearman_rho(sigma_hat, abs_error_int)
sanity.monotonicity_sign_must_be_positive: true
sanity.monotonicity_min_rho: 0.10
sanity.by_cp_distribution_check: true
sanity.by_cp_focus: ["22:00", "23:00"]
sanity.by_cp_min_distinct: 3
sanity.focus_monotonicity_check: true
sanity.focus_monotonicity_subset: cp_in_22_00_or_23_00
sanity.focus_monotonicity_metric: spearman_rho(sigma_hat, abs_error_int) on focus subset
sanity.focus_monotonicity_sign_must_be_positive: true
sanity.focus_monotonicity_min_rho: 0.10
# --- Read-only auditability of the focus subset (reviewer-required; NOT pass/fail) ---
sanity.focus_report_n_subset: true
sanity.focus_report_tie_diagnostics_abs_error_int: distinct_value_count
sanity.focus_auxiliary_metric: kendall_tau_b(sigma_hat, abs_error_int) on focus subset
sanity.focus_auxiliary_metric_binding: false
sanity.failure_action: do_not_run_oneshot_reject_and_open_new_hypothesis
sanity.thresholds_frozen: true

# --- Everything below is INHERITED UNCHANGED from phase5 v1.0 ---
conformal.method: normalized_quantization_aware
conformal.center: y_pred_dec
conformal.evaluated_object: integer_inclusive_bracket_contains_y_true_int
conformal.score: u = (y_true_int - y_pred_dec) / sigma_hat
conformal.tails: asymmetric
conformal.q_is_global: true
conformal.p_lo: (1 - c) / 2
conformal.p_hi: 1 - (1 - c) / 2
conformal.endpoint_lo: Q(y_pred_dec + q_lo * sigma_hat)
conformal.endpoint_hi: Q(y_pred_dec + q_hi * sigma_hat)
conformal.hi_ge_lo: true
conformal.Q: floor(x + 0.5)
conformal.quantile_method: linear
c_select.grid_start: 0.50
c_select.grid_stop: 0.96
c_select.grid_step: 0.005
c_select.rule: pick c with GLOBAL calib integer coverage in [band_lo, band_hi] minimizing |coverage - target|
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
accept.sanity_checks_pass_per_split: true
accept.heterosced_gate_passes_per_split_on_test: true
accept.global_calib_coverage_in_band: true
accept.widths_non_degenerate_min_distinct: 3
kill.reject_if_sanity_fails: true
kill.reject_if_widths_degenerate: true
kill.reject_if_global_calib_coverage_out_of_band: true
kill.no_param_retuning_after_results: true

# --- Run discipline ---
run.sanity_before_oneshot: true
run.execute_phase5_evaluate_times: 1
run.test_is_readout_only: true
PREREG>>>

## Rationale (not hashed)

- **Why a second proxy (P') before Track D.** The reviewer directed this explicitly: the
  bottleneck is a real operational regime (late CP, large `n`), the diagnosis is "the axis is
  not ordering error", and a better axis is a smaller, more auditable change than randomizing
  the discrete object. Track D stays the fallback after one or two honest P' rejections, or if
  a P' passes sanity yet the het gate still fails in a straddle-implying way.
- **Why the quantization margin.** It is the axis most directly coupled to the evaluated
  object: `Q(x) = floor(x + 0.5)` is least stable near a `.5` boundary, so distance to that
  boundary is a principled difficulty signal - RNG-free, always defined, causal, and
  independent of the flattened `prob_dist` that sank Track P.
- **Why the orientation `0.5 - margin`.** `sigma_hat` is a SCALE in `u = residual / sigma_hat`;
  it must be larger on harder rows. The reviewer offered both signs; the harder-near-threshold
  sign is the only one consistent with a difficulty scale, and the positive-sign monotonicity
  sanity check is the pre-committed test that can falsify it.
- **On the focus monotonicity check (3).** The reviewer marked this OPTIONAL but "muito util",
  then confirmed (update.txt 2026-05-30) it STAYS BINDING at the global `0.10` floor, for two
  reasons: the REQ-AUD-5 bottleneck is concentrated in the late CPs (22Z/23Z), so passing the
  global check does not guarantee usefulness where it matters; and the anti-gaming discipline is
  stronger - if (3) fails on small-`n`/ties that is a REAL signal the proxy lacks operational
  resolution in the critical regime, and it avoids spending the one-shot. The reviewer's only
  added requirement (no threshold change) is auditability: the sanity report emits `n_subset`,
  the `abs_error_int` tie diagnostics, and an auxiliary read-only Kendall tau-b on the focus
  subset, purely to interpret a borderline/failed Spearman - never to override pass/fail.
- **Why this is not gaming.** Exactly one variable changes (`sigma_hat`); the margin
  definition, orientation, floor percentile, all three sanity thresholds, the `c`-rule, and
  every gate threshold are fixed ex-ante and hashed; nothing is tuned to the gate; the floor
  and sanity checks are calib-only; the run is once; kill criteria (including "the new proxy
  fails its sanity checks") are pre-committed.
- **Alternatives considered (and why not now).** `1 - max_prob` (the reviewer's second choice;
  stable but still distribution-derived and may be flat in late CP - kept as the next P' if
  this one is rejected); raw `std(prob_dist)` and `entropy(prob_dist)` (the reviewer advised
  against both given the Track P result); Track D randomized/smoothed discrete object (a larger,
  harder-to-audit change held as the fallback per update.txt). Each remains available as a
  separate future pre-registered hypothesis if Track P' is rejected.
