# Live NWP availability audit (Onda 2-A) - **PAUSE**

- git_sha: `b6ec9f2b120aa3a67fa124b33dac682b52b27f86`  station: NZWN  window: 2021-01-01..2025-12-31  safety: 60min
- Read-only causal audit over local snapshots; no fetch, no model. run_time <= cp - 60min enforced by select_nwp_v1 and re-checked here. Per-model endpoints from ENDPOINT_BY_MODEL (ecmwf single_runs, gfs s3_grib). Verdict threshold any_causal coverage >= 0.99 on all CPs was frozen before the numbers. ECMWF pre-2024 absence is reported honestly as a per-CP coverage gap, not a bug -- the audit measures reality. serving_readiness (P3a) re-judges the SAME any_causal numbers over CP20-22 (NWP_LEAD_CPS) only -- CP23 is conservative Ridge and needs no NWP.
- **serving_readiness (CP20-22): PAUSE** (offending: ['20:00', '21:00', '22:00']) -- general verdict above is over all 4 CPs.

## any_causal (router keys off EITHER model at CP20-22)

| CP | coverage | causal/days | fallback_rate | n_gaps |
|----|----------|-------------|---------------|--------|
| 20:00 | 0.9556 | 1745/1826 | 0.0444 | 81 |
| 21:00 | 0.9556 | 1745/1826 | 0.0444 | 81 |
| 22:00 | 0.9556 | 1745/1826 | 0.0444 | 81 |
| 23:00 | 0.9556 | 1745/1826 | 0.0444 | 81 |

_PAUSE: any_causal coverage < 0.99 at CPs ['20:00', '21:00', '22:00', '23:00']._

## ecmwf (endpoint: single_runs)

| CP | coverage | causal/days | fallback_rate | lead min/med/max | run_age_h min/med/max | n_missing_months |
|----|----------|-------------|---------------|------------------|-----------------------|------------------|
| 20:00 | 0.3582 | 654/1826 | 0.6418 | 8.0/8.0/8.0 | 8.0/8.0/8.0 | 38 |
| 21:00 | 0.3582 | 654/1826 | 0.6418 | 9.0/9.0/9.0 | 9.0/9.0/9.0 | 38 |
| 22:00 | 0.3582 | 654/1826 | 0.6418 | 10.0/10.0/10.0 | 10.0/10.0/10.0 | 38 |
| 23:00 | 0.3582 | 654/1826 | 0.6418 | 11.0/11.0/11.0 | 11.0/11.0/11.0 | 38 |

## gfs (endpoint: s3_grib)

| CP | coverage | causal/days | fallback_rate | lead min/med/max | run_age_h min/med/max | n_missing_months |
|----|----------|-------------|---------------|------------------|-----------------------|------------------|
| 20:00 | 0.9556 | 1745/1826 | 0.0444 | 2.0/2.0/13.0 | 2.0/2.0/26.0 | 2 |
| 21:00 | 0.9556 | 1745/1826 | 0.0444 | 3.0/3.0/13.0 | 3.0/3.0/27.0 | 2 |
| 22:00 | 0.9556 | 1745/1826 | 0.0444 | 4.0/4.0/13.0 | 4.0/4.0/28.0 | 2 |
| 23:00 | 0.9556 | 1745/1826 | 0.0444 | 5.0/5.0/13.0 | 5.0/5.0/29.0 | 2 |

## Missing months (first 5 per model/CP)

- ecmwf 20:00: ['2021-01', '2021-02', '2021-03', '2021-04', '2021-05']
- ecmwf 21:00: ['2021-01', '2021-02', '2021-03', '2021-04', '2021-05']
- ecmwf 22:00: ['2021-01', '2021-02', '2021-03', '2021-04', '2021-05']
- ecmwf 23:00: ['2021-01', '2021-02', '2021-03', '2021-04', '2021-05']
- gfs 20:00: ['2021-01', '2021-02']
- gfs 21:00: ['2021-01', '2021-02']
- gfs 22:00: ['2021-01', '2021-02']
- gfs 23:00: ['2021-01', '2021-02']
