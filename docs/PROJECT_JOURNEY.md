# Project journey - Polymarket Tmax Forecaster (NZWN)

Consolidated, objective record of the path taken: what was built, what was tried, what failed,
and the decisions that resolved each fork. Detailed but skimmable. Companion to `CHANGELOG.md`
(versioned method changes) and the per-phase reports under `reports/`.

Station: NZWN (Wellington). Goal: intraday integer-Tmax forecast per checkpoint (CP), with
CP-aware causality, calibrated confidence, late-spike risk, and a live EV/Kelly decision layer
for Polymarket Tmax markets. Frozen contracts + anti-nowcaster audit throughout.

---

## Phase 0-2 - foundations (DONE, committed in 5126079)

- Frozen contracts (Q_VERSION 1.0, IMPUTATION_VERSION 1.0, FEATURES_VERSION 0.1), data
  contracts + labels (`late_spike_l1__cp_HH = k_eod != k_cp`), EDA (99.7% day_complete, 0%
  fallback), baselines (persistence/climatology), and the H0 anti-nowcaster audit harness.

## Phase 3 - Ridge band-aware (DONE)

- First ML: band-aware Ridge over the 13 baseline features, walk-forward 2023/2024/2025.
- **Result:** REQ-MET-4 PASS 3/3 - bracket-match beats max(persistence, climatology) by
  +16..+23 pts, CI95 lo>0 every split. Surviving anti-nowcaster gates pass.
- **Problem found:** the `corr_diff` gate FAILS on all splits (predictions track the nowcast
  more than next-day truth). This single finding drove the entire Phase 4 re-framing.

## Phase 4 - NWP residual learning (DONE; phase4_ready = True)

The hardest data chapter. Several forks, each resolved by evidence, not preference:

1. **Anchor contradiction.** The v1 design anchored NWP on a single climatological Tmax hour;
   review showed this is fragile to seasonal/early-peak shift. Resolved by the v1.1 amendment:
   the anchor became the **max-of-trajectory** over a forward Tmax-hour window of the single
   causal run (design 4.5.2.1; NWP_SOURCE_VERSION 1.1, MODEL_VERSION bump).
2. **HFAPI leakage / source choice (OPN-5 / T-OPN-5a).** Open-Meteo HFAPI stitches runs and can
   leak ~3h of assimilation; it also does not serve causal GFS single-runs. Decision: anchor on
   **GFS decoded OFFLINE from AWS `noaa-gfs-bdp-pds`** via `.idx` byte-range (a few hundred KB
   per message, not the ~500 MB field). eccodes/cfgrib kept strictly OFFLINE (never on the
   deterministic runtime import graph - REQ-MOD-6).
3. **The "bash classifier" detour.** A prior session's runbook expected the GFS backfill to run
   outside the agent; when picked up here, a real Windows bug surfaced in the decoder
   (`NamedTemporaryFile` + `Path.unlink()` raced eccodes' open handle -> WinError 32). Fixed by
   decoding in-memory via `eccodes.codes_new_from_message` (no temp file). The byte-range probe
   GATE (gridpoint 9.75 km, K->C plausible) passed and guarded the bulk decode.
4. **Split-1 (2023) rescue.** Re-anchoring made split-1 untrainable (no causal GFS pre-2023). A
   first instinct was to drop split-1 -> >=2/2. The reviewer (update.txt) correctly identified
   this as an INGESTION boundary, not a data limit: the S3 bucket carries GFS 0.25deg back to
   ~2021-03-22. Probed the bucket depth (earliest = 2021-03-22, not the ~2021-02 estimate),
   backfilled 2021-2022 (~21 months) so split-1 trains -> the preferred >=2/3 rule was kept, NO
   split dropped, NO pre-registration amendment, NO sha256 recompute.
5. **corr_diff demotion (criterion_version 1.1, pre-registered, hashed).** Rather than re-litigate
   a metric Phase 3 failed, corr_diff became a diagnostic monitor; its intent is absorbed by
   i_t_obs + SS(1h/3h) + counterfactual-AUC + the horizon curve. Acceptance became a PAIRED
   ABLATION (LGBM obs+NWP vs obs-only), CI95 lo>0 in >=2/3 splits.
- **Result:** paired-ablation per-CP 1/3 (only 2024 clears at the single op CP) but POOLED 3/3
  (CI95 lo>0 all splits); REQ-AUD-2 0 violations; phase4_ready = **True**. Pre-registration hash
  verified, no drift. Forward-skill curve positive at every lead (20-23Z).

## Phase 5 - calibration + confidence (CLOSED: NOT READY)

The chapter with the most attempts. Object: integer IC80 with ~0.80 coverage AND width that
tracks difficulty (REQ-AUD-5 heteroscedasticity gate, per width-quartile in [0.70,0.90], per
split, never pooled). Seven pre-registered, hashed, one-shot attempts - all failed the binding
het gate, each for an honest, documented reason:

| track | hypothesis (one variable) | outcome |
|-------|---------------------------|---------|
| v1.0 | normalized quantization-aware conformal (calibrate the integer object) | object mismatch fixed; het gate FAIL |
| A1 | global sigma winsorization [P25,P95] | wide-bin over-coverage reduced, het gate still FAIL |
| A3 | Mondrian conditional by sigma bucket | conditional fix; het gate FAIL (Track A closed) |
| P | difficulty axis = predictive entropy | REJECTED at calib-only monotonicity sanity (no one-shot) |
| P' | difficulty axis = quantization margin | REJECTED at calib-only sanity (no one-shot) |
| D1 | endpoint quantizer Q -> Q_rand (randomized rounding) | het gate FAIL; calib in-band, no KILL |
| S | tail-budget shape S1 sym vs S2 asym (calib-only vtest) | S1 wins on slack; does not change verdict |

- **A real integrity catch (D1).** The frozen `Q_rand` formula had a factor-2 transcription
  error (`P(ceil)=2t`, biased, with a pathological flip at 0.5) that contradicted the contract's
  own `E[Q_rand]=x` and would have failed the mandatory unbiasedness test. Corrected
  PRE-execution to standard randomized rounding (`P(ceil)=t`), with the canonical hash re-pinned
  in the same change-set and documented - anti-gaming discipline held.
- **Extracted signal (not wasted).** The late-CP mod-wide over-coverage is STRUCTURAL: 4
  deterministic corrections + 1 stochastic smoothing only relabel slack, never remove it. The
  symmetric tail beats the asymmetric one (S1 slack 0.965 vs S2 1.577), so it is not a
  directional-bias problem. Global coverage IS achievable; conditional (width-stratified)
  coverage is the open problem.
- **Decision (stop criterion B3):** Phase 5 closed NOT READY. IC80/confidence are DIAGNOSTIC
  only and are FENCED OFF from production trading (`confidence.gate_enabled_in_production: false`;
  `production_confidence_gate` no-ops while red). Roadmap advances; no more calibration tracks.

## Phase 6 - AR online residual corrector (PARTIAL)

- `core/online/ar.py`: AR(7) equal-weight, strictly-past, json state with backup-before-write and
  `(date_local, cp_utc)` dedupe (REQ-OPS-5). `ar_online.enabled=false` by default.
- T-6-3 (DM-test AR-on vs AR-off) deferred: it consumed the Phase 5 prediction stream that was
  in flux; revisitable now that Phase 5 closed.

## Phase 7 - late-spike risk module (DONE)

- Causal spike features (`ts_utc < cp_utc` guard) + binary LightGBM + isotonic calibration.
- **Result:** REQ-SPK-3 PASS 3/3 - PR-AUC 0.947/0.948/0.953 vs base prevalence ~0.81-0.85,
  bootstrap CI95 lower bound > prevalence every split; ECE 2.4-4.5%.
- Integrated: `-spike_risk` is the 6th confidence phi; the decision engine has
  `BLOCK_BUY_NO_LATE_SPIKE`.

## Phase 8 - decision engine + live odds (DONE for offline logic; live-gated for trading)

- **Scope correction (important).** An early premise treated Polymarket odds as a historical
  dataset with a realized-EV backtest as the primary metric. CORRECTED: odds are LIVE-only
  context captured at the forecast CP; there is no historical odds dataset and no EV backtest.
  The OFFLINE promotion metric is odds-free forecast-quality (`max bracket_match_when_traded s.t.
  coverage`); EV/Kelly are a LIVE product. Requirements (REQ-MET-1/5, REQ-DEC-3/4), objective,
  design 10.1 and the README were all corrected.
- **Built:** full `decide()` (6 states, design 10), `market_map.p_yes` (prob_dist -> contract),
  `shadow_exec.shadow_simulate` (single-trade PnL/what-if, NOT a historical backtest),
  `sizing.py` (live EV + capped fractional Kelly), `core/ingest/odds.py` (deterministic
  Polymarket event slug/URL + Gamma API live snapshot, verified against the real Wellington event
  - 11 brackets), and the `decide` CLI wiring forecast -> odds -> decision+sizing.

## Live data pipeline (added; the missing piece)

- The historical IEM CSV ends 2026-05-27; an intraday forecaster needs CURRENT obs. Added
  `core/ingest/metar_live.py`: fetches raw METAR from aviationweather.gov (30-min cadence),
  resolves DDHHMMZ to UTC, parses into the SAME canonical schema (one source of truth for the
  integer temperature), and merges with history. Verified live (191 rows, 100% parsed,
  to 2026-05-30 17:30Z).
- **Clean backtest 2026-05-27..30** (`scripts/backtest_may2026.py`, merged history+live, baseline
  empirical @ CP 23:00): realized Tmax 15/17/15/16; bracket-match 1/4, IC80 coverage 4/4. The
  baseline runs cold by 1-3C.
- **Bottleneck progression (diagnosed via the backtest):**
  1. RESOLVED - live ingestion was blocking (no current-obs fetch). Added `ingest-live` CLI
     (`py -3 -m core.cli.app ingest-live`): merged 112322 rows to 2026-05-30 18:00Z, 100% parsed.
  2. NEW bottleneck - the CLI was SERVING THE BASELINE, not a production model. The backtest's
     1/4 bracket-match is the empirical FLOOR; the trained Ridge/NWP models score ~0.44.
     Delivered `forecast --model {empirical|ridge}`: default stays `empirical` (NOT switched
     silently), `--model ridge` is opt-in and trains the Phase-3 band-aware Ridge on the panel.
     Verified 2026-05-27: empirical p50=13/IC80=[12,17] vs ridge p50=12/IC80=[12,13].
- **Open conceptual fork (to resolve before promoting a default):** "production model" is not yet
  unambiguous. Ridge (Phase 3) is trainable from obs alone for any live date, but failed
  corr_diff (nowcast-tracking). The NWP-residual (Phase 4, phase4_ready=True) is the stronger
  point model but its GFS s3_grib anchor only covers historical run dates - a TRUE live forecast
  needs a live GFS run fetched at the CP, which is not yet wired. So: Ridge is live-ready now;
  NWP-residual is the better model but live-gated on a live GFS anchor fetch. Promotion of the
  default (empirical -> ridge/NWP) remains a deliberate, separate decision.

---

## Cross-cutting discipline (held throughout)

## Ensemble-evolution track (2026-05-31) - incremental, gated

After Phase 5 closed, the bias audit re-framed the open problem as the CENTER under late-warming,
not the IC. A pivot to a layered probabilistic ensemble was proposed; judged and reconciled to an
INCREMENTAL queue (not a from-scratch v1 - that was the quarantine, which failed). Full assessment
+ the 4 conceded reviewer rebuttals in `reports/ensemble_pivot_assessment.md`.

What was tried and what it showed (each gated, honest):
1. **ridge_conformal_minimal** - per-CP IC80 from the Ridge's own abs-residuals. After two P0
   fixes (true split-conformal held-out calib; per-split train-only climo) -> coverage 0.86-0.91
   per CP, non-degenerate. **IC calibration is now defensible.** Not Phase 5.
2. **late_warming_bias_audit (n=1095)** - Ridge cold bias is narrow + proportional to post-CP
   warming and shared by ALL centers (causal-horizon limit). Answered "is it a dead end?": no -
   precursors may exist before the CP even though the realized thermal signal does not.
3. **Etapa 1 EDA (read-only)** - PRE-CP precursors of material late-warming exist: wind change
   S->N, morning slope, southerly (suppress), rain-persistence (suppress). "Cold-start=upside"
   REJECTED. Ridge has no month x decade bias (its bias is regime-specific).
4. **Etapa 2 precursor audit (walk-forward)** - 3/4 primary precursors survive; t_06 flipped OOS
   (rejected); S->N high-lift small-n. Verdict GO.
5. **risk_model_v0 / v0.1** - causal pre-CP logistic. v0 GO=False (top-decile lift just under 1.4,
   4/5 gates). v0.1 re-gated on bucket separation: also GO=False (high bucket too diluted for
   1.35x), BUT the LOW protective bucket is robust (~0.13-0.22 vs base ~0.38). **Net: a reliable
   CALM-DAY detector, not a sharp high-risk hunter.** No gate loosened; stays diagnostic-only.
6. **calm_day_filter_v0** - reviewer-directed pivot of the objective to the robust LOW signal.
   **GO=True**: calm days (predicted risk < train P30) have ~0.5x base late-warming rate,
   precision(no late-warming|calm) 0.78-0.88, Brier < base 3/3. A protective filter that guards
   the ~63% calm days where Ridge already does well. Diagnostic flag only (no IC/center change).
7. **Etapa 3 analog_retrieval_audit** - causal k-NN (train-only pool, anti-leakage). The high-risk
   side the logistic missed IS captured by analogs: non-calm high-risk lift 1.42/1.36/1.34, top-
   decile lift ~2.1, PR-AUC 0.64-0.67 vs base ~0.37 - predictive gates PASS 3/3. Formal GO=False
   only on g5 (analog_quality bucketing, a HOW-to-score metric, not capability). Analogs are the
   leading HIGH-risk arm candidate.
8. **analog_quality_v0.1** - resolves g5: `analog_confidence = |P_analog - base|` PASSES 3/3
   (high-confidence bucket Brier 0.165-0.175 vs 0.221-0.229, lift 2.2-2.6 vs ~1.0-1.3); the v0
   "divergence" was a paste artifact (code already used the 7-feat prereg vector). With g1-g4 + g5
   resolved, the analog high-risk arm is ELIGIBLE for a separately-gated build.

Open decision (awaiting direction): build the analog_high_risk_arm_v0 (now eligible) and/or
compare vs NWP/Open-Meteo (Etapa 4); then the ensemble has both sides (calm filter + analog
high-risk + Ridge center + conformal) and blending / conditional conformal can begin.

## Cross-cutting discipline (held throughout)

- ASCII-only source (`tools/ascii_guard.py`), reverse-import guard (eccodes never on runtime
  graph), determinism (frozen seeds; REQ-MOD-6), per-split reporting (pooled only as a labelled
  note), and hashed pre-registration with teeth (the evaluator refuses to run under a drifted
  contract). No threshold was loosened after seeing a result. **Docs (CHANGELOG + this journey +
  READMEs) and versioning are updated as part of every delivery, not afterwards.**
- **Per-session versioning (2026-05-31 onward): at the END of each session (while awaiting the next
  `update.txt`), the delivered state is tagged with an annotated git tag `session-YYYY-MM-DD[-n]` so
  the reviewer can check out and inspect the exact code, not only the reports. The working tree must
  be clean (only `references/code-reviews/update.txt`, the message channel, may differ) before tagging.**
- **Core-first FREEZE (2026-05-31 onward): NO new Polymarket/trading/execution delivery (Kelly, EV,
  sizing, decision-line, brackets, resolver, trading states) until a report shows the Tmax model beats
  strong baselines in causal walk-forward. The execution layer is frozen except for the minimum to keep
  existing contracts/tests green. `reports/core_predictor_status.md` is the gating evidence.**

## Current status snapshot (2026-05-31)

- DONE/green: Phases 0-4 (point forecast), Phase 7 (spike), Phase 8 offline logic + live odds +
  live METAR fetch (`ingest-live` + health-check). Full test suite green (367). Live `decide`
  hardened for resolved/boundary-price markets; EV/Kelly sizing follows the engine state.
- **Core predictor (2026-05-31, `reports/core_predictor_status.md`): Ridge beats the best baseline by
  MAE in 3/3 splits at all 4 CPs; CP23 MAE ~0.70 degC / RMSE ~1.02 / bracket-match 0.441. Edge is
  concentrated on late-warming days (MAE 0.87 vs persistence 2.55), ties on stable days, loses on
  Tmax-already-reached days. The core IS validated; the execution layer is FROZEN behind it.**
- **Phase 9 (predictor improvement) T-9-1 analog_high_risk_arm_v0: GO** - blends an analog point
  estimate into Ridge on EX-ANTE non-calm days (predicted risk>=c30, causal; not truth-derived).
  Non-calm MAE improves 3/3 splits, aggregate holds; anti-leakage review 10/10. Built via a 3-agent
  pipeline (my prereg + subagent impl/review + my re-verification). Gain is REAL but SMALL - the
  bigger open gap is the conditional distribution/interval (T-9-3), not the point.
- **Phase 9 T-9-3 conditional_calibration_v0: KILL (honest)** - regime-conditional (ex-ante
  calm/non_calm) conformal does NOT fix the structural late-CP IC80 over-coverage; both regimes
  over-cover (calm 0.945, non_calm 0.904), the slack is GLOBAL (Q-after-decimal + finite-sample rank),
  not regime-isolable. Confirms the Phase 5 closure. The calibration "roof" stays OPEN; next candidate
  is NWP-spread sigma or accepting ridge_conformal_minimal (per-CP IC80 0.86-0.91) as the stopgap.
- **Phase 9 calibration SETTLED-WITH-STOPGAP (2026-05-31): T-9-5 native_integer_conformal KILL
  (DECISIVE - native-integer still over-covers, refuting the Q-after-decimal hypothesis; the slack is
  integer granularity itself), T-9-6 NWP-spread NOT FEASIBLE (only 1 local NWP model -> zero spread),
  T-9-7 stopgap adopted (ridge_conformal_minimal diagnostic-only). A calibrated 80% integer IC is
  likely not recoverable with the current point model + granularity; the only remaining lever is a 2nd
  causal NWP model (ECMWF). Calibration is no longer the active blocker - the diagnostic stopgap holds.**
- **Phase 10 (post-calibration, 2026-05-31): T-10-1 ECMWF 2nd-NWP-source feasibility CONDITIONAL GO
  (code ready, missing is DATA; causal single-runs reachable 2024-03..2025-12, no GRIB); T-10-2 NWP
  early-lead point gain GO in degC (dMAE -0.20/-0.16/-0.11 at 20/21/22Z, 3/3 splits, reconciles
  bracket-match); T-10-3 error taxonomy delivered - the biggest ex-ante error pocket is the non-calm
  regime (73% of total error), then high-delta_06 days; T-10-4 diagnostic-IC display fence (doc).
  Next predictor lever, evidence-driven: the non-calm / high-delta_06 regime (where the analog arm + a
  2nd NWP source would help most).**
- **Phase 11 (data-first, 2026-05-31): T-11-1 ECMWF causal-ingest pilot GO (12/12 clean, no GRIB,
  causal run selected at CP23 lead 11h; full backfill 2024-03..2025-12 is the next data action);
  T-11-2 non_calm/high-delta targeted model prereg (design-first, H1 regime-split residual, gate must
  beat the analog arm); T-11-3 NWP early-lead candidate memo (NWP-residual candidate at CP20-22, no
  auto-promote without a per-CP comparison matrix). Execution + calibration unchanged.**
- CLOSED not-ready: Phase 5 interval calibration (diagnostic-only, fenced from trading).
- Ensemble-evolution track: ridge_conformal_minimal IC defensible; precursors validated (Etapa 2
  GO); risk_model v0/v0.1 GO=False (diagnostic); calm_day_filter_v0 GO=True (protective low side);
  analog_retrieval_audit + analog_quality_v0.1 - analogs capture the high-risk side (g1-g5 pass via
  analog_confidence), analog high-risk arm ELIGIBLE for a separately-gated build. Audits read-only.
- Active modeling bottleneck: late-warming CENTER (regime-specific cold bias); the risk model
  detects calm days well but not high-risk days sharply.
- Open/optional: protective-bucket use, risk_model v0.2, Etapa 3 analogs, NWP multi-model v0,
  promote CLI default (still empirical), persist trained model, live realized-EV.
