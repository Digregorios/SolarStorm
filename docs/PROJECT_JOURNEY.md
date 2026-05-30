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
  baseline runs cold by 1-3C - this is the FLOOR (the CLI forecast still uses the Phase-2
  empirical baseline, not the trained Ridge/NWP models that score ~0.44 bracket-match). Religando
  o CLI ao modelo treinado e o agendamento 30-min do fetch sao os proximos passos operacionais.

---

## Cross-cutting discipline (held throughout)

- ASCII-only source (`tools/ascii_guard.py`), reverse-import guard (eccodes never on runtime
  graph), determinism (frozen seeds; REQ-MOD-6), per-split reporting (pooled only as a labelled
  note), and hashed pre-registration with teeth (the evaluator refuses to run under a drifted
  contract). No threshold was loosened after seeing a result.

## Current status snapshot

- DONE/green: Phases 0-4 (point forecast), Phase 7 (spike), Phase 8 offline logic + live odds +
  live METAR fetch. Full test suite green.
- CLOSED not-ready: Phase 5 interval calibration (diagnostic-only, fenced from trading).
- Open/optional: T-8-4 threshold tuning (odds-free objective), T-6-3 AR DM-test, CLI `forecast`
  re-wire to the trained model, 30-min fetch scheduling, live realized-EV (intrinsically live).
