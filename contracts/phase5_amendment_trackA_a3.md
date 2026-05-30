# Phase 5 amendment - Track A.A3: Mondrian conditional conformal by sigma bucket (conformal_method_version 1.2)

> **Status: PROPOSED (not yet wired, not yet executed).** Per
> `references/code-reviews/update.txt` the reviewer has decided to START Track A3, but
> requires the pre-registration documentation to be explicit BEFORE any implementation
> (pre-registro + hash + changelog antes do codigo). This document is that artifact. The
> hashed block below is frozen for tamper-evidence; wiring it into
> `core/eval/preregistration.py` (`PHASE5A3_COMMITTED_SHA256` +
> `assert_phase5a3_preregistration_committed()`) and running `phase5_evaluate` ONCE
> happens only in a later, separate change-set.
>
> Canonical PREREG sha256 (to be pinned as `PHASE5A3_COMMITTED_SHA256` at wiring time):
> `ee0ac6f232490b749eaac27cbb974a58446d4b6db15fc96be607ae5a8b87e411`

## Hypothesis name

`trackA_a3_mondrian_sigma_bucket` - the wide-width-quartile over-coverage is a
CONDITIONAL miscalibration (it depends on the `sigma_hat` / width regime), so calibrate
the tail quantiles `(q_lo, q_hi)` CONDITIONALLY per `sigma_hat` bucket (Mondrian),
instead of a single global pair, with a fixed shrinkage toward the global pair to control
degrees of freedom.

## Why A3, and why now (evidence)

- Track A.A1 (`reports/phase5_trackA_a1.md`, run_id `20260530T012449Z`) winsorized
  `sigma_hat` to a calib-frozen `[P25, P95]`. It ran one-shot, with no leakage and no
  gate-moving. It REDUCED the widest-bin over-coverage in part (e.g. 2023 `1.000 -> 0.947`)
  but did NOT close the heteroscedasticity gap: bins 2-4 still over-cover (`> 0.90`) on
  every split. A1 was a real but INSUFFICIENT improvement.
- The lesson A1 teaches: a GLOBAL scale adjustment (one clip band applied to all rows)
  cannot fix a problem that is CONDITIONAL on the `sigma_hat` regime. Different `sigma_hat`
  buckets need different tail quantiles. A3 attacks exactly this, with controlled DOF and
  frozen rules.

## What changes (exactly one hypothesis)

The single method change is: the asymmetric tail quantiles become CONDITIONAL on a
`sigma_hat` bucket, with fixed shrinkage toward the global quantiles.

- Partition the calib rows into `n_buckets = 4` buckets by `sigma_hat` using empirical
  quantile edges (`rank_quantiles`), computed on CALIB ONLY and FROZEN. Test rows are
  assigned to a bucket via `searchsorted` on those frozen edges; the test distribution
  never influences the partition.
- For a fixed nominal level `c`, the per-bucket quantiles `q_lo^b, q_hi^b` are the
  empirical quantiles of the score `u = (y_true_int - y_pred_dec)/sigma_hat` AMONG the
  calib rows in bucket `b`, at levels `p_lo = (1-c)/2`, `p_hi = 1 - (1-c)/2`. The global
  quantiles `q_lo^g, q_hi^g` are the same empirical quantiles over ALL calib rows.
- Shrinkage (always ON, fixed): the effective per-bucket quantile is
  `q_eff = alpha * q_bucket + (1 - alpha) * q_global`, with
  `alpha = n_bucket / (n_bucket + n0)`, `n0 = 200` (fixed, pre-registered). Small buckets
  shrink hard toward the global pair; large buckets keep more of their own estimate.
- `c` stays GLOBAL per split, selected on calib exactly as v1.0 (grid search; pick `c`
  whose GLOBAL calib integer coverage is in `[0.76, 0.84]` and minimizes
  `|coverage - target|`). There is NO `c` per bucket. Only `(q_lo, q_hi)` are conditional.
- The emitted interval for a row uses its bucket's effective quantiles:
  `[Q(y_pred_dec + q_lo_eff * sigma_hat), Q(y_pred_dec + q_hi_eff * sigma_hat)]`,
  `hi_int >= lo_int`, `Q(x) = floor(x + 0.5)`.
- `conformal_method_version` bumps `1.0 -> 1.2`. (A1 used `1.1`; A3 is a SEPARATE branch
  off the v1.0 baseline and is `1.2`.)

### Determinism of the partition (frozen, pre-registered)

- `sigma_hat` is built in a FIXED order before any bucketization:
  `sqrt(p50_var) -> impute calib median -> floor -> bucketize`. Bucketizing before the
  floor/impute is forbidden.
- Edges `= numpy.quantile(calib sigma_hat, [0.25, 0.50, 0.75], method="linear")`. The SAME
  `method="linear"` is used for the per-bucket quantiles `q_bucket` and the global
  quantiles `q_global` (no mixing numpy edges with a different-method `q`).
- Bucket index `= numpy.searchsorted(edges, sigma_hat, side="right")` for BOTH calib and
  test, so a row exactly on an edge resolves to the upper bucket deterministically.
- Stable tie-handling by original index governs every sort/quantile, so identical calib
  input yields identical edges and identical per-bucket quantiles.
- **Known consequence of the `sigma_hat` spike (stated before the run).** Diagnostics show
  ~75% of `sigma_hat` mass sits at a single value (~0.10), so the interior edges can be
  equal-valued; `searchsorted` then leaves interior buckets empty or below `min_n_bucket`.
  This is expected, not a bug: the deterministic merge below collapses such buckets. If it
  collapses all the way to a single bucket, A3 degenerates to v1.0 - an honest, informative
  result meaning `sigma_hat` carries too little conditional structure to exploit.

### Minimum bucket size + deterministic merge fallback (frozen)

- `min_n_bucket = 50` (pre-registered). Below this a per-bucket quantile is too noisy to
  trust even after shrinkage.
- Merge rule (deterministic): while any bucket has `n < min_n_bucket`, take the smallest
  such bucket and merge it into its adjacent neighbour, preferring the LOWER-index
  neighbour on a tie; recompute counts; repeat until every remaining bucket has
  `n >= min_n_bucket`. Merging unions the adjacent edge intervals (drops the shared edge),
  so the partition stays contiguous in `sigma_hat`. The same merged edge set is frozen and
  reused on test.

## What does NOT change

- Coverage gate: target `0.80`, tol `0.04`, band `[0.76, 0.84]`. Untouched.
- Heteroscedasticity gate: per-width-quartile coverage in `[0.70, 0.90]`, 4 bins.
  Untouched (this is the bar we are trying to MEET, not move).
- ECE gate `0.05`. Untouched.
- Sigma PROXY stays `p50_var` (sqrt to stddev), imputed by calib median and floored.
  A3 does NOT winsorize (that is A1, a separate hypothesis); A3 does NOT swap the proxy.
- Splits (2023/2024/2025, 365 d), calib windows (per-CP 90 d), `c`-selection rule + grid,
  `Q(x) = floor(x + 0.5)`, seeds, determinism. Untouched.
- The het-gate width bins (the evaluation binning) are independent of the A3 `sigma_hat`
  buckets (the calibration partition). They are NOT the same object and are not coupled.

## Acceptance criteria (pre-registered; evaluated once)

1. The heteroscedasticity gate PASSES per split on TEST (every width-quartile coverage in
   `[0.70, 0.90]`) - this is the binding bar A3 is trying to meet.
2. Global calib coverage stays in `[0.76, 0.84]`.
3. Widths remain NON-DEGENERATE (`>= 3` distinct integer widths on calib AND test).

## Kill criteria (pre-registered; reject the hypothesis if hit)

- If widths collapse to degenerate (`< 3` distinct widths, or width std `~ 0`), REJECT -
  sharpness destruction, not calibration.
- If global calib coverage leaves `[0.76, 0.84]`, REJECT.
- If any bucket is empty AFTER the merge fallback completes, REJECT (the partition is
  ill-defined) - the merge is designed to make this impossible, so hitting it is a bug
  signal, not a tuning opportunity.
- No re-tuning of `n_buckets`, `n0`, `min_n_bucket`, the edge quantiles, or the quantile
  method after seeing the result. If A3 fails on its honest terms, the next step is a
  DIFFERENT pre-registered hypothesis, not new Mondrian parameters.

## Expected failure modes (honest; stated before the run)

- The `sigma_hat` spike may collapse the partition toward 1-2 effective buckets (see
  above). If so, A3 will look close to v1.0 / A1 and likely still fail the het gate. That
  would be evidence the difficulty signal `p50_var` is too weak for conditional
  calibration - motivating a proxy change (a separate hypothesis), not a parameter tweak.
- Even with 4 surviving buckets, shrinkage `n0 = 200` against ~89-row buckets pulls hard
  toward global (`alpha ~ 0.31`), so the conditional effect is deliberately damped to
  control DOF; partial improvement is an acceptable, informative outcome.

## Minimal test checklist (to add in the SAME change-set that wires + runs A3)

Per `references/code-reviews/update.txt` section "Checklist de testes minimos":

- **no-leak:** edges, the merge decisions, and the shrinkage params (`n0`, `min_n_bucket`)
  are computed on calib ONLY and frozen on the calibrator; `apply` on a test set whose
  `sigma_hat` distribution differs reuses the SAME edges/buckets/quantiles (a test row in
  the far tail is assigned by the frozen edges, not by re-quantiling test).
- **determinism:** same calib input -> identical edges, identical bucket assignment,
  identical per-bucket quantiles, identical merged partition (re-run equality).
- **sanity:** every bucket is non-empty after merge (`n >= min_n_bucket`); emitted widths
  are non-degenerate (`>= 3` distinct integer widths); `hi_int >= lo_int`; integer dtype.
- **shrinkage invariants:** `alpha in [0, 1]`; `alpha -> 0` as `n_bucket -> 0`;
  `q_eff` lies between `q_bucket` and `q_global`; with a single surviving bucket
  `q_eff == q_global` (A3 reduces to v1.0).

The canonical, hashed content is everything between the two markers. Prose outside the
markers (this header and rationale) is NOT hashed.

<<<PREREG
PHASE5_AMENDMENT_TRACK_A_A3
criterion_version: 1.0
amends: phase5_preregistration.md (criterion_version 1.0)
conformal_method_version: 1.2
q_version: 1.0
frozen_date: 2026-05-30

# --- Hypothesis (exactly one) ---
hypothesis.id: trackA_a3_mondrian_sigma_bucket
hypothesis.scope: heteroscedasticity_only
hypothesis.changes_gate: false
hypothesis.changes_sigma_proxy: false
hypothesis.changes_windows: false
hypothesis.includes_winsorization: false

# --- The single method change: Mondrian conditional (q_lo, q_hi) by sigma bucket ---
mondrian.enabled: true
mondrian.n_buckets: 4
mondrian.bucket_variable: sigma_hat
mondrian.bucket_variable_is_winsorized: false
mondrian.sigma_hat_pipeline: sqrt -> impute_calib_median -> floor -> bucketize
mondrian.assignment: rank_quantiles
mondrian.quantile_method: linear
mondrian.quantile_method_applies_to: [edges, q_bucket, q_global]
mondrian.edge_quantiles: [0.25, 0.50, 0.75]
mondrian.searchsorted_side: right
mondrian.tie_handling: by_original_index_stable
mondrian.edges_basis: calib_only
mondrian.edges_frozen_on_calib: true
mondrian.test_assignment: searchsorted_on_frozen_calib_edges
mondrian.min_n_bucket: 50
mondrian.merge_fallback: deterministic_adjacent_merge_until_all_ge_min_n
mondrian.merge_pick: smallest_below_min_n_first
mondrian.merge_neighbour_tiebreak: lower_index
mondrian.c_is_global: true
mondrian.c_per_bucket: false
mondrian.conditional_params: [q_lo, q_hi]
mondrian.shrinkage_enabled: true
mondrian.shrinkage_formula: q_eff = alpha * q_bucket + (1 - alpha) * q_global
mondrian.shrinkage_alpha: n_bucket / (n_bucket + n0)
mondrian.shrinkage_n0: 200
mondrian.q_global_basis: all_calib_recent_tail_rows
mondrian.q_bucket_basis: calib_recent_tail_rows_in_bucket

# --- Everything below is INHERITED UNCHANGED from phase5 v1.0 ---
conformal.method: normalized_quantization_aware
conformal.center: y_pred_dec
conformal.evaluated_object: integer_inclusive_bracket_contains_y_true_int
conformal.score: u = (y_true_int - y_pred_dec) / sigma_hat
conformal.tails: asymmetric
conformal.p_lo: (1 - c) / 2
conformal.p_hi: 1 - (1 - c) / 2
conformal.endpoint_lo: Q(y_pred_dec + q_lo_eff * sigma_hat)
conformal.endpoint_hi: Q(y_pred_dec + q_hi_eff * sigma_hat)
conformal.hi_ge_lo: true
conformal.Q: floor(x + 0.5)
c_select.grid_start: 0.50
c_select.grid_stop: 0.96
c_select.grid_step: 0.005
c_select.rule: pick c with GLOBAL calib integer coverage in [band_lo, band_hi] minimizing |coverage - target|
c_select.fallback: if none in band, pick c minimizing |coverage - target|
c_select.tie_break: lowest c wins on equal distance
c_select.recomputes_bucket_q_per_candidate_c: true
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
accept.heterosced_gate_passes_per_split_on_test: true
accept.global_calib_coverage_in_band: true
accept.widths_non_degenerate_min_distinct: 3
kill.reject_if_widths_degenerate: true
kill.reject_if_global_calib_coverage_out_of_band: true
kill.reject_if_any_bucket_empty_after_merge: true
kill.no_param_retuning_after_results: true

# --- Run discipline ---
run.execute_phase5_evaluate_times: 1
run.test_is_readout_only: true
PREREG>>>

## Rationale (not hashed)

- **Why conditional, not global.** A1 proved a single clip band cannot move bins 2-4 into
  band; the over-coverage differs by `sigma_hat` regime, so the correction must too.
  Mondrian conditioning is the standard, principled tool for exactly this.
- **Why shrinkage with fixed `n0`.** Per-bucket quantiles over ~89 rows are noisy; raw
  per-bucket quantiles would overfit and could destroy sharpness. Shrinking toward the
  global pair with a fixed, pre-registered `n0 = 200` caps the degrees of freedom and keeps
  the change conservative and reproducible.
- **Why `c` stays global.** Selecting `c` per bucket would multiply the search surface and
  invite overfitting the gate; keeping `c` global (one number per split, calib-only) while
  letting only `(q_lo, q_hi)` vary by bucket is the minimal conditional change.
- **Why this is not gaming.** Every parameter (`n_buckets`, edge quantiles, quantile
  method, `min_n_bucket`, merge rule, `n0`) is fixed ex-ante and hashed; none is tuned to
  the gate; `c` and all quantiles are calib-only; the run is once; the gate thresholds are
  untouched; kill criteria (including "reduces to v1.0 under the spike") are pre-committed.
