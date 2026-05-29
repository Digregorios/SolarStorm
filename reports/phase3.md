# Phase 3 - Ridge band-aware results

- CP operacional: `23:00`
- Splits: 3
- **REQ-MET-4 kill criterion: PASS** (3/3 splits beat baselines IC95 lo > 0)
- **REQ-AUD-2 gates: PARTIAL** (3 violations)
- **Phase 4 unblocked: False**

## Bracket-match per split

| split | Ridge full | Ridge no-temp | Persistence | Climatology | Ridge - max(base) [CI95] |
|-------|------------|---------------|-------------|-------------|-----------------------------|
| 2023-01-01_to_2023-12-31 | 0.4192 | 0.2493 | 0.2493 | 0.1671 | +0.1699 [+0.0932, +0.2411] |
| 2024-01-01_to_2024-12-30 | 0.4603 | 0.2466 | 0.2329 | 0.1644 | +0.2274 [+0.1562, +0.2986] |
| 2025-01-01_to_2025-12-31 | 0.4411 | 0.2712 | 0.2822 | 0.1616 | +0.1589 [+0.0877, +0.2274] |

## Anti-nowcaster gates (REQ-AUD-2)

### Split 2023-01-01_to_2023-12-31

| gate | value | CI95 | threshold | passed |
|------|-------|------|-----------|--------|
| ss_1h | 0.6420 | [+0.5893, +0.6921] | 0.08 | True |
| ss_3h_proxy | 0.6420 | [+0.5893, +0.6921] | 0.1 | True |
| corr_diff | -0.0158 | [-0.0246, -0.0081] | 0.2 | False |
| coverage_ic80 | 0.8603 | - | |cov-0.8|<0.04 | None |
| i_t_obs | 0.0973 | - | < 0.1 | True |
| counterfactual_same_temp | 0.8025 | - | > 0.7 | True |

### Split 2024-01-01_to_2024-12-30

| gate | value | CI95 | threshold | passed |
|------|-------|------|-----------|--------|
| ss_1h | 0.6514 | [+0.5998, +0.6992] | 0.08 | True |
| ss_3h_proxy | 0.6514 | [+0.5998, +0.6992] | 0.1 | True |
| corr_diff | -0.0185 | [-0.0280, -0.0101] | 0.2 | False |
| coverage_ic80 | 0.8795 | - | |cov-0.8|<0.04 | None |
| i_t_obs | 0.0890 | - | < 0.1 | True |
| counterfactual_same_temp | 0.8762 | - | > 0.7 | True |

### Split 2025-01-01_to_2025-12-31

| gate | value | CI95 | threshold | passed |
|------|-------|------|-----------|--------|
| ss_1h | 0.6905 | [+0.6483, +0.7277] | 0.08 | True |
| ss_3h_proxy | 0.6905 | [+0.6483, +0.7277] | 0.1 | True |
| corr_diff | -0.0063 | [-0.0145, +0.0026] | 0.2 | False |
| coverage_ic80 | 0.9178 | - | |cov-0.8|<0.04 | None |
| i_t_obs | 0.0753 | - | < 0.1 | True |
| counterfactual_same_temp | 0.8428 | - | > 0.7 | True |

## Interpretation of REQ-AUD-2 violations

The Ridge band-aware model passes the REQ-MET-4 kill criterion (beats both
persistence and climatology in 3/3 splits with IC95 strictly above zero) but
fails the `corr_diff` gate (corr(pred, truth) - corr(pred, T_now) ~ 0).

**Diagnosis:** at CP=23 UTC (~11:00 local NZ), the last observation `T_now`
is so strongly predictive of `tmax_int` that any model anchored on it
(including this Ridge with `last_obs_tmp_c_int` as a feature) ends up
correlating with `T_now` almost as much as with `truth`. This is exactly the
borderline-nowcaster condition the gate is designed to detect.

**Planned remediation:** Phase 4 NWP residual learning. The NWP forecast at
valid_time = local Tmax hour decouples the prediction from `T_now` because
the NWP run produces its own anchor independent of the morning observation.

**Phase 4 prerequisite:** OPN-5 (NWP source decision) is still open and
blocks Phase 4 implementation regardless of this gate (REQ-MET-4 + design 16).

**Decision:** Phase 4 stays BLOCKED until both (a) OPN-5 closes and (b)
the new model satisfies REQ-AUD-2 corr_diff in >= 2/3 splits.

