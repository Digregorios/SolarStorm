# Preregistration: two_model_spread_feasibility_v0 (T-11-6)

> `prereg_version = 1.0` (frozen 2026-06-01, before implementation). Phase 11. Read-only FEASIBILITY -
> NO calibrator, NO execution, NO calibration change. Rule: "Does a real two-model NWP spread explain
> Tmax error? Measure it honestly; only a GO here can later justify reopening calibration."

## Why now

ECMWF is landed (T-11-4/T-11-7). T-11-5 KILLed ECMWF auto-promote on the POINT but flagged a strong
CP20-22 point signal. The reviewer's route: use ECMWF first as a DIFFICULTY / SPREAD axis. Before T-9-6
there was only one causal model, so spread was identically zero. Now `|GFS - ECMWF|` is a REAL physical
disagreement signal - the first genuinely new calibration axis since the closure.

## The feasibility question

Does a causal, CP-available two-model spread predict the realized integer error? Spread candidates
(all causal, available at CP):
- `abs(GFS_t2m_at_cp - ECMWF_t2m_at_cp)` (per-CP two-model disagreement);
- `abs(GFS_maxtraj - ECMWF_maxtraj)` and/or `nwp_t2m_maxtraj_spread_c` (trajectory-anchor spread);
- std across the two models where available.
Target error signals: `abs(y_int - pred_int)` (pred = the Ridge point), bracket-miss (0/1),
large-error indicator (`abs error >= 2`).

## Protocol

Walk-forward within the ECMWF overlap window (2024-03..2025-12, >= 2 expanding folds; honestly shorter
than 2023-2025). Per CP (20/21/22/23), per fold, on TEST: build both models' causal CP value via
`select_nwp_v1` (run_time <= cp-60min) for GFS and ECMWF on the SAME rows; compute each spread
candidate; compute the Ridge point error. Report Spearman(spread, abs_error), and mean abs_error by
spread QUARTILE (Q1..Q4). Also break out by ex-ante regime (non_calm via c30=train P30) and
high_delta_06, especially CP20-22. Thresholds (quartile edges) fit on TRAIN only.

## GATE (FEASIBLE)

ALL of:
1. Spearman(spread, abs_error) POSITIVE in >= 2 folds (for at least one spread candidate).
2. Q4-spread mean abs_error > Q1-spread mean abs_error (error rises with spread) in >= 2 folds.
3. The signal holds per CP, especially CP20-22 (where T-11-5 showed NWP value).
4. Causal + same rows + train-only thresholds; reproducible.

If FEASIBLE -> recommend a follow-up that USES spread, ranked: (a) as a difficulty axis for a future
INTEGER-NATIVE / CQR calibrator (T-11-8), and/or (b) as a conditional point-routing signal. The diagnosis
agent decides "calibration, point routing, both, or neither".

## NOT FEASIBLE

- Spread does not correlate with error (Spearman ~0 or negative), or error does not rise across
  quartiles, or coverage is thin. Then the two-model spread is not a usable difficulty signal at NZWN
  with this window -> do NOT build a spread-conditioned calibrator; record it and move on.

## Scope

ALLOWED: `scripts/evaluate_two_model_spread_feasibility.py` (new, read-only),
`reports/calibration/two_model_spread_feasibility.{md,json}` (new). Reuse read_snapshots, select_nwp_v1,
ridge_band, training_panel, late_warming_risk, eval/metrics.
FORBIDDEN: `core/cli/decide.py`, `core/decision/**`, Polymarket/odds, execution, any calibrator build in
this front, any contract/threshold change, any REQ-AUD-5 touch. Feasibility only.

## What this does NOT do

No calibrator, no point routing, no serving change, no calibration reopen. It only answers: is the
two-model spread a real difficulty signal, and where? A GO here is a PRECONDITION (not a commitment) for
later spread-conditioned work.
