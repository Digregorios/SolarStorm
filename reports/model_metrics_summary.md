# Model metrics - consolidated analysis (2026-05-30)

> Fresh walk-forward runs of every trained model (deterministic, seeds frozen; no code
> changes were needed to run). Splits are expanding-window TEST years 2023 / 2024 / 2025.
> Odds are live-only, so EV/Kelly are NOT a historical metric here (see Phase 5 closure).

## Provenance (update.txt check 1.3)

- git commit: `2b8c2d4`
- `nzwn/config/model.yaml` sha256: `1218debe5f95...` (seeds: python/numpy/lightgbm = 42)
- Phase 4 pre-registration sha256 asserted at runtime: `9a0a2a1b7ebb...` (no drift)
- Q(x) = floor(x + 0.5) (Q_VERSION 1.0); local-day window Pacific/Auckland; CP_SET
  {20,21,22,23} UTC, operational CP 23:00 - identical across all three evaluators (they share
  `load_observations` + `build_tmax_labels` + the same expanding-split definition).

## Dataset sanity (update.txt check 1.4) - same panel/splits for all 3

| split | test days (n_test) | CPs covered | P3 n_train | P4 n_train (NWP-anchored) |
|-------|--------------------|-------------|------------|----------------------------|
| 2023 | 365 | 20/21/22/23 | 1090 | 644 |
| 2024 | 365 | 20/21/22/23 | 1455 | 1009 |
| 2025 | 365 | 20/21/22/23 | 1821 | 1375 |

- All splits: 365 test days x 4 CPs. P4 n_train is smaller (NWP-anchored rows only; causal GFS
  from 2021-03-22) - a documented training-size asymmetry, NOT a leakage or data-quality change.

## TL;DR

| Model | Phase | Headline metric | Verdict |
|-------|-------|-----------------|---------|
| Ridge band-aware | 3 | bracket-match beats baselines +16..+23 pts, 3/3 splits | REQ-MET-4 PASS; corr_diff gate FAIL (demoted in P4) |
| NWP-residual LGBM | 4 | paired-ablation NWP gain, pooled 3/3 CI95 lo>0 | phase4_ready = **True** |
| Conformal IC80 / confidence | 5 | het gate never passed | CLOSED **NOT READY** (diagnostic only) |
| Late-spike LGBM | 7 | PR-AUC 0.947-0.953 vs prevalence ~0.81-0.85 | REQ-SPK-3 PASS 3/3 |

## Phase 3 - Ridge band-aware (point Tmax bracket)

Bracket-match @ operational CP (23:00 UTC):

| split | persistence | climatology | Ridge full | Ridge - baseline [CI95] |
|-------|-------------|-------------|------------|--------------------------|
| 2023 | 0.2493 | 0.1671 | 0.4192 | +0.170 [+0.093, +0.241] |
| 2024 | 0.2329 | 0.1644 | 0.4603 | +0.227 [+0.156, +0.299] |
| 2025 | 0.2822 | 0.1616 | 0.4411 | +0.159 [+0.088, +0.227] |

- **REQ-MET-4 (kill criterion): PASS 3/3** - Ridge beats max(persistence, climatology) with
  CI95 lo > 0 in every split.
- RPS (mean, per split): 4.365 / 4.436 / 4.086. SS-vs-persistence (1h=3h proxy): 0.642 /
  0.651 / 0.691 (all >> 0.08/0.10 thresholds).
- Surviving anti-nowcaster gates PASS: ss_1h 0.64/0.65/0.69, ss_3h 0.64/0.65/0.69,
  i_t_obs 0.097/0.089/0.075 (<0.10), counterfactual AUC 0.80/0.88/0.84 (>0.70).
- **corr_diff gate FAIL** (-0.016 / -0.019 / -0.006 vs 0.20): predictions track the nowcast
  more than next-day truth. This is the known item that drove the Phase 4 re-framing; in
  Phase 4 corr_diff is DEMOTED to a diagnostic monitor (criterion_version 1.1), its intent
  absorbed by i_t_obs + ss + counterfactual-AUC + the horizon curve.

## Phase 4 - NWP-residual LGBM (GFS s3_grib max-trajectory anchor)

Bracket-match @ operational CP:

| split | persistence | climatology | Ridge | NWP raw | NWP+residual |
|-------|-------------|-------------|-------|---------|--------------|
| 2023 | 0.2493 | 0.1671 | 0.4438 | 0.0466 | **0.4329** |
| 2024 | 0.2329 | 0.1644 | 0.4329 | 0.0301 | **0.4795** |
| 2025 | 0.2822 | 0.1616 | 0.4575 | 0.0685 | **0.4575** |

Paired ablation (marginal NWP contribution = LGBM(obs+NWP) - LGBM(obs-only)):

| split | per-CP delta [CI95] | pooled delta [CI95] |
|-------|---------------------|----------------------|
| 2023 | +0.0247 [-0.0357, +0.0904] | +0.0630 [+0.0308, +0.0952] |
| 2024 | +0.1205 [+0.0575, +0.1836] | +0.0877 [+0.0555, +0.1185] |
| 2025 | +0.0493 [-0.0137, +0.1069] | +0.0788 [+0.0466, +0.1089] |

- **Acceptance: PASS** - per-CP 1/3 (only 2024 clears CI95 lo>0 at the single operational CP),
  but **pooled 3/3** (all CPs, tighter CI) clears the >=2 bar. NWP adds genuine forward skill.
- **REQ-AUD-2: PASS, 0 violations** (corr_diff diagnostic-only).
- RPS (mean, per split): 0.578 / 0.483 / 0.532. SS-vs-persistence: 0.663 / 0.692 / 0.703.
- Per-CP forward-skill curve (NWP delta = bm(obs+NWP) - bm(obs-only), 2025 split):
  20:00 +0.129 -> 21:00 +0.096 -> 22:00 +0.041 -> 23:00 +0.049. Positive at every lead (not a
  last-CP artifact); 2023/2024 show the same shape (see reports/phase4.md).
- **phase4_ready = True**; pre-registration hash verified (no drift).
- Training-window note: split-1 (2023) trains on ~21 months of causal GFS (s3_grib from
  2021-03-22); all splits exceed min_train_days=365, so the >=2/3 rule held (no split dropped).

## Phase 5 - conformal IC80 + confidence: CLOSED NOT READY

The REQ-AUD-5 heteroscedasticity gate never passed across v1.0/A1/A3/P/P'/D1/S (the over-
coverage in the wide late-CP bin is structural; see `reports/phase5_closure.md`). Operational
consequence: IC80 / confidence_score are DIAGNOSTIC only and do NOT gate trades in production
(`confidence.gate_enabled_in_production: false`). Global coverage IS achievable; the conditional
(width-stratified) coverage is the open problem. Not on the model-promotion critical path.

## Phase 7 - late-spike LGBM (binary risk module)

| split | PR-AUC [CI95] | base prevalence | recall@FPR<=0.05 | ECE |
|-------|---------------|-----------------|-------------------|-----|
| 2023 | 0.9470 [0.9345, 0.9610] | 0.8123 | 0.2808 | 0.0292 |
| 2024 | 0.9480 [0.9347, 0.9617] | 0.8514 | 0.2767 | 0.0445 |
| 2025 | 0.9525 [0.9395, 0.9637] | 0.8137 | 0.4074 | 0.0236 |

- **REQ-SPK-3: PASS 3/3** - PR-AUC CI95 lower bound > base prevalence in every split (genuine
  skill above "always spike"). ECE 2.4-4.5% (isotonic calibration effective).

## bracket_match @ coverage (REQ-MET-2)

REQ-MET-2 mandates the selective `bracket_match @ coverage {25,50,75,100%}` table. The
risk-coverage selection is a function of `confidence_score`, which is **not production-ready**
(Phase 5 NOT READY): selective coverage points are emitted per split by `phase5_evaluate`
(`reports/phase5.md`) but MUST be read as diagnostic, not as a calibrated operational curve.
At 100% coverage the bracket-match equals the per-model values above. A calibrated selective
table is gated on Phase 5 turning green.

## Who wins where / regressions (update.txt check 3)

Bracket-match @ operational CP (23:00), best non-baseline per split in **bold**:

| split | persistence | climatology | Ridge (P3) | NWP+residual (P4) | winner |
|-------|-------------|-------------|------------|--------------------|--------|
| 2023 | 0.2493 | 0.1671 | **0.4438** | 0.4329 | Ridge (P4 -0.011) |
| 2024 | 0.2329 | 0.1644 | 0.4329 | **0.4795** | P4 (+0.047) |
| 2025 | 0.2822 | 0.1616 | **0.4575** | 0.4575 | tie |

- **Where NWP wins:** clearly in 2024 (+4.7 pts at CP, and the paired ablation CI excludes 0
  per-CP only there). In 2023/2025 the per-CP NWP edge is positive but CI crosses 0; the win is
  carried by the pooled (all-CP) ablation. Earlier CPs (20-22Z) show the largest NWP gain
  (+0.13 at 20Z), i.e. the value is in longer lead, as designed.
- **Regressions to flag:** (a) in 2023 the NWP+residual is marginally BELOW Ridge at the
  operational CP (0.4329 vs 0.4438) - the NWP value there is a longer-lead/pooled effect, not a
  23Z effect; (b) Phase 3 fails corr_diff on all splits (nowcast-tracking), the reason it was
  demoted; (c) interval calibration (Phase 5) is red across the board.
- **Spike vs point models:** no regression interaction observed - the spike module is a separate
  binary head (PR-AUC ~0.95) and does not trade off against bracket-match here.

## Metric comparability caveat (avoid "fresh but not comparable")

- **Bracket-match** and **SS-vs-persistence** ARE comparable across P3/P4 (same object, same
  splits, same Q, same baselines) - use these for "who wins".
- **RPS is NOT comparable across P3 vs P4**: both use the same `rps()` fn + `np.mean`, but P3
  scores the empirical-conditional `prob_dist` while P4 scores the band-aware softmax
  `latent_to_prob_dist` over a different support - hence the scale gap (P3 ~4.4 vs P4 ~0.5).
  RPS is only read WITHIN a model across splits, never P3-vs-P4. (This is exactly the
  "non-comparable fresh metric" trap; flagged rather than silently tabulated.)
- All comparisons above are **per-split**; pooled numbers are shown only as a labelled note,
  never to hide a weak split (update.txt check 4).

## Bottom line

The point-forecast stack is healthy and promotable on forecast-quality: Ridge clears the kill
criterion, the NWP residual adds significant pooled skill (phase4_ready), and the late-spike
risk module has strong, calibrated discrimination. The only red is interval calibration (Phase
5), which is fenced off as diagnostic and off the promotion path. The next metric that does not
yet exist - realized EV - is intrinsically live (no historical odds) and accrues only once live
trading runs through `core.cli.app decide`.

## Reproduce

```
py -3 scripts/phase3_evaluate.py        # reports/phase3.{md,json}
py -3 scripts/phase4_evaluate.py        # reports/phase4.{md,json} + h0_verdict.json
py -3 scripts/spike_evaluate.py         # reports/spike/<run_id>.{md,json}
py -3 scripts/phase5_evaluate.py        # reports/phase5.{md,json} (diagnostic; not ready)
```
