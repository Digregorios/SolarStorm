# Phase 5 - closure: NOT READY (2026-05-30)

> Decision (reviewer, `references/code-reviews/update.txt` 2026-05-30): Phase 5 is closed
> **NOT READY**. The IC80 / confidence calibration never passed the binding REQ-AUD-5
> heteroscedasticity gate. No further calibration tracks will be opened (stop criterion B3).
> The roadmap advances to late-spike risk + shadow-trading / realized-EV.

## What Phase 5 tried to do

Turn the Phase-4 latent point forecast into a calibrated integer IC80 bracket whose
empirical coverage is ~0.80 AND whose interval WIDTH tracks difficulty - the REQ-AUD-5
heteroscedasticity gate (every IC-width quartile must cover within `[0.70, 0.90]`, per
split, never pooled). The binding miscalibration lives in the moderately-wide, large-`n`
bin in the late-CP regime (22Z/23Z): intervals there OVER-cover (too wide for the realized
error).

## Tracks attempted (all pre-registered, hashed, one-shot; all failed the binding gate)

| track | hypothesis (one variable changed) | result on REQ-AUD-5 het gate |
|-------|-----------------------------------|------------------------------|
| v1.0  | normalized quantization-aware conformal (calibrate the integer-inclusive object) | FAIL (binding het gate) |
| A1    | global sigma winsorization to a calib-frozen percentile band | reduced wide-bin over-coverage, but het gate still FAIL |
| A3    | Mondrian conditional conformal by sigma bucket (shrunk per-bucket tails) | FAIL (`accept_a3=False`) |
| P     | difficulty axis = predictive-distribution entropy | REJECTED at calib-only sanity (`sanity_checks_pass=False`) |
| P'    | difficulty axis = quantization margin `0.5 - |frac - 0.5|` | REJECTED at calib-only sanity |
| D1    | discrete-object smoothing: endpoint quantizer `Q -> Q_rand` (unbiased randomized rounding) | FAIL (het gate); calib coverage in band, widths non-degenerate, no KILL |
| S     | tail-budget shape (S1 sym 0.10/0.10 vs S2 asym 0.05/0.15), calib-only vtest | S1 wins on shape (lower slack) but does not change the verdict; not advanced to one-shot |

Determinism, no-leak (row-local seed; `row_id = sha256(NZWN|date_local|cp_utc)`, never the
dataframe index), and hash-pinned pre-registration held throughout. One D1 contract
transcription error (a factor-2 bias in `Q_rand`) was caught and corrected PRE-execution,
with the canonical hash re-pinned in the same change-set (`contracts/phase5_amendment_trackD_d1_randomized_Q.md`).

## Useful information extracted (not wasted)

- **The over-coverage is STRUCTURAL, not a tuning miss.** Four deterministic corrections
  (A1 global scale, A3 conditional-by-sigma, P entropy axis, P' margin axis) and one
  stochastic smoothing (D1) all left the late-CP mod-wide bin over-covering. The interval
  there genuinely spans too many integers for the realized error; reshaping tails or
  smoothing the quantizer only RELABELS slack, it does not remove it.
- **Track S quantifies the slack and the best tail shape.** Calib-only vtest
  (`reports/phase5_trackS_vtest.md`): mean mod-wide slack at 22Z/23Z is S1=0.965 vs
  S2=1.577 - the SYMMETRIC budget is strictly better; the asymmetric tail makes it worse.
  So the residual is not a directional-bias problem an asymmetric interval would fix.
- **Global coverage is achievable; per-width-quartile coverage is not (yet).** D1 held
  global calib coverage in `[0.76, 0.84]` with non-degenerate widths on all splits - the
  marginal target is reachable; the CONDITIONAL (width-stratified) target is the open
  problem.
- **2023 is training-scarcity limited** (~21 months causal GFS from 2021-03-22), a distinct
  axis from the 2024 calib->test drift; both are out of scope for a pure calibration fix.
- **Late-CP (22Z/23Z) is the locus.** The CP-stratified report is where the signal is, and
  it remains useful diagnostically even though the gate is red.

## Operational decision (in force until Phase 5 is green)

1. **IC80 / confidence_score are NOT a trade gate (stay-out) in production.** Enforced in
   config: `confidence.gate_enabled_in_production: false` (`nzwn/config/model.yaml`), honored
   by `core/decision/engine.py::production_confidence_gate` (returns PASS when disabled;
   fail-safe default False). The diagnostic `confidence_gate` is unchanged for analysis.
2. **Informative / diagnostic use only.** Keep the CP-stratified coverage report, especially
   22Z/23Z, as a monitor.
3. **Advance the roadmap** to phases that measure value without perfect calibration:
   - Late-spike as a risk module (blocks / alerts).
   - Shadow trading / realized EV as the primary metric, with logs/audit and
     pre-registered thresholds.

## Reproduce

```
py -3 -m scripts.phase5_evaluate                 # v1.0 baseline verdict
py -3 -m scripts.phase5_evaluate_trackA_a1       # A1
py -3 -m scripts.phase5_evaluate_trackA_a3       # A3
py -3 -m scripts.phase5_evaluate_trackP          # P
py -3 -m scripts.phase5_evaluate_trackPprime     # P'
py -3 -m scripts.phase5_evaluate_trackD_d1       # D1
py -3 -m scripts.phase5_vtest_trackS             # S (calib-only vtest)
```
