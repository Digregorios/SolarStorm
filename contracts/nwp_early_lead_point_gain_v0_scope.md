# Scope: nwp_early_lead_point_gain (T-10-2)

> `scope_version = 1.0` (frozen 2026-05-31). Phase 10 (post-calibration), predictor-only.

## Honest context (avoid duplication)

`reports/phase4.md` ALREADY documents the per-CP NWP forward-skill curve in BRACKET-MATCH: NWP delta
+0.11/+0.10/+0.13 at 20Z, degrading smoothly to ~+0.04 at 22Z, in 3/3 splits - a clear GO pattern.
So the *existence* of early-lead point gain is established. The GENUINE GAP (same as core_predictor_status)
is that it is reported in bracket-match only, NOT in degC MAE/RMSE or RPS per CP. This front fills that
gap, it does NOT re-discover the gain.

## Objective

Consolidate the NWP early-lead POINT gain per CP (20/21/22 vs 23) in degC MAE, RMSE, bracket-match AND
RPS, Ridge-only vs Ridge+NWP-residual, walk-forward 2023/24/25. Reuse the Phase-4 panel + residual LGBM.

## Deliverable

`scripts/evaluate_nwp_early_lead.py` (reuse phase4 panel/model loading) + `reports/nwp_early_lead_point_gain.{md,json}`
with a per-CP table: CP | Ridge MAE | Ridge+NWP MAE | dMAE | dRMSE | dBM | dRPS | splits-improved.

## GATE (GO = confirm + quantify the early-lead point gain in degC)

- NWP improves MAE OR RPS at CP20-22 in >= 2/3 splits, AND does not materially regress CP23
  (MAE increase <= 0.02 degC at 23Z). Reconcile bracket-match with phase4.md (sanity).
- KILL/NEGATIVE: if the degC view contradicts the bracket-match gain (e.g. BM up but MAE worse),
  report that honestly - it would mean the gain is bracket-edge luck, not a real degC improvement.

## Scope

ALLOWED: `scripts/evaluate_nwp_early_lead.py` (new), `reports/nwp_early_lead_point_gain.{md,json}` (new).
Reuse (read-only) the Phase-4 panel build + residual LGBM + eval/metrics (mae/rmse/rps).
FORBIDDEN: decide.py, decision/**, Polymarket/odds, execution, any contract change, any calibration
re-opening. No NWP backfill / network. If NWP snapshots are unavailable for a split, report thin coverage
honestly.
