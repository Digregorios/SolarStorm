# Phase 5 amendment - Track D.D1: randomized rounding / tie-breaking at quantization (conformal_method_version 2.0, q_version 1.1)

> **Status: PROPOSED (not yet wired, not yet executed).** Per
> `references/code-reviews/update.txt` (2026-05-30) the reviewer reviewed FOUR honest
> negative results - A1 (global scale) and A3 (Mondrian by sigma bucket) both insufficient at
> the het gate; Track P (entropy difficulty axis) and Track P' (quantization-margin difficulty
> axis) both rejected at the calib-only sanity gate - and DIRECTED moving to a DIFFERENT CLASS
> of hypothesis: Track D, discrete-object smoothing. The reviewer recommended STARTING with
> **D1 (deterministic-RNG randomized quantization)** over D2 (deterministic soft-containment)
> because D1 touches a single place (the quantization step), preserves the rest of the
> pipeline, is easy to test for determinism / no-leak, and attacks the step/tie of `Q` at
> `0.5` directly. This file registers D1 docs-before-code; wiring
> (`PHASE5D1_COMMITTED_SHA256` + `assert_phase5d1_preregistration_committed()`), the unit
> tests, and the single `phase5_evaluate` one-shot happen ONLY in a later, separate change-set
> AFTER explicit reviewer approval (per update.txt line 22: "so entao pedir aprovacao para
> wiring+run one-shot").
>
> **Transcription correction (2026-05-30, pre-execution, before any result seen).** The
> first transcription of `quantization.randomized_Q_definition` carried a factor-2 error
> (`u < (1 - 2t)` / `u < (2t - 1)`), which yields `P(ceil) = 2t` and a BIASED estimator
> `E[Q_rand(x)] = x + t` plus a pathological flip exactly at `t = 0.5` - directly
> contradicting this contract's stated `E[Q_rand(x)] = x`, its "Bernoulli linear in the
> fractional part" rationale, and the mandatory unbiasedness sanity test. Corrected to the
> standard randomized rounding `P(ceil) = t` (`ceil if u < t else floor`). This is a
> faithful-intent fix made BEFORE wiring/running, not a post-hoc tweak; the canonical hash
> is recomputed accordingly in the SAME change-set that wires `PHASE5D1_COMMITTED_SHA256`.
>
> Canonical PREREG sha256 (pinned as `PHASE5D1_COMMITTED_SHA256` at wiring time, AFTER the
> transcription correction above): recomputed in-code via
> ``python -m core.eval.preregistration phase5d1``.

## ASCII transliteration note (faithful transcription)

This repo enforces ASCII-only source (`tools/ascii_guard.py`). The reviewer's template uses two
non-ASCII glyphs; they are transliterated here with NO change of meaning, and the canonical hash
is computed over the ASCII text:

- The randomized quantizer, written in the reviewer's template as "Q" with a combining tilde
  above it, is transliterated as `Q_rand` throughout.
- The "approximately equal" sign in the reviewer's template is transliterated as `~=`.

There is no pre-committed D1 hash to match (this is the first registration of D1), so the
canonical sha256 is computed from this ASCII contract and pinned at wiring time.

## Hypothesis name

`trackD_d1_randomized_q` - the REQ-AUD-5 binding miscalibration lives in the moderately-wide,
large-`n` bin in the late-CP regime (Passo 1), where the evaluated object is discrete and
INCLUSIVE. Four deterministic corrections have now failed to move the het gate: global scale
(A1), conditioning by sigma bucket (A3), and two difficulty-axis swaps (P entropy, P' margin).
The next-order hypothesis is that the COMBINATION of {discrete object + inclusive containment +
quantization at the endpoints} creates steps/asymmetry that a purely deterministic method cannot
"align" in the late-CP regime without inflating slack. D1 keeps the normalized
quantization-aware conformal exactly as-is UP TO the endpoints, and replaces the deterministic
`Q(x) = floor(x + 0.5)` with a reproducible RANDOMIZED quantization `Q_rand` that removes the
step/tie around `0.5` - WITHOUT touching any gate.

## Framing (read this before the method)

- This is a **discrete-object smoothing change, NOT a gate change and NOT a sigma/difficulty
  change.** Exactly one thing moves: the quantizer at the two endpoints, `Q -> Q_rand`. The
  sigma proxy (`p50_var`), the score, the asymmetric tails, the GLOBAL `(q_lo, q_hi)`, the
  `c`-selection rule + grid, the windows, and the splits are unchanged.
- **Why D1 and why now (reviewer rationale).** It is the smallest change in the new class: a
  single substitution at quantization, trivially testable for determinism and no-leak, and
  aimed squarely at the `0.5` step/tie that the four prior deterministic attempts could not
  align. D2 (soft containment) is held back because it CALIBRATES on a soft object but REPORTS
  on the hard object - a larger, harder-to-defend change the reviewer would only take with an
  explicit "hard containment is too degenerate" motivation.
- **Why randomized rounding.** `Q(x) = floor(x + 0.5)` is a hard step at every half-integer, so
  near `frac(x) = 0.5` an arbitrarily small change in the decimal endpoint flips the emitted
  integer - the discrete artifact. `Q_rand` makes the rounding a Bernoulli draw whose
  probability is linear in the fractional part, so `E[Q_rand(x)] = x` (unbiased) and the
  step/tie around `0.5` is smoothed across rows, while each row stays fully reproducible from
  `(global_seed, row_id, endpoint_side)`.

## What changes (exactly one hypothesis)

The single method change is the quantizer applied to the two decimal endpoints.

- BEFORE (v1.0 / A1 / A3 / P / P'): `endpoint_int = Q(y_pred_dec + q * sigma_hat)` with
  `Q(x) = floor(x + 0.5)` (deterministic).
- AFTER (Track D1): `endpoint_int = Q_rand(y_pred_dec + q * sigma_hat; global_seed, row_id,
  endpoint_side)` where `Q_rand` is the randomized rounding defined in the hashed block:
  for `f = floor(x)`, `t = x - f` and a deterministic `u ~ Uniform(0,1)` keyed by
  `(global_seed, row_id, endpoint_side)` - `return f+1 (ceil) if u < t else f (floor)` for all
  `t in (0,1)` (and exactly `f` when `t == 0`). This gives `P(ceil) = t`, so
  `E[Q_rand(x)] = x` and the hard tie at `0.5` is removed.
- `conformal_method_version` bumps `1.0 -> 2.0`; `q_version` bumps `1.0 -> 1.1` (the quantizer
  object itself changed - a MAJOR bump, distinct from the difficulty-axis tracks that left `Q`
  intact).

### Determinism / no-leak / causality of the RNG (frozen, pre-registered)

- `global_seed = 20260530` is FIXED in the hashed block. The per-row draw `u` is a deterministic
  function of `(global_seed, row_id, endpoint_side)` only - NO dependence on test statistics, on
  the calib/test role, or on any other row. Same inputs -> same `Q_rand` output, on every
  machine, every run.
- `row_id` is a deterministic hash of NO-FUTURE, per-row-stable keys (reviewer's normative
  decision, `update.txt` 2026-05-30): `row_id = sha256(f"{station_id}|{day_local}|{cp_utc}")`.
  Here `station_id` is the station icao literal `NZWN` (this is a single-station project; the
  panel carries no `station_id` column, the icao is fixed in `nzwn/config/station.yaml`),
  `day_local` is the panel's `date_local` column, and `cp_utc` is the panel's `cp_utc` column
  (ISO UTC). It does NOT depend on the realized label, on any feature, or on any time-varying
  state, and it explicitly does NOT use the dataframe/panel ROW INDEX (which changes under
  sort/filter and would break reproducibility). The `endpoint_side` tag (`lo` / `hi`)
  decorrelates the two endpoints; `split_name` MAY be mixed in for cross-split independence only
  if stable. The seed and RNG version are logged in the run audit. A non-deterministic `Q_rand`
  (same inputs -> different output) is a KILL.
- The seed and RNG version are logged in the run audit. A non-deterministic `Q_rand` (same
  inputs -> different output) is a KILL.

### Invariants that MUST hold (pre-registered)

- `hi_int >= lo_int` after randomized rounding; if violated for a row, set `hi = lo` (degenerate
  but valid; the reviewer's rule).
- Endpoints are integer dtype.
- Global calib coverage stays in band; widths stay non-degenerate; the run is deterministic
  given the seed.

## What does NOT change

- Coverage gate (`0.80 +/- 0.04`, band `[0.76, 0.84]`), het gate (per-width-quartile in
  `[0.70, 0.90]`, 4 bins, per split, never pooled), ECE gate (`0.05`). Untouched.
- The het-gate width binning (frozen normative definition in `docs/req_aud5_normative.md`).
- Sigma proxy (`p50_var`, variance, sqrt, calib-median impute, floor), the score, the
  asymmetric tails, the GLOBAL `(q_lo, q_hi)`, the `c`-selection rule + grid, splits
  (2023/2024/2025), calib windows (per-CP 90 d). Untouched.
- The conformal method family (normalized quantization-aware). Only the endpoint quantizer
  changes, `Q -> Q_rand`.

## Acceptance criteria (pre-registered; evaluated once)

1. The heteroscedasticity gate PASSES per split on TEST (every width-quartile coverage in
   `[0.70, 0.90]`) - the binding bar.
2. Global calib coverage stays in `[0.76, 0.84]`.
3. Widths remain NON-DEGENERATE (`>= 3` distinct integer widths on calib AND test).

## Kill criteria (pre-registered; reject the hypothesis if hit)

- If `Q_rand` is not deterministic given `(global_seed, row_id, endpoint_side)`, REJECT.
- If global calib coverage leaves `[0.76, 0.84]`, REJECT.
- If widths collapse to degenerate (`< 3` distinct widths, or width std `~= 0`), REJECT.
- No re-tuning of the seed, the `Q_rand` definition / eps, the sigma floor, or the `c`-rule
  after seeing the result. If D1 fails on its honest terms, the next step is a DIFFERENT
  pre-registered hypothesis (D2 soft-containment, or a refined D1 with tie-only randomization),
  NOT a tweak to this one.

## Expected failure modes (honest; stated before the run)

- **Randomization may only relabel slack, not remove it.** If the over-coverage in the mod-wide
  late-CP bin is structural (the interval genuinely spans too many integers), unbiased
  randomized rounding redistributes which integer each endpoint lands on but does not narrow the
  bracket - the het gate could still fail. That is an informative, honest result.
- **Variance injection.** `Q_rand` adds per-row noise; aggregate coverage should be stable (the
  A/B seed check is read-only evidence of this) but widths could fluctuate. The non-degeneracy
  kill guards against width collapse.
- **hi < lo flips.** Independent draws on the two endpoints can invert a very narrow interval;
  the `hi = lo` fallback keeps the object valid and is pre-registered, not a post-hoc patch.

## Minimal test checklist (to add in the SAME change-set that wires + runs D1)

Per `references/code-reviews/update.txt` lines 95-99:

- **determinism:** same `row_id + seed -> same Q_rand`; same calib input -> identical `c`,
  `(q_lo, q_hi)`, and emitted intervals on re-run.
- **no-leak:** `global_seed` is fixed and `row_id = sha256(station_id|day_local|cp_utc)` does
  not depend on test statistics, on the realized label, on features, or on the dataframe row
  index; calib never sees test, the draw is row-local.
- **sanity:** `hi >= lo` for every row (incl. the `hi = lo` fallback path); endpoints are int
  dtype; `E[Q_rand(x)] = x` holds in expectation on a constructed grid (unbiasedness);
  `Q_rand` reduces to `floor`/`ceil` deterministically at the `t<0.5` / `t>=0.5` extremes.
- **A/B (read-only, NOT a gate):** with a DIFFERENT seed the per-row assignment changes but the
  aggregate metrics (global coverage) stay stable - reported as evidence, never as pass/fail.

The canonical, hashed content is everything between the two markers. Prose outside the markers
(this header and rationale) is NOT hashed.

<<<PREREG
PHASE5_AMENDMENT_TRACK_D_D1
criterion_version: 1.0
amends: phase5_preregistration.md (criterion_version 1.0)
conformal_method_version: 1.0 -> 2.0
q_version: 1.0 -> 1.1
frozen_date: 2026-05-30
hypothesis.id: trackD_d1_randomized_q
hypothesis.scope: discrete_object_smoothing_only
hypothesis.changes_gate: false
hypothesis.changes_sigma_proxy: false
hypothesis.changes_windows: false
hypothesis.changes_c_rule: false
--- Core: keep normalized quantization-aware conformal unchanged up to endpoints ---
conformal.method: normalized_quantization_aware
conformal.center: y_pred_dec
conformal.score: u = (y_true_int - y_pred_dec) / sigma_hat
sigma.proxy: p50_var
sigma.is_variance: true
sigma.transform: sqrt
sigma.missing_impute: calib_median
sigma.floor: max(calib_median * 1e-3, 1e-6)
conformal.tails: asymmetric
conformal.p_lo: (1 - c) / 2
conformal.p_hi: 1 - (1 - c) / 2
c_select.grid_start: 0.50
c_select.grid_stop: 0.96
c_select.grid_step: 0.005
c_select.rule: pick c with GLOBAL calib integer coverage in [band_lo, band_hi] minimizing |coverage - target|
c_select.fallback: if none in band, pick c minimizing |coverage - target|
c_select.tie_break: lowest c wins on equal distance
c_select.test_blind: true
--- The single change: randomized quantization Q_rand(x; seed, row_id) instead of Q(x) ---
quantization.family: randomized_rounding
quantization.base_Q: floor(x + 0.5)
quantization.randomized_Q_definition:
Let f = floor(x); t = x - f in [0,1).
Let u ~ Uniform(0,1) generated deterministically from (global_seed, row_id, endpoint_side).
If t == 0: return f (exact integer; no draw).
If t < 0.5: return f+1 (ceil) if u < t else f (floor)
If t >= 0.5: return f+1 (ceil) if u < t else f (floor)
(Equivalently for all t in (0,1): ceil if u < t else floor. P(ceil)=t => E[Q_rand(x)] = x, unbiased, and the hard tie at 0.5 is removed.)
quantization.seed_global: 20260530
quantization.row_id_definition: row_id = sha256(f"{station_id}|{day_local}|{cp_utc}") (hex; truncation to 16 hex chars is for logs only, the seed derivation may use the full digest)
quantization.row_id_keys: [station_id, day_local, cp_utc]
quantization.row_id_keys_property: no_future_and_stable_per_row (no label, no features, no time-varying state)
quantization.row_id_forbidden: dataframe_or_panel_row_index (changes under sort/filter; breaks reproducibility)
quantization.station_id_source: station icao literal (single-station: NZWN); day_local = panel date_local column; cp_utc = panel cp_utc column (ISO UTC)
quantization.seed_derivation: u = uniform01(hash64(global_seed, row_id, endpoint_side[, split_name]))  # split_name optional, only if stable
quantization.row_id_source: row_id_definition above  # must be deterministic; NOT page_url
quantization.endpoint_side_tag: [lo, hi]  # to decorrelate endpoints
quantization.determinism: same inputs -> same Q_rand outputs
conformal.endpoint_lo: Q_rand(y_pred_dec + q_lo * sigma_hat)
conformal.endpoint_hi: Q_rand(y_pred_dec + q_hi * sigma_hat)
conformal.hi_ge_lo: true (if violated, set hi=lo)
--- Gates unchanged ---
gate.coverage_target: 0.80
gate.coverage_tol: 0.04
gate.coverage_band: [0.76, 0.84]
gate.heterosced_coverage_low: 0.70
gate.heterosced_coverage_high: 0.90
gate.heterosced_n_bins: 4
gate.ece_tol: 0.05
--- Acceptance / kill ---
accept.heterosced_gate_passes_per_split_on_test: true
accept.global_calib_coverage_in_band: true
accept.widths_non_degenerate_min_distinct: 3
kill.reject_if_rng_not_deterministic: true
kill.reject_if_global_calib_coverage_out_of_band: true
kill.reject_if_widths_degenerate: true
kill.no_param_retuning_after_results: true
--- Run discipline ---
run.execute_phase5_evaluate_times: 1
run.test_is_readout_only: true
PREREG>>>

## Rationale (not hashed)

- **Why a new CLASS of hypothesis.** Four deterministic corrections (A1, A3, P, P') have failed
  to move the binding het gate; per the reviewer the remaining next-order hypothesis is that the
  discrete-object + inclusive-containment + endpoint-quantization combination creates
  steps/asymmetry that no deterministic method can align in the late-CP regime without inflating
  slack. D1 tests exactly that by smoothing the quantizer.
- **Why D1 before D2.** D1 changes one place, preserves the pipeline, and is easy to test for
  determinism/no-leak; D2 calibrates on a soft object yet reports on the hard object, a larger
  and harder-to-defend change. The reviewer recommended D1 first and offered to simplify
  `Q_rand` to tie-only randomization (`|frac - 0.5| < eps`) if we confirm D1 - a refinement
  reserved for a future pre-registered variant, NOT applied silently here.
- **Why this is not gaming.** Exactly one variable changes (the endpoint quantizer); the seed,
  the `Q_rand` definition, and every gate threshold are fixed ex-ante and hashed; no gate is
  touched; the RNG is row-local and seed-fixed (no test-stat dependence); the run is once; kill
  criteria (incl. non-determinism and width collapse) are pre-committed.
- **`row_id` resolved (reviewer's normative decision, not an implementation detail).** The
  reviewer rejected `page_url` dependence and fixed `row_id =
  sha256(f"{station_id}|{day_local}|{cp_utc}")` over no-future, per-row-stable keys. Verified
  against the live Phase 5 panel schema (`core/contracts/phase5.py`): the panel has `date_local`
  and `cp_utc` per row; there is NO `station_id` column because this is a single-station project,
  so `station_id` is the fixed icao literal `NZWN` (`nzwn/config/station.yaml`) and `day_local =
  date_local`. The wiring step must build `row_id` from these fields and MUST NOT use the
  dataframe row index. This is settled before wiring, as the reviewer required.
