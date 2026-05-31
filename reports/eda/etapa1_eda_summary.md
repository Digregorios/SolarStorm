# Etapa 1 EDA - signal inventory (read-only) for Etapa 2 precursor audit

Consolidates the 3 parallel read-only EDA tracks (month/decade, morning/delta, regime-path) into
a ranked inventory of CAUSAL precursors of material late-warming (`k_eod - k_cp >= 2`, base rate
**0.377**). All cuts use only pre-CP information; targets are audit-only. This is
hypothesis-generation: it tells Etapa 2 (`late_warming_precursor_audit`) which features to test
with walk-forward + lift gates, and which to drop. NO model was built; nothing is promoted here.

Sources: `reports/eda/month_decade_*.md`, `reports/eda/morning_predictors.md`,
`reports/eda/delta_from_min.md`, `reports/regime/regime_path_eda.md`,
`reports/regime/foehn_clearing_rain_recovery_eda.md`.

## Headline: precursors DO exist (the causal-horizon question is answered)

The open question from the bias audit was whether ANY pre-CP signal anticipates the post-CP
warming, or whether it is pure causal-horizon noise. **Answer: real precursors exist**, strongest
in the wind/regime and morning-slope axes. This validates continuing the ensemble evolution (the
project is not a dead end) and tells us where the lift is.

## Tier 1 - strongest, large-n, promote to Etapa 2 precursor audit

| signal | cut | P(material_lw) | lift vs 0.377 | n | source |
|--------|-----|----------------|---------------|---|--------|
| wind quadrant change S->N | overnight S -> CP N | 0.64 | 1.70 | 103 | regime |
| `delta_06_to_cp` (morning slope) | high vs low | 0.50 vs 0.28 | up to 1.33 | full | morning |
| wind quadrant at CP = S | southerly | 0.29 | 0.76 (SUPPRESS) | 857 | regime |
| foehn-like proxy (NW + warming + drying) | True | 0.44 | 1.16 | 913 | regime |
| rain persistence rainy->rainy->rainy | path | 0.18 | 0.49 (SUPPRESS) | 267 | regime |

- The two strongest are DIRECTIONAL and protective signals are as valuable as enhancing ones:
  southerly-at-CP and persistent-rain SUPPRESS late-warming (good for confident low forecasts).
- `delta_06_to_cp` (morning warming slope) is the best single thermal-trajectory precursor;
  season-dependent (JJA rho 0.36, MAM 0.27, ~0 in DJF).

## Tier 2 - real but conditional / season-specific / smaller-n

- `t_06` / `tmin_so_far_06` COLD mornings weakly predict late-warming (rho -0.13; within-JJA
  -0.42) - but it is a LEVEL/room effect, useful as a regime indicator not a direct upside cue.
- Month x decade for LATE-WARMING in winter: July D1 material-lw 0.533 vs D2 0.267 (double), Apr
  D2 0.271 vs D3 0.443, Nov D1 0.183 vs D2 0.383. Real but noisy (n~60/cell). Candidate as a
  spike-risk MODIFIER, not a Tmax-level feature.
- E->S wind change (n=33, lift 1.45) and a few regime paths (`dry->mild->dry` 0.71;
  `rainy->mild->cloudy` 0.80) - high lift but small n; treat as exploratory.

## Tier 3 - drop / no useful lift (do NOT spend Etapa 2 budget here)

- `overnight_recovery` (rho 0.02), `delta_00_06` (rho -0.09): noise for late-warming.
- `tmax_d_minus_1`: strong for Tmax LEVEL (rho 0.81) but ZERO for late-warming (-0.01). Keep for
  the center/level arm, not the spike-risk arm.
- Decade-of-month for Tmax LEVEL or Tmax HOUR: spread < 1.5 degC / <= 1h; already captured by
  climatology + month_sin/cos. Do NOT add as a level feature.
- `clearing_proxy` / `rain_stopped`: counter-intuitively SUPPRESS (post-frontal southerly cooling
  dominates solar re-heating). Not an upside cue; possibly a weak protective one.

## Two corrections to prior assumptions (honest)

1. "Cold start = more upside" is **REJECTED**: `Spearman(delta_min_to_cp, remaining_after_cp) =
   +0.20` - high-energy days warm both before AND after CP. Upside is not a cold-start rebound.
2. Ridge has **no material month x decade bias** (worst cell -0.63, by-decade ~0). The bias-audit
   finding stands: Ridge's cold bias is specific to the late-warming REGIME, not a seasonal cell.
   So the fix is a regime/precursor-conditioned adjustment, not a per-month recalibration.

## Hand-off to Etapa 2 (precursor audit) - pre-registered feature shortlist

Test these with walk-forward lift gates (>=2/3 splits), as causal features for
`material_late_warming` (NOT as forecast inputs of the level model):
```
wind_quadrant_at_cp            (S protective; N enhancing)
wind_quadrant_change_overnight_to_cp   (S->N strongest)
delta_06_to_cp                 (morning slope; season-interacted)
foehn_like_proxy               (broad, N/W+warming+drying)
rain_persistence / rain_path   (rainy->rainy suppresses)
t_06 / tmin_so_far_06          (regime/level indicator, season-interacted)
month x decade                 (winter spike-risk MODIFIER only, expect noisy)
```
Explicitly de-scoped (Tier 3): overnight_recovery, delta_00_06, decade-for-level, tmax_d-1 for
spike. Season interaction (esp. JJA vs DJF) must be a stratum in the audit, not ignored.
