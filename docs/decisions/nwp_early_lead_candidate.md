# Decision memo: NWP early-lead candidate (T-11-3)

> `memo_version = 1.0`. Turns the T-10-2 GO into an organized model decision. NOT a promotion, NOT
> execution. Predictor-only.

## What T-10-2 established

`reports/nwp_early_lead_point_gain.md`: the NWP-residual (Phase 4 LGBM) improves the Tmax POINT over
Ridge-only in degC AND RPS, concentrated at early leads: mean dMAE -0.197/-0.156/-0.105 at 20/21/22Z,
smaller -0.035 at 23Z, in 3/3 splits, no CP23 regression, reconciling the phase4 bracket-match curve.
So the early-lead point gain is real (not bracket-edge luck).

## The decision to make (not auto-promote)

Does NWP-residual become the candidate POINT model per CP? The honest position:

- **CP20/21/22 (early leads):** NWP-residual is the strongest candidate point model - the gain is
  material (~0.1-0.2 degC MAE) and consistent 3/3 splits. RECOMMEND: NWP-residual is the candidate
  point model at CP20-22.
- **CP23 (operational):** the NWP gain is small (-0.035 degC) and Ridge is already strong; the analog
  arm (T-9-1) also targets CP23 non_calm days. RECOMMEND: keep Ridge (+ analog arm candidate) at CP23
  for now; do NOT switch CP23 to NWP-residual on a 0.035 degC edge until a consolidated comparison.
- **Per-CP rule is legitimate** (the model can differ by CP) since the lead-to-peak horizon differs;
  this is not overfitting, it is using NWP where it demonstrably helps.

## Why NOT auto-promote now

1. A final comparison MATRIX is missing: Ridge vs NWP-residual vs analog-arm vs (future)
   non_calm/high-delta residual, on identical rows, per CP, in MAE/RMSE/bracket-match/RPS. Promotion
   should follow that matrix, not a single pairwise GO.
2. The ECMWF backfill (T-11-1 GO) may change the NWP picture: a 2-model ensemble could improve the
   point further AND finally create a real spread axis. Promoting GFS-only NWP-residual now risks
   re-work once ECMWF lands.
3. T-9-1 analog and NWP-residual may overlap on the same non_calm days; the matrix must show whether
   they are additive or redundant before both are promoted.

## Recommended sequence

1. Land the ECMWF full backfill (T-11-1 GO -> 2024-03..2025-12) and re-fit the NWP-residual as a
   2-model ensemble.
2. Build ONE consolidated per-CP comparison matrix (the four candidates above) - a new task, gated.
3. Promote per CP from that matrix: likely NWP-residual at CP20-22, Ridge/analog at CP23, revisited
   after ECMWF.
4. Only after a serving point model is chosen does any downstream (calibration revisit if spread is
   real; execution remains frozen regardless) get reconsidered.

## Scope

Doc-only decision memo. No code, no promotion, no execution/Polymarket, no contract change. The actual
consolidated comparison matrix and any serving-path change are separate, gated steps.
