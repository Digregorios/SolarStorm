# core_predictor_status - the 7-question core audit (per CP, per regime, degC)

- CP set ['20:00', '21:00', '22:00', '23:00'] (operational `23:00`). Read-only. Execution layer (Kelly/EV/decision-line/brackets) FROZEN pending this. Regime masks group the evaluation by truth-derived strata (legitimate for a diagnostic breakdown; not a feature). Climatology refit per split (train-only).

## The 7 questions (objective verdicts)

1. **Best baseline?** CP-dependent. At early CPs climatology wins (e.g. CP20 climatology MAE ~1.78 vs persistence ~2.94); at the operational CP23 persistence wins (MAE ~1.32 vs 1.78). So the bar a model must clear is max(persistence, climatology), per CP.
2. **Does the model beat it?** YES. Ridge beats the best baseline by MAE in 3/3 splits at ALL four CPs. At CP23: Ridge MAE 0.7 vs persistence 1.322 vs climatology 1.782; bracket-match 0.441 vs 0.255/0.164. Reconciles with model_metrics_summary CP23 (0.419/0.460/0.441) and the REQ-MET-4 kill criterion (PASS 3/3).
3. **Which CPs?** All of 20/21/22/23 UTC. MAE improves monotonically toward EOD (~0.96 -> 0.88 -> 0.79 -> 0.70 degC) - the model adds the most value at earlier leads where persistence is weakest (persistence MAE ~2.9 at CP20).
4. **Which regimes?** Ridge's edge is concentrated, not uniform: it CRUSHES persistence on material late-warming days (MAE 0.868 vs 2.545); it roughly TIES persistence on stable days (0.601 vs 0.594); and it LOSES on days where Tmax already occurred at CP (0.9 vs 0.0 - persistence IS the truth there, Ridge adds noise). Slightly better in winter than summer.
5. **Typical error in degC?** At the operational CP23: MAE ~0.7 degC, RMSE ~1.021 degC (was previously unreported - this audit fills that gap). Per-CP MAE/RMSE in the table below.
6. **Is the distribution calibratable or useless?** Partially. Phase 5 closure: GLOBAL coverage is achievable, but the conditional (width-stratified) heteroscedasticity gate REQ-AUD-5 never passed -> IC80/confidence are DIAGNOSTIC-ONLY, fenced from trading. The point forecast is strong; the calibrated interval is the genuine open problem (see reports/phase5_closure.md). The ensemble-evolution ridge_conformal_minimal gives a defensible per-CP IC80 (coverage 0.86-0.91) as a stopgap, but is not a passed conditional-calibration.
7. **Which feature adds signal?** From the Phase 3 no-temperature ablation + permutation importance: the temperature anchors carry most of it - k_cp, last_obs_tmp_c_int and the climatology anchor. The no-temperature feature set is materially weaker (see reports/phase3.md Ridge no-temp column); i_t_obs permutation importance on last_obs is 0.075-0.097 at CP23. NWP adds genuine pooled forward skill at earlier leads (Phase 4, phase4_ready=True).

## Per-CP point forecast (MAE/RMSE degC + bracket-match), walk-forward mean over splits

| CP | model | MAE | RMSE | bracket-match | splits Ridge beats best baseline (MAE) |
|----|-------|-----|------|---------------|------------------------------------------|
| 20:00 | ridge | 0.96 | 1.321 | 0.336 | 3/3 |
| 20:00 | persistence | 2.941 | 3.594 | 0.131 |  |
| 20:00 | climatology | 1.782 | 2.235 | 0.164 |  |
| 21:00 | ridge | 0.884 | 1.221 | 0.355 | 3/3 |
| 21:00 | persistence | 2.502 | 3.067 | 0.141 |  |
| 21:00 | climatology | 1.782 | 2.235 | 0.164 |  |
| 22:00 | ridge | 0.789 | 1.117 | 0.398 | 3/3 |
| 22:00 | persistence | 1.907 | 2.371 | 0.17 |  |
| 22:00 | climatology | 1.782 | 2.235 | 0.164 |  |
| 23:00 | ridge | 0.7 | 1.021 | 0.441 | 3/3 |
| 23:00 | persistence | 1.322 | 1.755 | 0.255 |  |
| 23:00 | climatology | 1.782 | 2.235 | 0.164 |  |

## Per-regime (operational CP), MAE + bracket-match, Ridge vs persistence

Averaged over splits at the operational CP. Regimes group by truth strata (diagnostic).

| regime | mean n | Ridge MAE | pers MAE | Ridge bm | pers bm |
|--------|--------|-----------|----------|----------|---------|
| all | 365 | 0.7 | 1.322 | 0.441 | 0.254 |
| stable (no material late-warming) | 229 | 0.601 | 0.594 | 0.478 | 0.406 |
| material late-warming (truth-kcp>=2) | 136 | 0.868 | 2.545 | 0.376 | 0.0 |
| summer (DJF) | 90 | 0.815 | 1.431 | 0.402 | 0.233 |
| winter (JJA) | 92 | 0.616 | 1.33 | 0.5 | 0.272 |
| tmax already reached at CP (kcp==truth) | 93 | 0.9 | 0.0 | 0.256 | 1.0 |

_See reports/core_predictor_status.md prose for the 7-question verdicts._
