# REQ-AUD-5 normative reference (frozen)

Status: FROZEN reference. This document fixes (1) what the heteroscedasticity
coverage gate is meant to guarantee and (2) exactly how its bins are built. It
changes no method, no gate threshold, and no contract; it is a definition so the
intent cannot be re-litigated after a result. The binding numeric thresholds live
in `core/contracts/phase5.py`; the binning algorithm lives in
`core/eval/gates_phase5.py`. This file is the prose source-of-truth those two
implement.

## 1) REQ-AUD-5 intent (normative)

The gate exists to stop a degenerate but high-scoring failure mode of interval
forecasting: an emitter that buys aggregate coverage by making the *hard* rows'
intervals so wide they "always cover", while the *easy* rows stay miscalibrated.
Aggregate (pooled) coverage can sit on target while the conditional behaviour is
wrong. REQ-AUD-5 asserts the opposite property:

- **Width must track difficulty.** A wider emitted interval must correspond to a
  genuinely harder row, not to a free coverage cushion. Equivalently: coverage
  must be approximately constant across the width distribution, not rising toward
  1.0 as width grows.
- **No "always cover" tail.** The widest intervals must not be systematically
  over-covered (coverage pinned at 1.0). Over-coverage in the wide tail is the
  signature this gate is built to catch.
- **No starved narrow head.** The narrowest intervals must not be systematically
  under-covered. Both directions of conditional miscalibration fail the gate.
- **Per split, never pooled.** The property must hold within each walk-forward
  split. Pooling across splits is forbidden for the pass/fail decision, because
  pooling can average away a per-regime defect.

Concretely: bin the emitted IC80 rows by interval width into 4 width groups and
require every non-empty group's empirical coverage to lie in
`[HETEROSCED_COVERAGE_LOW, HETEROSCED_COVERAGE_HIGH] = [0.70, 0.90]`. The gate
PASSES iff every non-empty bin is in band; it FAILS if any bin is out of band.
The `mixed_in_and_out` flag marks the diagnostic case where at least one bin is
in band and at least one is out — the explicit heteroscedastic-miscalibration
signature.

What the gate is NOT: it is not an aggregate-coverage check (that is the separate
`coverage_target = 0.80 +/- 0.04` gate), and it is not a calibration-curve / ECE
check (that is Track C). REQ-AUD-5 is solely about coverage-vs-width conditional
flatness.

## 2) Het-gate binning definition (normative)

Source of truth: `core.eval.gates_phase5.heteroscedasticity_gate`. The binning is
**rank-based on distinct widths**, NOT equal-mass over rows. Exact construction
(`n_bins = HETEROSCED_N_BINS = 4`):

1. Per-row width `w = hi_int - lo_int + 1` (integer brackets; identical to the
   width used by `conformal.coverage_report`).
2. `unique_widths = numpy.unique(w)` (sorted, de-duplicated).
3. Interior probabilities `probs = numpy.linspace(0, 1, n_bins + 1)[1:-1]`; for
   `n_bins = 4` this is `[0.25, 0.50, 0.75]`.
4. Interior edges `edges = numpy.quantile(unique_widths, probs, method="linear")`
   — quantiles of the *distinct width values*, so a heavily-tied width
   distribution still yields stable, reproducible cut points.
5. Row assignment `bin_idx = numpy.searchsorted(edges, w, side="right")`, giving
   bins `0..3`.
6. Empty bins (fewer distinct widths than `n_bins`, or edge collisions) are
   dropped from the report. An all-identical-width input collapses to a single
   non-empty bin. No RNG anywhere.

Consequences that matter for reading the audit:

- Because edges are quantiles over *distinct widths* (not over rows), bin row
  counts are typically very unequal. The integer-quantized emitter produces a
  few large discrete widths held by a small number of hard rows, so the upper
  bins (bins 2 and 3) routinely carry only ~11-30 rows per split. A reported
  `coverage = 1.000` on `n ~ 11` is therefore NOT evidence of determinism — it
  is a small-sample point estimate and must be read with its binomial CI.
- Tie rule: edges are over unique widths and assignment is `searchsorted` with
  `side="right"`, so all rows sharing a width land in the same bin
  deterministically.

## 3-4) Read-only data artifact

The binomial confidence intervals per bin and the composition of the wide bins
are generated (read-only, no method change) by
`scripts/phase5_wide_bin_audit.py` into `reports/phase5_wide_bin_audit.{md,json}`.
That artifact reads the standing v1.0 normalized conformal method (the method
that remains after Track A.A1 and Track A.A3 both closed as real-but-insufficient)
and reports, per split and per REQ-AUD-5 bin: `n`, successes, coverage, the
Wilson 95% interval, and the month/CP/sigma composition of the upper (wide) bins.
