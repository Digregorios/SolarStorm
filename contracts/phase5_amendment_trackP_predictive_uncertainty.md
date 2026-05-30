# Phase 5 amendment - Track P: predictive-distribution uncertainty as the difficulty axis (conformal_method_version 1.3)

> **Status: PROPOSED (not yet wired, not yet executed).** Per
> `references/code-reviews/update.txt` the reviewer reviewed the read-only REQ-AUD-5 audit
> (`reports/phase5_wide_bin_audit.md`, Passo 1) and explicitly cleared opening Track P as a
> PROPOSED, docs-before-code proxy / difficulty-axis change, with two binding adjustments
> folded in below: (A) frame this as a DIFFICULTY-AXIS change, not a "spike fix"; (B) use a
> discrete-stable `uncertainty(prob_dist)` (a single frozen definition) rather than raw
> `std`, AND include MANDATORY read-only sanity checks of the new `sigma_hat` BEFORE the
> one-shot. Wiring it into `core/eval/preregistration.py`
> (`PHASE5P_COMMITTED_SHA256` + `assert_phase5p_preregistration_committed()`), adding the
> unit tests, and running `phase5_evaluate` ONCE happen only in a later, separate change-set
> AFTER explicit reviewer approval (update.txt Passo 3).
>
> Canonical PREREG sha256 (to be pinned as `PHASE5P_COMMITTED_SHA256` at wiring time):
> `215c29d34d582cf619d2766e69b5e55cb9c452a68e89e1613619d71aef759b85`

## Hypothesis name

`trackP_predictive_uncertainty_sigma` - the REQ-AUD-5 bottleneck is in the DIFFICULTY AXIS
in the late-CP regime: the current `sigma_hat = sqrt(p50_var)` does not ORDER difficulty
where the over-coverage lives (the 22Z/23Z rows), so the residual score
`u = (y_true_int - y_pred_dec)/sigma_hat` stays heteroscedastic. Replacing `sigma_hat` with
a fine, discrete-stable uncertainty measure of the model's OWN emitted predictive
distribution (`sigma_hat = uncertainty(prob_dist)`) may align width with difficulty and
reduce the structural over-coverage in bin 1 (the mod-wide bin) WITHOUT any RNG, while
keeping a single global tail-quantile pair.

## Framing (reviewer-adjusted; read this before the method)

- This is a **difficulty-axis change, NOT a spike fix.** The defect is that the current
  proxy fails to rank difficulty in the relevant regime (late CP). That can hold even
  WITHOUT a `p50_var` spike (a proxy can be simply wrong for a regime), so the hypothesis is
  framed around "wrong axis for the late-CP regime", not "the proxy spikes".
- **Why not raw `std(prob_dist)`.** In a discrete distribution `std` can saturate or become
  anti-informative exactly when the support/center moves - i.e. in the late-CP regime where
  we most need to differentiate. So the proxy is a discrete-stable `uncertainty(prob_dist)`
  with a single, frozen definition (below), not raw `std`.

## Why Track P, and why now (evidence)

Grounded in the read-only audit `reports/phase5_wide_bin_audit.md` (REQ-AUD-5, Passo 1)
and the two closed Track A one-shots:

- **A1 (winsorization, `1.1`) and A3 (Mondrian by sigma bucket, `1.2`) were real but
  insufficient.** Both ran one-shot, no leak, no gate-moving; the heteroscedasticity gate
  still failed on every split. A1 exhausted the GLOBAL scale correction and A3 the
  CONDITIONAL correction - both while KEEPING `sigma_hat = sqrt(p50_var)` fixed. The lesson:
  the axis itself, not the correction on top of it, is the limiting factor.
- **The wide-bin audit localizes the defect.** Per split, the binding over-coverage is in
  bin 1 (moderate width, large `n` = 98/127/161), whose Wilson 95% CI EXCLUDES 0.90
  ([0.962,1.0] / [0.957,0.999] / [0.956,0.997]) - a REAL structural over-coverage, not
  sampling noise. The extreme-wide bins 2-3 (`n` = 11-22) have Wilson intervals that
  STRADDLE 0.90, so they are NOT statistically callable.
- **The wide rows are an operational axis (late CP), not a season.** Across all three
  splits the wide bins are composed of ONLY the 22:00Z and 23:00Z CPs, spread over ~21-23
  distinct dates and most months. So the next proxy must carry signal IN that late-CP
  regime; this is why the prereg makes a per-CP sanity check mandatory.
- **Why a proxy change before Track D (randomized/smoothed).** A better difficulty axis is a
  smaller, more explainable change that does NOT alter the discrete object. There is no
  evidence yet of an INEVITABLE discrete-object straddle that only RNG could fix; Track D
  stays a fallback (update.txt Passo 4) pending evidence after Track P.

## What changes (exactly one hypothesis)

The single method change is the definition of `sigma_hat`. NOTHING else moves.

- BEFORE (v1.0 / A1 / A3 baseline): `sigma_hat = sqrt(p50_var)`, imputed by calib median,
  floored. `p50_var` is the causal variance of `y_pred_dec` across the EARLIER CPs of the
  same local date (NULL for the first CP of a day).
- AFTER (Track P): `sigma_hat = uncertainty(prob_dist)`, with the uncertainty functional
  fixed to **Shannon entropy in nats** of the per-row emitted integer predictive
  distribution `prob_dist` (dict[int,float] over the row's causal support `K`):
  `sigma_hat = - sum_k p_k * ln(p_k)`, with the convention `0 * ln(0) = 0`.
  Entropy is LABEL-INVARIANT (it depends only on the probability profile, not on where the
  integer support sits), which is the discrete-stability property the reviewer requires:
  it does not saturate or shift merely because the center/support moves between CPs. It is
  ALWAYS defined (every emitted row has a `prob_dist`), so there is no NULL/impute branch;
  it is floored at a calib-frozen `sigma_floor` for numerical safety only.
- Because the normalized score `u = (y_true_int - y_pred_dec)/sigma_hat` learns its tail
  quantiles `(q_lo, q_hi)` empirically on calib, `sigma_hat` need only be a POSITIVE,
  per-row, monotone-in-difficulty ordering; its physical units are absorbed by the learned
  quantiles. Entropy (nats) therefore plugs into the existing machinery unchanged.
- The conformal score form, the asymmetric tails, the GLOBAL `(q_lo, q_hi)`, the
  `c`-selection rule + grid, `Q(x) = floor(x + 0.5)`, and the interval endpoints are the
  v1.0 method - just evaluated with the new `sigma_hat`. There is NO Mondrian, NO
  winsorization, NO per-bucket conditioning (those are A1/A3, separate hypotheses).
- `conformal_method_version` bumps `1.0 -> 1.3`. (A1 = `1.1`, A3 = `1.2`; Track P is a
  SEPARATE branch off the v1.0 baseline and is `1.3`.)

### Determinism / causality of the new proxy (frozen, pre-registered)

- `prob_dist` is the model's emitted forecast for that row, built causally upstream
  (`latent_to_prob_dist` over the causal support `K`); its entropy introduces NO future
  information - it is a deterministic function of the same per-row forecast already emitted.
- `sigma_floor` is computed on CALIB ONLY (a fixed small percentile of calib `sigma_hat`,
  pre-registered below) and FROZEN; test reuses the frozen floor. The test distribution
  never influences the floor.
- No RNG anywhere; same calib input -> identical `sigma_floor`, identical scores, identical
  `c`, identical intervals.

### MANDATORY read-only sigma-hat sanity checks (BEFORE the one-shot; reviewer-required)

These are axis SANITY checks, not tuning. They run read-only on CALIB ONLY and MUST pass
before the single `phase5_evaluate` run is permitted. If any fails, the one-shot is NOT
executed and Track P is rejected in favour of a DIFFERENT pre-registered proxy.

1. **Monotonicity vs a simple difficulty label.** Compute the difficulty label
   `abs_error_int = |y_true_int - Q(y_pred_dec)|` on calib, and require the Spearman rank
   correlation `rho(sigma_hat, abs_error_int)` on calib, PER SPLIT, to be POSITIVE and
   `>= sanity.monotonicity_min_rho` (pre-registered below). Rationale: a difficulty axis
   that does not even rank-order the model's own integer error is not a difficulty axis.
2. **No per-CP collapse.** For each CP (and explicitly for 22:00 and 23:00, the regime where
   the over-coverage lives), the calib `sigma_hat` distribution must have
   `>= sanity.by_cp_min_distinct` distinct values. Rationale: a proxy that collapses to a
   single value within the late-CP regime cannot differentiate the rows that fail the gate.

The sanity thresholds are frozen in the hashed block; they are NOT re-tuned after looking.
A failed sanity check is an honest, informative reject of THIS proxy (open a new one), never
a reason to relax the threshold.

## What does NOT change

- Coverage gate: target `0.80`, tol `0.04`, band `[0.76, 0.84]`. Untouched.
- Heteroscedasticity gate: per-width-quartile coverage in `[0.70, 0.90]`, 4 bins, per split,
  never pooled. Untouched (the bar Track P is trying to MEET, not move).
- ECE gate `0.05`. Untouched (ECE is Track C; not bundled here).
- The het-gate width binning (rank-quantiles over distinct widths) - the frozen normative
  definition in `docs/req_aud5_normative.md`. Untouched.
- Splits (2023/2024/2025, 365 d), calib windows (per-CP 90 d), `c`-selection rule + grid,
  `Q(x) = floor(x + 0.5)`, seeds, determinism. Untouched.
- The conformal method family (normalized quantization-aware, GLOBAL asymmetric tails).
  Only the `sigma_hat` input changes.

## Acceptance criteria (pre-registered; evaluated once)

0. (Pre-condition) Both MANDATORY sanity checks above PASS on calib, per split. If not, the
   one-shot is not run.
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
- No re-tuning of the uncertainty definition, the floor percentile, the sanity thresholds,
  or the `c`-rule after seeing the result. If Track P fails on its honest terms, the next
  step is a DIFFERENT pre-registered hypothesis (another proxy, or Track D), not a tweak to
  this one.

## Expected failure modes (honest; stated before the run)

- The band-aware softmax `tau` may make `prob_dist` (hence its entropy) near-constant across
  rows, so the new `sigma_hat` could fail the monotonicity sanity check - informative: it
  would mean the model's emitted distribution does not encode difficulty either, which
  strengthens the case for Track D. This is caught BEFORE the one-shot by design.
- A better-calibrated `sigma_hat` typically NARROWS easy rows and WIDENS hard rows; global
  calib coverage could drift, pushing the selected `c`. The coverage band gate guards this;
  leaving the band is a pre-registered kill, not a tuning opportunity.
- Entropy is label-invariant, so it ignores the PHYSICAL degree-spread that `std` would
  capture. If the monotonicity check shows entropy ranks difficulty well this is a feature
  (stability); if it ranks poorly the check fails and we switch proxy - either way the
  decision is made on calib BEFORE the test readout.

## Minimal test checklist (to add in the SAME change-set that wires + runs Track P)

Per `references/code-reviews/update.txt` Passo 3 ("testes unitarios: no-leak, determinismo,
sanity"):

- **no-leak:** `sigma_floor` and the sanity thresholds are computed/declared on calib ONLY
  and frozen; `apply` on a test set whose `sigma_hat` distribution differs reuses the SAME
  frozen floor and the SAME global `(q_lo, q_hi)`; test never re-estimates the floor or the
  quantiles, and the sanity checks never touch test.
- **determinism:** same calib input -> identical `sigma_floor`, identical Spearman rho,
  identical `c`, identical emitted intervals (re-run equality).
- **sanity (unit-level):** entropy matches the closed-form `- sum_k p_k ln p_k` on a
  hand-checked distribution (incl. the one-hot `H = 0` and uniform `H = ln|K|` corners);
  `sigma_hat >= sigma_floor` after flooring; the monotonicity helper returns a known
  Spearman value on a constructed monotone fixture; the per-CP distinct-count helper detects
  a constructed collapsed-CP fixture.
- **reduction sanity:** with `sigma_hat` forced constant the method reduces to a fixed-width
  global interval and the degenerate-proxy / collapsed sanity path is reachable and detected.

The canonical, hashed content is everything between the two markers. Prose outside the
markers (this header and rationale) is NOT hashed.

<<<PREREG
PHASE5_AMENDMENT_TRACK_P
criterion_version: 1.0
amends: phase5_preregistration.md (criterion_version 1.0)
conformal_method_version: 1.3
q_version: 1.0
frozen_date: 2026-05-30

# --- Hypothesis (exactly one) ---
hypothesis.id: trackP_predictive_uncertainty_sigma
hypothesis.scope: difficulty_axis_only
hypothesis.framing: difficulty_axis_change_not_spike_fix
hypothesis.changes_gate: false
hypothesis.changes_sigma_proxy: true
hypothesis.changes_windows: false
hypothesis.includes_winsorization: false
hypothesis.includes_mondrian: false

# --- The single method change: sigma_hat = uncertainty(prob_dist) ---
sigma.proxy_before: sqrt(p50_var)
sigma.proxy_after: uncertainty(prob_dist)
sigma.uncertainty_definition: shannon_entropy_nats
sigma.entropy_formula: -sum_k p_k * ln(p_k)
sigma.entropy_zero_convention: 0*ln(0)=0
sigma.label_invariant: true
sigma.prob_dist_support: causal_per_row_support_K
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

- **Why a proxy change is the right next move.** A1 and A3 exhausted the GLOBAL and the
  CONDITIONAL corrections that keep `sigma_hat = sqrt(p50_var)` fixed; both failed because
  the axis itself does not order difficulty in the late-CP regime. The audit shows the
  over-coverage is structural (bin 1 CI excludes 0.90) and tied to the 22Z/23Z rows, so a
  better scale - not more conditioning on a bad scale - is the principled lever.
- **Why `uncertainty(prob_dist)` = entropy, not raw `std`.** Entropy is label-invariant and
  stable when the support/center moves (the discrete late-CP regime), avoiding the
  saturation the reviewer flagged for `std`; it is the model's own per-row uncertainty,
  fine-grained, always defined, causal, and RNG-free, requiring no new data and no change to
  the discrete object.
- **Why mandatory sanity-before-one-shot.** A self-derived proxy can be "pretty" yet
  collapse exactly where it must differentiate. Checking monotonicity vs `|error_int|` and
  the per-CP distribution on CALIB, BEFORE the test readout, prevents spending the one-shot
  on an axis that demonstrably carries no signal - and keeps the test strictly readout-only.
- **Why this is not gaming.** Exactly one variable changes (`sigma_hat`); the uncertainty
  definition, the floor percentile, the sanity thresholds, the `c`-rule, and every gate
  threshold are fixed ex-ante and hashed; nothing is tuned to the gate; the floor and
  sanity checks are calib-only; the run is once; kill criteria (including "the new proxy
  fails its sanity checks") are pre-committed.
- **Alternatives considered (and why not now).** Raw `std(prob_dist)` (degree-scale but can
  saturate in discrete late-CP regimes - reviewer-flagged); `1 - max_prob` (stable but
  coarser - ignores how mass spreads below the mode); `distance-to-threshold` (couples
  calibration to a market-specific object); `real NWP spread` (needs an ingest change - the
  current `nwp_spread` is median-filled to 0, signal-free). Each remains available as a
  separate future pre-registered hypothesis if Track P is rejected.
