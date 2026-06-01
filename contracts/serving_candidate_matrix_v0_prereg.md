# Preregistration: serving_candidate_matrix_v0 (T-11-9, Phase 2)

> `prereg_version = 1.0` (frozen 2026-06-01, before implementation). Decide the best POINT model per CP
> and per regime WITHOUT promoting on a single report. Predictor-only: no execution, no Polymarket, no
> calibration. The `|GFS-ECMWF|` spread is EXCLUDED from any routing/serving logic here (T-11-6 was
> FEASIBLE-CONDITIONAL with seasonal reversal; spread is reserved for T-11-8 calibration only).

## Objective

Build one consolidated comparison matrix of the candidate POINT models, on identical rows, walk-forward,
per CP and per regime, to inform (not auto-execute) a conservative serving routing.

## Candidates (same rows, same splits)

1. Ridge base (no NWP) - the floor / CP23 incumbent.
2. GFS-residual (Phase-4 residual LGBM, GFS anchor).
3. ECMWF-residual (residual LGBM, ECMWF anchor) - the T-11-5 strong CP20-22 candidate.
4. analog high-risk arm (T-9-1, GO) - blends on ex-ante non_calm days at CP23.
5. GFS+ECMWF ensemble - included ONLY as a per-CP candidate, and ONLY where it does NOT regress CP23
   (T-11-5 showed it regresses CP23). NOT a global default.

NO spread-based routing (reviewer P1). Reuse existing panels/models; nothing re-tuned.

## Protocol

Walk-forward. Use the FULL 2023-2025 splits for Ridge/GFS/analog where data allows; for ECMWF-residual
and the ensemble, restrict honestly to the ECMWF overlap window (2024-03..2025-12, >= 2 folds) and LABEL
that the ECMWF rows are a shorter window (do not compare an ECMWF metric on 2 folds against a 3-fold
Ridge metric without saying so). Per-split train-only climatology; causal NWP; ex-ante regime c30=train
P30 (canonical, NOT P70, NOT truth).

## Matrix (the deliverable, per split + pooled-as-labelled-note)

Rows = candidates; columns = MAE, RMSE, bracket-match, RPS. Sliced by: per CP (20/21/22/23, with CP20-22
RIGIDLY separated from CP23); per regime (calm, non_calm, high_delta_06, non_calm AND high_delta_06).

## DECISION RULES (recommendation, not auto-promotion)

- Per CP, name the best candidate by MAE then RPS, but only call a winner when it does NOT regress vs the
  incumbent and the margin is outside trivial noise.
- CP20-22 vs CP23 are decided SEPARATELY. ECMWF-residual may be recommended as the CP20-22 candidate
  (strong T-11-5 signal) WITHOUT being promoted at CP23.
- CP23 stays CONSERVATIVE: Ridge / GFS-residual / analog, unless a candidate wins clearly with NO
  regression and NOT only on the short ECMWF window.
- Do NOT degrade calm/stable days (any recommended routing must hold or improve them).
- The output is a RECOMMENDED routing table + an explicit "winner-shopping" guard note; actual serving
  wiring is Phase 3 (separate, gated).

## Anti winner-shopping (mandatory)

Report must state: same rows per comparison; window differences labelled; no per-split cherry-picking; a
candidate "wins" a CP only if it wins in >= 2/3 (or >= 2/2 in the short window) folds, not one lucky fold.

## Scope

ALLOWED: `scripts/evaluate_serving_candidate_matrix.py` (new), `reports/serving/candidate_matrix_v0.{md,json}`
(new). Reuse ridge_band, residual_lgbm, training_panel, analog_high_risk, late_warming_risk, eval/metrics.
FORBIDDEN: `core/cli/decide.py`, `core/decision/**`, Polymarket/odds, execution, any calibration code, any
spread-based routing, any contract/threshold change, any model re-tuning.

## What this does NOT do

No serving wiring (Phase 3), no calibration, no promotion by itself. It produces the evidence matrix +
a conservative recommended routing, gated.
