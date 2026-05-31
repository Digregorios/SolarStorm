# Preregistration: native_integer_conformal_v0 (T-9-5)

> `prereg_version = 1.0` (frozen 2026-05-31, before implementation). Phase 9 calibration.
> Guiding rule: "Do not build Polymarket. Do not build execution. Build the calibration roof in
> causal walk-forward, or honestly accept the diagnostic stopgap."

## Diagnosis this attacks

Phase 5 + T-9-3 (regime-conditional KILL) converged on: the structural late-CP IC80 over-coverage is
GLOBAL, not regime/sigma localizable, and its dominant mechanism is **calibrating a DECIMAL interval
then applying `Q` (floor(x+0.5))** - the quantize-after step adds discrete slack (+0.06..0.11 coverage
over target). Changing the conditioning axis (regime/sigma) cannot remove it. So the next move attacks
the OBJECT/MECHANIC: calibrate the integer object directly.

## Objective

Produce an integer IC80 `[lo_int, hi_int]` for Tmax by calibrating NATIVELY in integer space (no
decimal interval + `Q`), and test whether it reduces the structural over-coverage while keeping the
REQ-AUD-5 het gate honest. Point center = existing Ridge integer prediction `pred_int = Q(latent)`
(unchanged; `Q` on the POINT is fine - it is the INTERVAL we stop quantizing).

## Methods (pre-registered; evaluate both, report both)

Per split, per CP, fit on the held-out calib slice (train-only), apply on test. Walk-forward 2023/24/25.

**M1 - integer abs-residual quantile (symmetric, finite-sample):**
```
e_int      = |y_int - pred_int|              (integer errors on CALIB)
q          = the ceil((n+1)*0.80)/n-th order statistic of e_int   (integer)
IC80       = [pred_int - q, pred_int + q]
```
Pure integer; no decimal, no `Q`-after. This is essentially the `ridge_conformal_minimal` object but
evaluated here under the full GO/KILL + het gate.

**M2 - signed integer residual quantiles (asymmetric):**
```
r_int      = y_int - pred_int               (signed integer residuals on CALIB)
q_lo       = floor((n+1)*0.10)-th order stat of r_int
q_hi       = ceil((n+1)*0.90)-th order stat of r_int
IC80       = [pred_int + q_lo, pred_int + q_hi]
```
Corrects a directional bias (e.g. the cold bias) without the decimal->`Q` slack.

(Optional M3, only if cheap: discrete-PMF cumulative-mass set over the empirical-conditional
`prob_dist` - smallest integer set with mass >= calib-tuned tau. Report if implemented, else skip.)

All integer-native: the interval endpoints are integers by construction; `Q` is NEVER applied to a
calibrated decimal bound. Frozen: coverage=0.80, the two order-statistic rules above, per-(cp) calib
with pooled fallback when n < 30. No per-split tuning.

## Baselines (mandatory, same rows)

- Phase 5 v1.0 signed conformal (decimal + `Q`) - the object this is trying to beat.
- The T-9-3 regime-conditional result (for context; already KILL).

## GATE (GO to promote a native-integer method)

ALL of (reuse `core/eval/gates_phase5.heteroscedasticity_gate` unchanged, per split, never pooled):
1. Global IC80 coverage in [0.78, 0.86] in >= 2/3 splits.
2. REQ-AUD-5 het gate (per-width-quartile coverage in [0.70,0.90]) PASSES in >= 2/3 splits
   (this is the binding one Phase 5 never passed).
3. Mean IC80 width strictly LOWER than the v1.0 decimal+`Q` baseline in >= 2/3 splits (the whole
   point: remove the quantize-after slack -> tighter intervals at the same coverage).
4. No per-split tuning; deterministic; causal (calib disjoint from test).

GO = the simplest method (prefer M1, then M2) that satisfies all four.

## KILL

- Still over-covers (het gate FAIL) even native-integer -> the slack is NOT the `Q`-after step but the
  finite-sample integer granularity itself (Tmax integers are too coarse for 80% to land in band).
- Passes coverage only by NOT being tighter than v1.0 (no width gain).
- Needs per-split tuning.
If KILL: this is decisive - it means a calibrated 80% INTEGER IC is likely not recoverable with the
current point model + data granularity, and the project should formally adopt the T-9-7 diagnostic
stopgap rather than keep chasing the roof.

## Scope (files implementation may touch)

ALLOWED: `core/calibration/integer_conformal.py` (new), `scripts/evaluate_native_integer_conformal.py`
(new), `reports/calibration/native_integer_conformal_v0.{md,json}` (new). Reuse (read-only)
`ridge_band`, `training_panel`, `climatology`, `eval/metrics`, `eval/gates_phase5`,
`contracts/quantization` (Q on the POINT only).
FORBIDDEN: `core/cli/decide.py`, `core/decision/**`, Polymarket/odds, execution, any contract/threshold
change, any gate loosening, reopening the Phase 5 closure.

## What this does NOT do

No execution wiring; no change to the serving forecast path; promotion into serving is a separate
later step. Calibration experiment only.
