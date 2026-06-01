# Changelog

Notable contract/method/feature changes across the project. Versioned method changes are
tamper-evident via the canonical PREREG sha256 pinned in `core/eval/preregistration.py`. For the
narrative path (attempts, failures, decisions) see `docs/PROJECT_JOURNEY.md`.

## [phase11:T-11-9 Phase2] - 2026-06-01 - serving candidate matrix (conservative per-CP routing)

`scripts/evaluate_serving_candidate_matrix.py` (prereg v1.0). Consolidated comparison of 5 candidate
POINT models (Ridge, GFS-residual, ECMWF-residual, analog high-risk arm, GFS+ECMWF ensemble) on identical
rows, walk-forward, per CP and per regime - to INFORM a conservative routing, not auto-promote. Reviewer's
route adjustment honored: the `|GFS-ECMWF|` spread is EXCLUDED from all routing (T-11-6 FEASIBLE-CONDITIONAL).
3-agent pipeline (my prereg + impl + anti-winner-shopping review) + my re-verification.

**Recommended routing (recommendation, NOT promotion - Phase 3 wires it):**
- CP20/21/22 -> ECMWF-residual (wins 2/2 folds, large margin, no calm regression; e.g. CP20 MAE 0.69/0.55
  vs Ridge 1.03/0.80).
- CP23 -> Ridge (incumbent best among the conservative set; ECMWF only wins CP23 in 1/2 folds, so the
  conservative rule keeps Ridge). The ensemble wins CP23 both folds but is EXCLUDED from CP23 per the
  T-11-5 regression finding + prereg rule.
CP20-22 decided separately from CP23; ECMWF metrics honestly labelled as the shorter 2-fold window
(2024-03..2025-12) vs the 3-fold full-window context for Ridge/GFS/analog. Anti-winner-shopping: same
rows, windows labelled, winner only if >=2/2 (short) or >=2/3 (full) folds. Review PASS 10/10.

**Carried Phase-3 risk (flagged):** ECMWF availability at inference - the CP20-22 routing needs a graceful
fallback (to GFS-residual or Ridge) for missing/delayed ECMWF runs. Suite 367 green. No execution/calibration.
`reports/serving/candidate_matrix_v0.md` (+ `_review.md`).

## [phase11:T-11-6] - 2026-06-01 - two-model spread feasibility FEASIBLE-CONDITIONAL (seasonal reversal)

`scripts/evaluate_two_model_spread_feasibility.py` (prereg v1.0, read-only). Tested whether the real
two-model spread `|GFS_t2m - ECMWF_t2m|` at the CP predicts the Ridge integer error, walk-forward in the
ECMWF window (2024-03..2025-12, 2 folds). 3-agent pipeline (my prereg + impl + anti-leakage review +
decision diagnosis) + my own re-verification.

**VERDICT FEASIBLE-CONDITIONAL.** The lenient any-CP gate was technically met (Spearman positive 2/2,
Q4>Q1 2/2), BUT I added a cross-fold sign-consistency check that exposes the real story: the
spread->error sign REVERSES by season. Fold1 (warm) non_calm/high_delta Spearman +0.15..+0.19 at CP20-22
(high spread = harder); Fold2 (winter) -0.14..-0.22 at CP20-21 (high spread = EASIER). CP20/CP21 flip
sign across folds; CP22/CP23 are consistent. So the headline is downgraded from FEASIBLE to
FEASIBLE-CONDITIONAL - not a usable STANDALONE signal and NOT for point routing.

Decision (diagnosis agent, concurred): the spread is a candidate **calibration difficulty axis ONLY**,
usable solely if INTERACTED with season/regime inside a learned calibrator (T-11-8 CQR), where it can be
exploited where it helps and suppressed where it reverses. NOT point routing (the seasonal flip would
make correct calls in summer and wrong calls in winter with no ex-ante discriminator). REQ-AUD-5 stays
unchanged; any future calibrator using this signal must still pass it (no auto-reopen). Short window (22
months), no p<0.05 - honest caveats recorded. Anti-leakage review PASS (causal both models, train-only
edges, ex-ante c30=P30, same rows, no P70 drift). Suite 367 green. No execution/calibration change.
`reports/calibration/two_model_spread_feasibility.md` (+ `_review.md`, `_diagnosis.md`).

## [phase11:T-11-5] - 2026-06-01 - ECMWF/ensemble point gain KILL (honest; strong CP20-22 signal flagged)

`scripts/evaluate_ecmwf_ensemble_point_gain.py` (prereg `contracts/ecmwf_ensemble_point_gain_v0_prereg.md`
v1.0). Compared Ridge / GFS-residual / ECMWF-residual / GFS+ECMWF ensemble on identical rows, within the
ECMWF overlap window (2024-03..2025-12, 2 expanding folds - honestly shorter than the 2023-2025 splits).
Built via the subagent pipeline (my prereg + impl + anti-leakage review + my own re-verification).

**VERDICT KILL** (per-candidate gate): no single NWP candidate passes all of gates 1-3.
- ecmwf_residual: gate1 CP20-22 PASS (2/2), gate2 CP23-no-regress PASS, gate3 pocket FAIL (1/2).
- ensemble: gate1 PASS (2/2), gate2 FAIL (CP23 regress +0.15), gate3 pocket PASS (2/2).

**Two corrections I made during verification (did not rubber-stamp the agents):**
1. The impl had a real GATE-LOGIC BUG - gate 2 (CP23 non-regression) was evaluated GLOBALLY across all
   candidates, so the ensemble's CP23 regression failed the gate for everyone. The prereg is PER-CANDIDATE
   (prefer ecmwf_residual). I rewrote the gate to evaluate each candidate independently.
2. The anti-leakage review agent then claimed the fix yields "GO, ecmwf_residual passes all 5 gates" -
   that was WRONG: ecmwf_residual FAILS gate 3 (pocket gain only 1/2 folds; GFS-residual is already
   strong in the pocket in H2). The corrected per-candidate logic gives the honest KILL.

**Honest signal (not buried under KILL):** ECMWF-residual is a strong CP20-22 POINT improver (gate 1
PASS 2/2, MAE gains ~-0.10..-0.35 vs best existing, larger than GFS-residual). It just does not ROBUSTLY
win the non_calm/high_delta pocket across both short-window folds. This is a "do not auto-promote on a
2-fold window, but a strong candidate for the T-11-3 consolidated per-CP matrix on a longer window" -
not "ECMWF is useless". Anti-leakage otherwise clean (ex-ante regime canonical c30=P30, causal NWP,
train-only thresholds, same rows). Suite 367 green. No execution/calibration change.
`reports/nwp/ecmwf_ensemble_point_gain.md` (+ `_review.md`).

## [phase11:T-11-8 PLANNED] - 2026-06-01 - CQR / LightGBM-quantile prereg (new calibration hypothesis)

Planning-only (no code). Registered `contracts/cqr_lightgbm_quantile_v0_prereg.md` (prereg_version 1.0)
as a PLANNED, research-backed calibration hypothesis. CQR changes the OBJECT LEARNED - adaptive quantile
bounds (LightGBM quantile loss) conformalized on the BOUNDS - rather than a post-hoc band around a
center. This reopens calibration as a NEW hypothesis WITHOUT contradicting the closure (which killed the
center+band paradigm) and WITHOUT loosening REQ-AUD-5. Honest caveat recorded: the integer-granularity
limit (T-9-5) persists, so CQR may improve shape yet still not pass the het gate. Queue: execute LAST,
after T-11-5 (ECMWF point gain) + T-11-6 (two-model spread), fed the best feature set (obs+GFS+ECMWF+
spread) - CQR is underestimated if run before the new NWP features exist. NOT executed this session.

## [phase11:T-11-7] - 2026-06-01 - ECMWF daily-per-CP coverage audit GO (base hardened)

`scripts/ecmwf_daily_cp_coverage_audit.py` (read-only, no fetch): the reviewer asked to upgrade the
backfill's monthly-sample audit to a FULL daily-per-CP audit before any modeling. Every local date
2024-03-01..2025-12-31 x 4 CPs was checked via `select_nwp_v1` (`run_time <= cp-60min`). The full audit
CAUGHT a 1-day boundary gap the monthly sample missed - 2024-03-01 needs the 2024-02-29 12Z run, which
predated the backfill START. Closed it by fetching the 2 boundary runs (2024-02-29 00Z/12Z). **GO:
671/671 days causal at all 4 CPs (100%), 0 gaps**, consistent lead_h (8/9/10/11h = prev-day 12Z run
feeding 20/21/22/23Z). ECMWF data is solid for T-11-5 (point gain) / T-11-6 (two-model spread). No
model/calibration/execution. `reports/nwp/ecmwf_full_daily_cp_coverage.md`.

## [phase11:T-11-4] - 2026-05-31 - ECMWF full backfill GO (2nd causal NWP source landed)

`scripts/ecmwf_backfill_full.py` (controlled, idempotent, resumable, rate-limited with retry/backoff,
per-invocation `--max-runs` cap so no single run times out). Backfilled causal ECMWF IFS HRES
single-runs for 2024-03-01..2025-12-31, cycles 00Z+12Z. **GO: 1342/1342 runs (100%), 0 failures**, and
the causal-coverage audit confirms a selectable run (`run_time <= cp-60min`) at all 4 CPs in every one
of the 22 months. No GRIB/eccodes; every row carries run_time/valid_time/lead_h. Data + audit only -
no model, no calibration, no execution. Snapshots in `artifacts/raw/nwp` (gitignored).
`reports/nwp/ecmwf_backfill_full.md`. Unblocks T-11-5 (ECMWF point gain / 2-model ensemble) and T-11-6
(two-model spread feasibility - the first real NWP-spread axis).

## [phase11:ecmwf+targeted] - 2026-05-31 - T-11-1 ECMWF pilot GO, T-11-2 prereg, T-11-3 decision memo

Data-first round (reviewer-directed): bring new causal NWP data + design the targeted predictor, no
calibration / no execution / no Polymarket.

- **T-11-1 ecmwf_causal_backfill_pilot (`scripts/ecmwf_backfill_pilot.py`,
  `reports/nwp/ecmwf_backfill_pilot.md`): GO.** Small controlled pilot (12 ECMWF single-runs across a
  dense 3-day sequence before two contrasting target CPs, autumn + winter 2024). Live fetch clean 12/12,
  NO GRIB/eccodes, every row carries `run_time_utc`/`valid_time_utc`/`lead_h`; `select_nwp_v1` picks a
  CAUSAL run at both CP23 targets (prev-day 12Z run, lead 11h, run_time <= cp-60min). The first attempt
  was a PAUSE (sparse run-time sampling forced the selector to reach across months) - fixed by fetching
  a dense local sequence; the PAUSE->GO iteration itself validated the gate. Next: full backfill
  2024-03..2025-12 (~2680 calls, ~22 partitions), accept split-1 asymmetry, cross-check before promote.
  Snapshots in `artifacts/raw/nwp` (gitignored).
- **T-11-2 non_calm_high_delta_model_v0 prereg (`contracts/...prereg.md`, prereg_version 1.0):
  DESIGN-FIRST.** Turns the T-10-3 error map into ONE pre-registered hypothesis (H1 = regime-split
  residual on the EX-ANTE non_calm AND high-delta_06 pocket), with a GO gate that requires the pocket
  gain to EXCEED T-9-1's analog arm. Not implemented yet (frozen design so the later build is not a
  random search); alternatives explicitly deferred.
- **T-11-3 nwp_early_lead_candidate decision memo (`docs/decisions/nwp_early_lead_candidate.md`):**
  the T-10-2 GO -> NWP-residual is the CANDIDATE point model at CP20-22, keep Ridge/analog at CP23; NO
  auto-promotion without a consolidated per-CP comparison matrix (Ridge vs NWP-residual vs analog vs
  future regime-residual), which should wait for the ECMWF backfill (2-model ensemble may change it).

Suite 367 green; all guards pass. Predictor/data/design only; execution + calibration unchanged.

## [phase10:post-calibration] - 2026-05-31 - 4 fronts: ECMWF feasibility, NWP early-lead, error map, IC fence

Calibration is settled-with-stopgap and CLOSED as an active trail. Four parallel post-calibration
fronts (scopes mine, subagent impl, my independent re-verification; predictor/analysis/governance only,
execution frozen).

- **T-10-1 ecmwf_causal_ingest_feasibility (`reports/nwp/ecmwf_causal_ingest_feasibility.md`):
  CONDITIONAL GO.** The code ALREADY supports ECMWF (`select_nwp_v1` is model-parameterized); what is
  missing is DATA, not code. Causal ECMWF single-runs are reachable for 2024-03..2025-12 (~2680 calls,
  ~22 monthly partitions, no GRIB/eccodes). Condition: accept the split-1 asymmetry (ECMWF only for
  dates >= 2024-03) + run the T-OPN-5a cross-check before promoting. Next action recorded; not executed.
- **T-10-2 nwp_early_lead_point_gain (`scripts/evaluate_nwp_early_lead.py`,
  `reports/nwp_early_lead_point_gain.md`): GO.** Consolidated the existing phase4 per-CP NWP gain in
  degC. NWP+residual improves MAE AND RPS at 20/21/22Z in 3/3 splits (mean dMAE -0.197/-0.156/-0.105,
  dRPS improves), CP23 non-regression PASS, and the degC view RECONCILES with the phase4 bracket-match
  curve (not bracket-edge luck). NWP is a real point-improver at early leads.
- **T-10-3 forecast_error_taxonomy (`scripts/evaluate_error_taxonomy.py`,
  `reports/model_error_taxonomy.md`): delivered (the failure map).** Top remaining ex-ante error pockets
  by share of total |error|: regime_non_calm (73%, MAE 0.732, n=765), delta06_high (47%), delta06_mid
  (38%), southerly (33%); highest per-row error on s_to_n transition days (MAE 0.949) and January (0.989);
  Tmax-already-reached shows a strong +0.83 over-prediction bias (post-hoc). **NOTE: I caught + fixed a
  definitional drift the subagent introduced** - it had used non_calm = risk>=P70 (top 30%); corrected to
  the canonical calm_day_filter c30 = P30 (calm = bottom 30%, non_calm = top 70%), consistent with
  T-9-1/T-9-3. The fix moved non_calm to the #1 pocket (as expected, since it is ~70% of days).
- **T-10-4 diagnostic_ic_display_contract (`docs/decisions/diagnostic_ic_display_contract.md`):
  delivered.** Doc-only governance fence for the diagnostic IC (mandatory banner, per-CP coverage,
  never a trade gate, retired when REQ-AUD-5 passes >=2/3). Parent: the T-9-7 stopgap memo.

Direction: the failure map says the biggest ex-ante actionable error is concentrated in the non-calm /
high-delta_06 regime - exactly where T-9-1's analog arm operates and where a 2nd NWP source (T-10-1)
would help most. Suite 367 green; all guards pass.

## [phase9:calibration-fronts] - 2026-05-31 - T-9-5 KILL (decisive), T-9-6 NOT FEASIBLE, T-9-7 stopgap adopted

Three parallel calibration fronts (reviewer-directed; preregs/scopes mine, subagent impl, my
independent re-verification). All predictor/calibration-only; execution stays frozen.

- **T-9-5 native_integer_conformal_v0 (`contracts/native_integer_conformal_v0_prereg.md`,
  `core/calibration/integer_conformal.py`): KILL - and DECISIVE.** Calibrated the integer object
  directly (M1 symmetric |residual| quantile; M2 signed residual quantiles), NO decimal->`Q`. It STILL
  over-covers / fails the REQ-AUD-5 het gate in >=2/3 splits. **This refutes the `Q`-after-decimal
  hypothesis**: the structural slack is the integer GRANULARITY itself (Tmax integers are too coarse for
  80% to land in-band without over-covering). Useful positive: M2 (signed) is strictly TIGHTER than the
  v1.0 decimal+`Q` baseline in 3/3 splits (width 4.25/4.00/3.75 vs 4.27/4.28/3.77) and at 2025 reaches
  cov 0.876 with het PASS - but cannot hit the het gate in 2/3. het gate reused UNCHANGED [0.70,0.90].
- **T-9-6 nwp_spread_sigma feasibility (`scripts/evaluate_nwp_spread_sigma.py`): NOT FEASIBLE.** The
  local NWP archive holds only ONE causal model (NCEP GFS), so spread/disagreement columns are
  identically zero (zero variance) - no usable difficulty axis. Revisiting requires ingesting a second
  causal NWP source (e.g. ECMWF IFS). Read-only feasibility; no calibrator built.
- **T-9-7 stopgap (`docs/decisions/calibration_stopgap_2026-05-31.md`): adopted.** Formalizes
  `ridge_conformal_minimal` (per-CP IC80, over-covers ~0.86-0.91) as DIAGNOSTIC-ONLY: not passed
  calibration, never a trade gate (`gate_enabled_in_production: false` stays), shown only with a
  "diagnostic IC, over-covers, not for sizing" banner; retired when a method passes REQ-AUD-5 >=2/3.

**Strategic conclusion (honest):** a calibrated 80% INTEGER IC is likely NOT recoverable with the
current point model + integer granularity. Three independent attacks (regime axis T-9-3, native-integer
object T-9-5, NWP-spread axis T-9-6) all failed or were infeasible. Calibration is now
SETTLED-WITH-STOPGAP; the only remaining lever is a 2nd causal NWP model (T-9-6 revisit). Suite 367 green.

## [phase9:T-9-3] - 2026-05-31 - conditional_calibration_v0 KILL (honest; the "roof" stays open)

The "roof": tried to fix the structural late-CP IC80 over-coverage (Phase 5's binding REQ-AUD-5
failure) by conditioning conformal on the EX-ANTE regime (calm/non_calm from the late-warming risk
model, train-P30 c30 cutpoint) - a NEW axis vs Phase 5's sigma-bucket Mondrian (A3). Prereg
`contracts/conditional_calibration_v0_prereg.md` (prereg_version 1.0), with an explicit honest prior
that the over-coverage is likely structural/irreducible. Built via the 3-agent pipeline (my prereg +
subagent impl/review + my independent re-verification).

**VERDICT KILL** (expected per the prior): G1 global coverage in [0.78,0.86] FALSE (0.93/0.91/0.91);
G2 het-quartile gate FALSE all splits AND per-regime coverage out of band (calm 0.96/0.94/0.93,
non_calm 0.91/0.90/0.90 - BOTH over-cover); G3 no width inflation (deltas +0.13/+0.28/+0.21 < +0.5,
so it is not gaming coverage). **Diagnosis: the over-coverage is GLOBAL + structural; conditioning on
calm/non_calm does NOT isolate the slack to one regime** (worst in calm at 0.945, but non_calm also
over-covers). The ~0.91 global coverage is the documented v1.0 `Q`-after-decimal integer-quantization
inflation (+0.06..0.11), which the conditional method inherits. This CONFIRMS and reinforces the Phase
5 closure ("reshaping relabels slack, does not remove it"). Anti-leakage review PASS 10/10 (het gate
reused unchanged; regime ex-ante; calib disjoint from test). Suite 367 green.

Next calibration candidate (recorded, not opened): NWP-spread sigma as the difficulty axis, OR accept
`ridge_conformal_minimal` (per-CP IC80, coverage 0.86-0.91) as the operational stopgap. Phase 5 closure
NOT reopened. Predictor/calibration-experiment only; no execution change.
`reports/calibration/conditional_calibration_v0.md` (+ `_review.md`).

## [phase9:T-9-1] - 2026-05-31 - analog_high_risk_arm_v0 GO (predictor improvement; ex-ante gate)

First Phase-9 (predictor-improvement) arm. Prereg `contracts/analog_high_risk_arm_v0_prereg.md`
(prereg_version 1.0). Blends an analog point estimate into Ridge ONLY on EX-ANTE non-calm days
(predicted late-warming risk >= train-P30 c30 cutpoint - causal, available at CP; NEVER the
truth-derived late-warming stratum, which stays diagnostic-only). `analog_pred = k_cp +
Laplace-smoothed neighbor mean(tmax_int-k_cp)` over K=50 train-pool neighbors (date<test,
train-only standardizer), `blend = Q((1-w)*ridge + w*analog)`, `w = 0.5*clip(analog_conf/0.20,0,1)`,
frozen constants (no per-split tuning).

Built via a 3-agent pipeline (I wrote the prereg; subagents did impl + anti-leakage review; I
re-verified independently). **VERDICT GO**: non-calm MAE improves 3/3 splits
(0.727->0.704, 0.718->0.704, 0.700->0.693); non-calm bracket-match improves 2/3 (tied 2025);
aggregate improves or holds every split (within tolerance). Anti-leakage review PASS 10/10 incl
the critical ex-ante-gate check; full suite 367 green; all guards pass.

**HONEST CAVEAT:** the gain is REAL but SMALL (conservative confidence-weighted blend, w<=0.5).
Consistent with `core_predictor_status` - the point forecast is already strong; the bigger open
gap is the DISTRIBUTION/interval (conditional calibration, T-9-3), not the point. Predictor-only:
no execution/Polymarket/IC change. `reports/analog/analog_high_risk_arm_v0.md` (+ `_review.md`).

## [reorientation:core-first] - 2026-05-31 - FREEZE the execution layer; prove the core predictor

Course-correction (reviewer-directed): the project was drifting into execution/presentation
sophistication (Kelly, EV, decision-line, brackets, resolver) on top of a predictor whose core
evidence was scattered. New standing rule:

> **No new Polymarket/trading/execution delivery until a report shows the Tmax model beats strong
> baselines in causal walk-forward.** The execution layer (Kelly/EV/sizing, decision-line, brackets,
> resolver, trading states) is FROZEN except for the minimum needed to keep existing contracts/tests green.

Delivered `reports/core_predictor_status.md` answering the 7 core questions, consolidating the
validated Phase 0-4 evidence and FILLING the genuine gaps the prior reports lacked:
- **MAE/RMSE in degC** added to `core/eval/metrics.py` (was absent; test `test_metrics_degc.py`).
- **Per-CP point forecast** (20/21/22/23 UTC), not only the operational CP, via
  `scripts/core_predictor_status.py` (reuses `build_training_panel` + `fit_ridge_band`, per-split
  train-only climatology, walk-forward 2023/24/25).
- **Per-regime** breakdown (stable / material late-warming / summer / winter / Tmax-already-reached).

Findings (honest, incl. the unflattering): Ridge beats the best baseline by MAE in 3/3 splits at ALL
four CPs (CP23 MAE ~0.70 degC, RMSE ~1.02, bracket-match 0.441 - RECONCILES with model_metrics_summary
0.419/0.460/0.441 and REQ-MET-4). The edge is CONCENTRATED: crushes persistence on late-warming days
(MAE 0.87 vs 2.55), ties on stable days (0.60 vs 0.59), and LOSES on Tmax-already-reached days (0.90
vs 0.00 - persistence is the truth there). Distribution: point forecast strong, but the calibrated
interval (Phase 5 conditional coverage) remains the open problem. Read-only audit; no model/threshold/
contract change. Suite 367 green.

## [fix:decision-line] - 2026-05-31 - live decide robustness + sizing/engine coherence

Surfaced while producing a real `decision_line.json` for reviewer audit (a resolved Wellington
market, 2026-05-31). Three real defects fixed (no gate/contract loosened):

- **Boundary-price crash**: `size_book`/`expected_value` correctly reject price not in (0,1), but
  the live `decide` CLI fed them resolved-market prices (winner at 1.0, losers at ~0.0005) and the
  `ValueError` was caught by a blind `except Exception` and mis-reported as `odds_status=unavailable`.
  Now `size_book` and the CLI SKIP degenerate prices (resolved / no live quote) -> `NO_TRADE_RESOLVED`.
- **Blind except**: the odds fetch (`snapshot_live`) is now isolated in its own `try/except`; the
  `decide`/`size_side` per-bracket loop runs in the `else` block so a genuine bug there RAISES
  instead of masquerading as `odds_status=unavailable`. The fetch except is narrowed to
  `(ConnectionError, TimeoutError, ValueError, KeyError, OSError)` with an `odds_unavailable:<Type>` note.
- **Sizing<->engine incoherence**: `size_book` chose the best-EV side INDEPENDENTLY of `engine.decide`,
  so a bracket could read `NO_TRADE_RESOLVED` yet carry `ev>0, stake=1.0`. Sizing now FOLLOWS the
  engine state (the pre-registered state machine is the single source of truth): EV/Kelly/stake are
  computed only for the side the engine chose (OPPORTUNITY_ASSYMETRIC->BUY_YES, BUY_NO->BUY_NO), else 0.
  An explicit `side` field (BUY_YES|BUY_NO|null) is now emitted per bracket for auditability.

Validation: the proof is the regression suite - `test_resolved_market_no_crash_and_coherent` (boundary
fixture), `test_sizing_follows_engine_state` (BUY_NO sizes NO, no-edge -> side null/stake 0), and
`test_size_side_buy_no_semantics_from_decision_line` (size_side takes p_yes, converts to 1-p_yes for
NO). A future open market (2026-06-02) was inspected ONLY as an odds-ingestion / decision-line
plumbing smoke test - NOT model validation: the nowcast needs same-day intraday info available at CP,
and that date fell back to climatology. Note: `OPPORTUNITY_ASSYMETRIC` is a frozen (misspelled)
pre-registered identifier, kept as-is (no unmigrated rename). Suite 363 green.

## [ensemble-evolution] - 2026-05-31 - incremental track (NOT a from-scratch v1)

Decision: evolve the current forecaster into a layered probabilistic ensemble incrementally
(each arm gated by walk-forward), NOT a big-bang rewrite. Assessment + reconciled queue in
`reports/ensemble_pivot_assessment.md`. Quarantine = source of IDEAS not code; PolyWeather =
engineering recipes (DEB blend, hourly/phase corrector, TAF-as-suppression). Steps so far:

- **ridge_conformal_minimal** (`core/models/ridge_conformal.py`): per-CP IC80 = 80% conformal
  quantile of the Ridge's OWN integer abs-residuals, hierarchical fallback (cp_specific ->
  global_cp_pool -> insufficient_data). Fixed to TRUE split-conformal (held-out calib) + per-split
  train-only climatology after two reviewer P0 corrections. Historical per-CP IC80 coverage
  0.86-0.91, non-degenerate widths -> IC calibration is DEFENSIBLE. NOT Phase 5.
- **late_warming_bias_audit** (n=1095 OOS): Ridge near-unbiased overall (mean_err -0.018); cold
  bias is NARROW + proportional to post-CP warming (+0.39@mag2 .. +2.35@mag4) and shared by ALL
  centers (causal-horizon limit, not Ridge-specific). The 4 fresh days were a real failure regime,
  not adversarial.
- **Etapa 1 EDA (read-only)**: causal-eligible PRE-CP precursors of material late-warming
  (k_eod-k_cp>=2, base 0.377) DO exist. Tier-1: wind quadrant change S->N (lift 1.70), morning
  slope delta_06_to_cp, southerly-at-CP (suppress), rain-persistence (suppress). Rejected
  "cold-start = upside". `reports/eda/etapa1_eda_summary.md`.
- **Etapa 2 late_warming_precursor_audit (walk-forward)**: 3/4 primary precursors survive the gate
  (delta_06_to_cp enhance, southerly + rain-persistence suppress, all PASS 3/3); S->N high-lift
  but small-n; t_06 FLIPPED OOS (rejected). Verdict GO. `reports/spike/late_warming_precursor_audit.md`.
- **Etapa 5 risk_model_v0 + v0.1** (`core/models/late_warming_risk.py`, prereg
  `contracts/late_warming_risk_v0_1_prereg.md` prereg_version 1.0): causal pre-CP logistic +
  isotonic. v0 GO=False (4/5 gates; top-decile lift 1.38/1.62/1.39 < 1.4). v0.1 re-gated on bucket
  separation: GO=False (g3 high>=1.35x base fails) - but the LOW protective bucket is robust
  (~0.13-0.22 vs base ~0.38). Net: a reliable CALM-DAY detector, NOT a sharp high-risk hunter.
  s_to_n did not help. NO gate loosened; stays diagnostic-only. `reports/spike/late_warming_risk_v0*.md`.
- **calm_day_filter_v0** (prereg `contracts/calm_day_filter_v0_prereg.md` prereg_version 1.0,
  `scripts/calm_day_filter_v0_evaluate.py`): re-frame the robust LOW signal as a protective
  calm-day filter (reviewer-directed). **GO=True** - calm days (predicted risk < train P30) have
  obs-rate 0.22/0.13/0.21 vs base 0.38/0.38/0.36 (<= 0.65x), precision(no late-warming|calm)
  0.78/0.88/0.79 (>= 0.75), Brier < base 3/3. Diagnostic flag only (no IC/center change yet);
  high-risk detection deferred to Etapa 3 (analogs). `reports/spike/calm_day_filter_v0.md`.
- **Etapa 3 analog_retrieval_audit** (prereg `contracts/analog_retrieval_audit_prereg.md`
  prereg_version 1.0): causal k-NN (K=50, train-only pool date<test, no target/k_eod in distance).
  Predictive gates PASS 3/3 incl the FOCUS g4 non-calm high-risk lift 1.42/1.36/1.34 (>=1.25) and
  g3 top-decile lift ~2.1 (vs 1.38 from the logistic); PR-AUC 0.64-0.67 vs base ~0.37. Formal
  GO=False only on g5 (analog_quality bucketing did not separate Brier - a HOW-to-score-adherence
  metric, not predictive capability). **Analogs demonstrably capture the high-risk side the
  logistic could not** -> leading high-risk arm candidate. No gate loosened.
  `reports/analog/analog_retrieval_audit.md`.
- **analog_quality_v0.1** (prereg `contracts/analog_quality_v0_1_prereg.md` prereg_version 1.0):
  operationalizes the only failing analog gate (g5). Verified the v0 code matched the prereg
  distance vector (7 feats incl rain_persistence_path - the reviewer's flagged divergence was a
  paste artifact). Same retrieval; only the adherence metric changes. **`analog_confidence` =
  |P_analog - base| PASSES g5 3/3** (high-confidence bucket Brier 0.165-0.175 vs 0.221-0.229,
  lift 2.2-2.6 vs ~1.0-1.3); effective_n and weighted_mean_dist fail. With g1-g4 (v0) + g5 now
  resolved, the analog high-risk arm is ELIGIBLE for a (separately gated) build.
  `reports/analog/analog_quality_v0_1.md`.

## [live-metar] - 2026-05-30 - Live observation fetch (pipeline gap fixed)

- **Added** `core/ingest/metar_live.py`: fetch raw METAR from aviationweather.gov
  (`?ids=<ICAO>&format=raw&hours=N`, 30-min cadence), resolve `DDHHMMZ` to full UTC, parse into
  the canonical observation schema via the shared `parse_observations` (single source of truth
  for integer temperature), and `merge_observations(historical, live)` with ts dedup. Tests:
  `tests/unit/test_metar_live.py`. Verified live (191 rows to 2026-05-30 17:30Z).
- **Added** `scripts/backtest_may2026.py`: clean backtest 2026-05-27..30 on merged history+live.
- **Rationale:** an intraday forecaster must pull current obs; the frozen IEM CSV ends
  2026-05-27. Reuses the historical parser so live and historical rows are identical in schema.

## [cli-serving] - 2026-05-30 - ingest-live command + forecast --model flag

- **Added** `ingest-live` CLI: fetch+merge current METAR (verified: 112322 merged rows to
  2026-05-30 18:00Z, 100% parsed) - the live-ingestion bottleneck is RESOLVED.
- **Added** `forecast --model {empirical|ridge}`: default stays `empirical` (NOT switched
  silently); `--model ridge` trains the Phase-3 band-aware Ridge and emits its prob_dist.
- **Conclusion (documented in `docs/PROJECT_JOURNEY.md`):** the backtest showed live ingestion
  was blocking; with that fixed, the ACTIVE bottleneck is that the CLI default still serves the
  Phase-2 baseline (1/4 backtest bracket-match floor) rather than a production model (~0.44).
  Conceptual fork left open: Ridge is live-ready but failed corr_diff; the stronger NWP-residual
  (phase4_ready) is live-gated on a live GFS anchor fetch. Promoting the default is a deliberate
  separate step.

## [phase8-scope-fix] - 2026-05-30 - Odds are LIVE-only (no historical backtest)

- **Corrected scope** across `requirements.md` (REQ-MET-1/5, REQ-DEC-3/4), `contracts/objective.md`,
  `design.md` 10.1, and `README.md`: Polymarket odds are live context captured at the forecast CP,
  NOT a historical dataset. Removed `EV_realized_on_test_split` as the primary metric and the
  equity-curve backtest. OFFLINE promotion metric is odds-free `max bracket_match_when_traded s.t.
  coverage`; EV/Kelly are computed LIVE.
- **Added** `core/ingest/odds.py` (deterministic event slug/URL + Gamma API live snapshot ->
  `ContractRange` brackets + prices + sha256; verified vs the real Wellington event, 11 brackets),
  `core/decision/sizing.py` (live `expected_value`, capped `kelly_fraction`, `size_side`,
  `size_book`), and `ExecutionContract.position_sizing='fractional_kelly'` + `kelly_cap`. Tests:
  `test_odds_ingest.py`, `test_sizing.py`.
- **tasks.md:** T-8-5 (equity-curve backtest) REMOVED; T-8-6 (economic_edge) deferred to live;
  T-8-1/8-2 reframed to live confirmation/snapshot.

## [phase8-decision] - 2026-05-30 - Decision engine + market map + shadow sim + live CLI

- **Added** `core/decision/engine.py::decide` (6 states per design 10: low-confidence stay-out,
  BLOCK_BUY_NO_LATE_SPIKE, NO_TRADE_RESOLVED, OPPORTUNITY_ASSYMETRIC, BUY_NO, no-edge),
  `core/decision/market_map.py` (`p_yes` over a `ContractRange`, normalization validator),
  `core/decision/shadow_exec.py` (single-trade PnL/what-if simulator, EXECUTION_VERSION 1.0),
  `contracts/execution.md` + `core/contracts/execution.py` (pydantic). Tests:
  `test_decision_engine_full.py`, `test_market_map.py`, `test_shadow_exec.py`,
  `test_execution_contract.py`.
- **Added** `core/cli/decide.py` (registered as `decide`): forecast prob_dist -> market_map ->
  live odds snapshot -> decide + size_book -> decision row JSON; odds-unavailable handled
  gracefully. Confidence/spike marked uncalibrated so no un-validated gate blocks.
- **Phase-5-not-ready guard:** `confidence.gate_enabled_in_production: false`;
  `production_confidence_gate` no-ops while red. Transversal: `tools/contract_version_guard.py`
  (T-X-2), `scripts/postmortem_monthly.py` (T-X-3).

## [phase7-spike] - 2026-05-30 - Late-spike risk module (REQ-SPK-3 PASS 3/3)

- **Added** `core/spike/features.py` (14 causal features, `ts_utc < cp_utc` guard),
  `core/spike/model.py` (binary LightGBM + isotonic, seed 42), `scripts/spike_evaluate.py`.
- **Result:** PR-AUC 0.947/0.948/0.953 vs base prevalence ~0.81-0.85, bootstrap CI95 lo >
  prevalence every split; ECE 2.4-4.5%. Integrated `-spike_risk` as the 6th confidence phi and
  `BLOCK_BUY_NO_LATE_SPIKE` in the decision engine.

## [phase6-ar] - 2026-05-30 - AR(7) online residual corrector (partial)

- **Added** `core/online/ar.py` (AR(7) equal-weight, strictly-past, json state with
  backup-before-write + (date,cp) dedupe; REQ-MOD-5/REQ-OPS-5). `ar_online.enabled=false` default.
  Tests: `test_ar_online.py`. T-6-3 DM-test deferred (was blocked by the Phase 5 stream).

## [phase5-closure] - 2026-05-30 - Phase 5 CLOSED NOT READY (stop criterion B3)

- After v1.0/A1/A3/P/P'/D1/S all failed the binding REQ-AUD-5 het gate, Phase 5 is closed
  NOT READY. IC80/confidence are diagnostic-only and fenced from trading
  (`confidence.gate_enabled_in_production: false`). See `reports/phase5_closure.md`. The S
  tail-budget calib-only vtest (S1 sym beats S2 asym on slack) confirmed the over-coverage is
  structural, not directional. No further calibration tracks.

## [phase4-nwp] - 2026-05-29..30 - NWP residual learning (phase4_ready = True)

- **Added** the GFS s3_grib causal anchor path: `core/ingest/grib_idx.py` (eccodes-free byte-range
  logic, CI-tested), `scripts/gfs_grib_decode.py` (OFFLINE eccodes decode; in-memory
  `codes_new_from_message` after a Windows temp-file bug), `scripts/gfs_s3_backfill.py`,
  `core/features/nwp.py::select_max_trajectory_anchor`, `core/models/residual_lgbm.py`.
- **Anchor amendment v1.1** (NWP_SOURCE_VERSION 1.0->1.1, MODEL_VERSION bump): max-of-trajectory
  over a forward Tmax-hour window of the single causal run (design 4.5.2.1), replacing the
  single-hour anchor. Panel + `phase4_evaluate` re-anchored on GFS s3_grib.
- **Pre-registration with teeth:** `contracts/phase4_preregistration.md` (criterion_version 1.1)
  hashed as `PHASE4 ... 9a0a2a1b...` and asserted at runtime; `corr_diff` DEMOTED to diagnostic;
  acceptance = paired ablation (LGBM obs+NWP vs obs-only), CI95 lo>0 in >=2/3.
- **Split-1 rescue:** probed AWS `noaa-gfs-bdp-pds` depth (earliest 2021-03-22), backfilled
  2021-2022 so split-1 trains -> kept the >=2/3 rule (no drop, no amendment, no recompute).
- **Result:** paired-ablation pooled 3/3 (CI95 lo>0), per-CP 1/3 (2024), REQ-AUD-2 0 violations,
  phase4_ready = **True**. Reports: `reports/phase4.{md,json}`, `h0_verdict.json`.

## [phase5-trackD-d1] - 2026-05-30 - EXECUTED (het gate FAIL; no KILL)

- Wired + ran after the transcription-correction below. `PHASE5D1_COMMITTED_SHA256 =
  7e14915e6e7b51f701aad79f736c65cf12303d038a866cdf14e245ed3e4ccb4b` (recomputed after fixing the
  biased `Q_rand` formula). `Q_rand` (unbiased `P(ceil)=t`) wired at the two endpoints only
  (`core/contracts/quantization.py`, `core/calibration/conformal.py::apply_normalized_conformal_qrand`).
  One-shot run_id `20260530T135256Z`: het gate FAIL on all splits (over-coverage structural),
  calib in-band, widths non-degenerate, A/B-seed stable -> ACCEPT D1 = False, KILL = False.
  Tests: `test_trackD_d1_qrand.py`. The PROPOSED entry below documented the pre-wiring state; the
  factor-2 transcription error in the originally-frozen formula was corrected PRE-execution and
  the hash re-pinned in the same change-set.

## [phase5-trackD-d1] - 2026-05-30 - PROPOSED (docs-before-code; NOT wired, NOT executed)

### Phase 5 amendment Track D.D1 - randomized rounding / tie-breaking at quantization (conformal_method_version 1.0 -> 2.0, q_version 1.0 -> 1.1)

- **Contract:** `contracts/phase5_amendment_trackD_d1_randomized_Q.md` (criterion_version 1.0;
  amends `contracts/phase5_preregistration.md` v1.0 - a NEW CLASS of hypothesis,
  discrete-object smoothing, NOT a continuation of A1/A3/P/P'; the sigma proxy, gates, windows,
  and `c`-rule are all unchanged).
- **Canonical PREREG sha256:**
  `033e80dc346e40e7097724d08be9f8aea2fd28d06971e548dba7a641275cc2f7`
  (to be pinned as `PHASE5D1_COMMITTED_SHA256` in the SAME change that wires the method; NOT
  yet wired into `core/eval/preregistration.py`).
- **Reason (reviewer direction, `references/code-reviews/update.txt`):** four deterministic
  corrections - A1 (global scale), A3 (Mondrian by sigma bucket), P (entropy difficulty axis),
  P' (quantization-margin difficulty axis) - all failed to move the binding het gate (A1/A3
  insufficient; P/P' rejected at the calib-only sanity gate). The reviewer directed moving to a
  DIFFERENT CLASS: the next-order hypothesis is that {discrete object + inclusive containment +
  endpoint quantization} creates steps/asymmetry no deterministic method can align in the
  late-CP regime without inflating slack. D1 is the recommended first variant (over D2
  soft-containment) because it touches a single place and is easy to test for determinism /
  no-leak.
- **Change (exactly one variable):** replace the deterministic `Q(x) = floor(x + 0.5)` at the
  two decimal endpoints with a reproducible randomized rounding `Q_rand(x; global_seed, row_id,
  endpoint_side)` - for `t = frac(x)` and a deterministic `u ~ Uniform(0,1)`, round up with
  probability linear in `t` so `E[Q_rand(x)] = x` and the tie at `0.5` is smoothed.
  `global_seed = 20260530` fixed; `row_id = sha256(station_id|day_local|cp_utc)` from no-future
  stable keys; `lo`/`hi` decorrelated. The score, sigma proxy, GLOBAL `(q_lo, q_hi)`, `c`-rule
  + grid, gates, windows, and splits are unchanged.
- **ASCII note:** the reviewer's template uses `Q` with a combining tilde and an "approximately
  equal" glyph; both are transliterated (`Q_rand`, `~=`) for the repo's ASCII-only source, with
  no change of meaning; the canonical hash is over the ASCII text.
- **Invariants / kill (pre-registered):** `hi >= lo` (fallback `hi = lo`), int endpoints,
  determinism given seed, calib global in-band, widths non-degenerate. KILL on non-deterministic
  RNG, calib out-of-band, or width collapse; no seed / `Q_rand` / floor / `c`-rule re-tuning
  after results.
- **`row_id` resolved (reviewer normative decision, update.txt 2026-05-30):** drop `page_url`;
  use `row_id = sha256(f"{station_id}|{day_local}|{cp_utc}")` over no-future, per-row-stable
  keys, with the seed mixing `(global_seed, row_id, endpoint_side)` and optionally `split_name`;
  the dataframe/panel row index is FORBIDDEN. Verified against the live panel schema
  (`core/contracts/phase5.py`): `date_local` and `cp_utc` exist per row; single-station project
  has no `station_id` column, so `station_id` is the icao literal `NZWN`
  (`nzwn/config/station.yaml`) and `day_local = date_local`.
- **Status:** PROPOSED only. Per update.txt the reviewer authorized registering D1 as PROPOSED
  and updating it with the normative `row_id` definition now; wiring + the single one-shot run
  require EXPLICIT separate approval (Passo 3 of D1). No open questions remain before wiring.

## [phase5-trackPprime] - 2026-05-30 - EXECUTED (proxy rejected at sanity gate; one-shot NOT run)

### Phase 5 amendment Track P' - quantization margin (distance-to-threshold) as the difficulty axis (conformal_method_version 1.0 -> 1.4)

- **Contract:** `contracts/phase5_amendment_trackPprime_quantization_margin.md`
  (criterion_version 1.0; amends `contracts/phase5_preregistration.md` v1.0 - a SEPARATE
  branch off the v1.0 baseline, NOT a continuation of A1/A3/P; entropy, winsorization,
  Mondrian, and randomization are all explicitly excluded).
- **Canonical PREREG sha256:**
  `e4fb58abb8ce63b67527ba4b906c6ab783506220e27c75023a91cc63db07c4e4`
  (pinned as `PHASE5PP_COMMITTED_SHA256`; asserted at run startup).
- **Reason (reviewer direction, `references/code-reviews/update.txt`):** Track P (entropy)
  was rejected at the calib-only monotonicity sanity gate - the model's OWN emitted
  distribution does not rank-order its integer error in the late-CP regime. The reviewer
  directed opening Track P' BEFORE Track D, because the REQ-AUD-5 bottleneck is a real
  operational regime (late CP 22:00Z/23:00Z, moderately-wide large-`n` bin) with no evidence
  of an inevitable discrete-object straddle that only RNG could fix; a better difficulty axis
  is a smaller, more auditable change than randomizing the discrete object.
- **Change (exactly one variable):** `sigma_hat = 0.5 - |frac - 0.5|` where
  `frac = y_pred_dec - floor(y_pred_dec)` - the distance of the decimal forecast to the `.5`
  rounding boundary of `Q(x) = floor(x + 0.5)`, oriented so LARGER = closer to the boundary =
  harder. RNG-free, always defined, label-invariant, depends on `y_pred_dec` only; floored at
  calib P1. The score form, GLOBAL `(q_lo, q_hi)`, `c`-rule + grid, `Q`, gates, windows, and
  splits are unchanged.
- **MANDATORY read-only sanity checks BEFORE the one-shot (calib-only, per split, binding):**
  (1) Spearman `rho(sigma_hat, |y_true_int - Q(y_pred_dec)|)` positive and `>= 0.10`; (2) no
  per-CP collapse - `>= 3` distinct `sigma_hat` per CP, explicitly 22:00 and 23:00; (3) the
  reviewer's recommended FOCUS check, adopted as binding: the same Spearman restricted to the
  22:00 + 23:00 calib rows, positive and `>= 0.10` (a proxy that does not order difficulty in
  the regime where the problem lives is rejected). A failed check rejects the proxy and opens a
  new hypothesis; the one-shot is NOT run. Thresholds frozen in the hashed block.
- **Auditability (reviewer-required, no threshold change):** for the 22:00+23:00 focus subset
  per split the report emits `n_subset`, the `|error_int|` distinct-value count (tie
  diagnostic), and an AUXILIARY read-only Kendall `tau-b`; tau-b never overrides the binding
  focus Spearman pass/fail.
- **Result (run_id `20260530T123033Z`):** the margin proxy FAILED the binding GLOBAL
  monotonicity sanity check on ALL three splits - Spearman `rho(sigma_hat, |error_int|)` =
  `0.0105` / `-0.0108` / `0.0009` (near zero, negative on 2024), each far below the `0.10`
  floor. The per-CP distinct check PASSED everywhere (89-90 distinct margins per focus CP - the
  axis is not collapsed). The focus check marginally passed on 2023 (`0.1010`) but failed on
  2024/2025 (`0.0414` / `0.0571`); the auxiliary Kendall `tau-b` (`0.0795` / `0.0304` /
  `0.0471`) corroborates the weakness. So the distance-to-`.5`-boundary does NOT rank-order the
  model's integer error: this is the PRE-REGISTERED expected failure mode (integer error is
  driven by model BIAS / a shifted center, not by rounding instability), caught BEFORE the
  one-shot by design. Per discipline the single `phase5_evaluate` one-shot was NOT run (the test
  split was never touched), the proxy is REJECTED on honest terms, and nothing was re-tuned.
  ACCEPT P' = False, KILL = True. See `reports/phase5_trackPprime.{md,json}` and
  `audits/20260530T123033Z/phase5/`.
- **Follow-up:** per the pre-registration the next step is a DIFFERENT pre-registered hypothesis
  - either a second difficulty proxy (the reviewer's listed alternative `1 - max_prob`, or
  another axis) or Track D (randomized/smoothed discrete object) - NOT a tweak to the margin
  definition, orientation, floor, or sanity thresholds. Two difficulty-axis proxies (entropy,
  then quantization margin) have now been rejected at the calib-only sanity gate without
  touching the test split; both the distribution-derived axis (Track P) and a
  distribution-free, object-coupled axis (Track P') carry no usable difficulty signal in the
  late-CP regime, which further strengthens the case for Track D. Awaits the reviewer's next
  determination in `references/code-reviews/update.txt`.
- **Run discipline:** wiring (`PHASE5PP_COMMITTED_SHA256` + `assert_phase5pp_preregistration_committed`)
  + unit tests + the sanity-gated `phase5_evaluate` happened in one change-set under autopilot
  authorization (update.txt); test is readout only; no parameter, floor, sanity-threshold, or
  `c`-rule re-tuning after results.

## [phase5-trackP] - 2026-05-30 - EXECUTED (proxy rejected at sanity gate; one-shot NOT run)

### Phase 5 amendment Track P - predictive-distribution uncertainty as the difficulty axis (conformal_method_version 1.0 -> 1.3)

- **Contract:** `contracts/phase5_amendment_trackP_predictive_uncertainty.md`
  (criterion_version 1.0; amends `contracts/phase5_preregistration.md` v1.0 - a SEPARATE
  branch off baseline; NOT a continuation of A1/A3, neither winsorization nor Mondrian is
  bundled in).
- **Canonical PREREG sha256:**
  `215c29d34d582cf619d2766e69b5e55cb9c452a68e89e1613619d71aef759b85`
  (pinned as `PHASE5P_COMMITTED_SHA256`; asserted at run startup).
- **Reason:** A1 (global scale) and A3 (conditional by sigma bucket) both ran one-shot and
  both failed the het gate on every split, while KEEPING `sigma_hat = sqrt(p50_var)` fixed.
  The read-only REQ-AUD-5 audit (`reports/phase5_wide_bin_audit.md`) localized the binding
  over-coverage to bin 1 (mod-wide, large `n`; Wilson 95% CI excludes 0.90 - structural,
  not noise) and showed the wide rows are exclusively the late CPs (22:00Z/23:00Z). The
  limiting factor is the DIFFICULTY AXIS, not the correction on top of it.
- **Change (exactly one variable):** `sigma_hat = uncertainty(prob_dist)`, fixed to Shannon
  entropy in nats `- sum_k p_k ln p_k` (label-invariant, discrete-stable; reviewer chose
  this over raw `std`, which can saturate in the late-CP regime). Always defined; floored at
  a calib-frozen P1. The score form, GLOBAL `(q_lo, q_hi)`, `c`-rule + grid, `Q`, gates,
  windows, and splits are unchanged. No Mondrian, no winsorization.
- **Reviewer-required MANDATORY read-only sanity checks BEFORE the one-shot:** (1) Spearman
  `rho(sigma_hat, |y_true_int - Q(y_pred_dec)|)` on calib, per split, positive and `>= 0.10`;
  (2) no per-CP collapse - calib `sigma_hat` has `>= 3` distinct values per CP, explicitly
  for 22:00 and 23:00. A failed check rejects the proxy and opens a new hypothesis; the
  one-shot is NOT run. Thresholds frozen in the hashed block.
- **Result (run_id `20260530T044216Z`):** the entropy proxy FAILED the binding monotonicity
  sanity check on ALL three splits - Spearman `rho(sigma_hat, |error_int|)` = `0.0414` /
  `0.0663` / `0.0049`, each POSITIVE but each well below the `0.10` floor. The per-CP
  distinct check PASSED (89-90 distinct entropy values per CP, including 22:00/23:00 - the
  axis is not collapsed). So the model's emitted predictive distribution does NOT rank-order
  its own integer error: entropy is not a usable difficulty axis here. This is the
  PRE-REGISTERED expected failure mode (band-aware softmax `tau` flattening `prob_dist`),
  caught BEFORE the one-shot by design. Per discipline the single `phase5_evaluate` one-shot
  was NOT run (the test split was never touched), the proxy is REJECTED on honest terms, and
  nothing was re-tuned. ACCEPT P = False, KILL = True. See `reports/phase5_trackP.{md,json}`
  and `audits/20260530T044216Z/phase5/`.
- **Follow-up:** the next step is a DIFFERENT pre-registered hypothesis - either another
  difficulty proxy (Track P') or Track D (randomized/smoothed discrete object, update.txt
  Passo 4) - NOT a tweak to the entropy definition, floor, or sanity threshold. The fact that
  the model's OWN distribution carries no difficulty signal in the late-CP regime strengthens
  the case for Track D.
- **Run discipline:** wiring (`PHASE5P_COMMITTED_SHA256` + `assert_phase5p_preregistration_committed`)
  + unit tests + the sanity-gated `phase5_evaluate` happened in one change-set after explicit
  reviewer approval (update.txt Passo 3); test is readout only; no parameter, floor,
  sanity-threshold, or `c`-rule re-tuning after results.

## [phase5-a3] - 2026-05-30 - EXECUTED (insufficient; Track A closed)

### Phase 5 amendment Track A.A3 - Mondrian conditional conformal by sigma bucket (conformal_method_version 1.0 -> 1.2)

- **Contract:** `contracts/phase5_amendment_trackA_a3.md` (criterion_version 1.0; amends
  `contracts/phase5_preregistration.md` v1.0 - a SEPARATE branch off baseline, NOT a
  continuation of A1; A1's winsorization is not bundled in).
- **Canonical PREREG sha256:**
  `ee0ac6f232490b749eaac27cbb974a58446d4b6db15fc96be607ae5a8b87e411`
  (pinned as `PHASE5A3_COMMITTED_SHA256`; asserted at run startup).
- **Reason:** Track A.A1 (sigma winsorization) ran one-shot, no leak, no gate-moving, and
  reduced widest-bin over-coverage only in part - bins 2-4 still over-cover (`> 0.90`) on
  every split. A1 proved a GLOBAL scale adjustment cannot fix a CONDITIONAL
  miscalibration. A3 calibrates the tail quantiles `(q_lo, q_hi)` conditionally per
  `sigma_hat` bucket (Mondrian), with controlled DOF.
- **Change:** `n_buckets = 4` (rank_quantiles, edges frozen-on-calib, method=linear);
  `c` stays global per split; only `(q_lo, q_hi)` are per-bucket, with fixed shrinkage
  `q_eff = alpha*q_bucket + (1-alpha)*q_global`, `alpha = n_bucket/(n_bucket + n0)`,
  `n0 = 200`; `min_n_bucket = 50` with a deterministic adjacent-merge fallback. One
  hypothesis; gate/proxy/windows/splits unchanged; no winsorization.
- **Result (single run, run_id `20260530T024825Z`):** no leak (edges/partition frozen on
  calib, reused on test, all splits); 4 buckets merged to 3 under the `p50_var` spike (the
  pre-registered failure mode); all buckets non-empty; widths non-degenerate; global calib
  coverage in band. BUT the binding het gate still FAILS on all splits - the over-coverage
  is in the wide width-quartiles and `sigma_hat`-bucketing does not move it. Real but
  insufficient; not gamed. ACCEPT A3 = False, KILL = False. See
  `reports/phase5_trackA_a3.{md,json}`. Track A (A1+A3) closed without retuning.
- **Follow-up (read-only, no method change):** REQ-AUD-5 normative intent + binning frozen
  in `docs/req_aud5_normative.md`; wide-bin audit (Wilson CIs + late-CP composition) in
  `reports/phase5_wide_bin_audit.{md,json}`. Motivates Track P (difficulty-axis change).

## [phase5-a1] - 2026-05-30 - EXECUTED (insufficient; superseded by A3)

### Phase 5 amendment Track A.A1 - sigma winsorization (conformal_method_version 1.0 -> 1.1)

- **Contract:** `contracts/phase5_amendment.md` (criterion_version 1.0; amends
  `contracts/phase5_preregistration.md` v1.0).
- **Canonical PREREG sha256:**
  `ea5b279a70c9b889158c10a867a35a6b49b7859402fa01661cd082b0a6e39c09`
  (to be pinned as `PHASE5A_COMMITTED_SHA256` in the SAME change that wires the method).
- **Reason:** the v1.0 heteroscedasticity gate fails because wide width-quartile bins
  over-cover (~0.99-1.00). Read-only diagnostics (`reports/phase5_hetero_diagnose.md`)
  show `sigma_hat = sqrt(p50_var)` is spiked at ~0.10 with a heavy tail (p99/p50 ~ 5-7x),
  and interval width is uncorrelated with realized error (Spearman ~0.01-0.10). The
  tiny-sigma rows inflate the shared score quantile while the sigma tail inflates the
  applied width, producing 6-14 brackets of pure slack in the wide bins.
- **Change:** winsorize `sigma_hat` to a calib-frozen `[P25, P95]` band, used in both
  the score `u` and the emitted interval. One hypothesis; gate/proxy/windows/splits
  unchanged.
- **Acceptance / kill / expected-failure:** see `contracts/phase5_amendment.md`.
- **Run discipline:** `phase5_evaluate` executed exactly once after wiring; test is
  readout only; no percentile re-tuning after results.
- **Result (single run, run_id `20260530T012449Z`):** no leak (clip frozen on calib,
  reused on test, all splits); widths non-degenerate; global calib coverage in band; widest
  width-bin over-coverage reduced (2023 `1.000->0.947`, 2024 `1.000->0.981`, 2025
  unchanged). BUT the binding het gate still FAILS on all splits (bins 2-4 remain `> 0.90`).
  Real but insufficient; not gamed. See `reports/phase5_trackA_a1.{md,json}`. Motivates A3.

## [phase5-v1.0] - 2026-05-30

### Phase 5 conformal METHOD amendment - normalized quantization-aware conformal

- **Contract:** `contracts/phase5_preregistration.md` (criterion_version 1.0).
- **Canonical PREREG sha256:**
  `56459f40e94a4162b850419f6920ad73afd8a3bc371dc3924c503f6beb01cea1`
  (pinned as `PHASE5_COMMITTED_SHA256`).
- **Reason:** the prior path calibrated a DECIMAL interval then quantized it, but the
  gate evaluates the INTEGER-INCLUSIVE bracket object - calibrating one object and
  evaluating another breaks the coverage guarantee (diagnosed +0.06..+0.11 gap).
- **Change:** calibrate on the same integer object via normalized quantization-aware
  conformal; per-row `sigma_hat = sqrt(p50_var)`; asymmetric tails; continuous nominal
  level `c` selected on calib only.
- **Result (single run):** object mismatch fixed; coverage passes on 2023/2025, fails on
  2024 (calib->test drift); heteroscedasticity gate fails (wide-bin over-coverage); 2023
  ECE scarcity-driven. Phase 5 not ready (honest, un-gamed).
