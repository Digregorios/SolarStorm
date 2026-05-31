# T-10-1 ECMWF Causal Ingest Feasibility Memo

> Phase 10 deliverable. Scope: `contracts/ecmwf_causal_ingest_feasibility_v0_scope.md`.
> Author: automated analysis. Date: 2026-05-31. Doc-only (no ingest, no backfill).

---

## 1. Does the code ALREADY support ECMWF?

**YES.** The missing thing is DATA, not code.

Evidence:

- `core/ingest/nwp_client.py` defines `ECMWF_IFS_HRES = ModelSpec(id="ecmwf_ifs_hres",
  open_meteo_id="ecmwf_ifs", cycle_h=6, archive_start=date(2017, 1, 1))`.
- `V1_MODELS` tuple includes ECMWF alongside GFS. The config contract
  (`load_nwp_model_specs`) validates both are present in `nzwn/config/model.yaml`.
- `fetch_hfapi()` and `fetch_single_run()` accept any `ModelSpec`; ECMWF is
  parameterized identically to GFS (same URL base, different `models=` value).
- `select_nwp_v1` and `select_nwp_ensemble` are model-agnostic: they filter on
  `pl.col("model")` string, not on hard-coded model names.
- `snapshot_hfapi_range` and `snapshot_single_run` write to model-specific
  partition paths (`<station>/ecmwf_ifs_hres/<endpoint>/...`).
- The max-of-trajectory anchor (`core/features/nwp.py`) operates on any causal
  run regardless of model identity.

**What is actually missing:** no ECMWF parquet snapshots exist on disk. The GFS
pipeline (`scripts/gfs_s3_backfill.py` + `scripts/gfs_grib_decode.py`) was built
because GFS single-runs were unavailable via Open-Meteo API for NZWN (P-02 in
`docs/guia_portabilidade.md`). ECMWF does NOT have this problem -- Open-Meteo
serves ECMWF single-runs natively.

---

## 2. Causal ECMWF historical-forecast feed: is it reachable?

**YES, with a date-range constraint.**

### 2.1 Single Runs API (strict causal)

Per `contracts/nwp_source.md` endpoint matrix:

> `single-runs-api.open-meteo.com/v1/forecast?run=YYYY-MM-DDTHH:00`
> -- strict-causal: a single model run picked by `run_time_utc`;
> **ECMWF available since 2024-03**.

Per `docs/guia_portabilidade.md` problem P-03:

> ECMWF single-run causal vazio em fev/2024, cheio em mar/2024.
> [...] ECMWF causal so >= 2024-03 no Open-Meteo.

The Single Runs endpoint returns explicit `run_time_utc` (the `run=` parameter
IS the init time) and the response carries hourly `valid_time_utc` values with
computable `lead_h = (valid_time - run_time) / 1h`. This satisfies the causal
contract: `run_time_utc <= cp_utc - 60min` is enforceable deterministically.

### 2.2 Historical Forecast API (stitched, non-causal anchor)

HFAPI for ECMWF covers the full archive from 2017-01-01. However, it is a
stitched series (each hour sourced from the freshest run at that moment). Per
the project's established rules (design 4.5.2, `guia_portabilidade.md` sec 2.1),
stitched data is NOT causal for the anchor -- it can only serve as a feature
engineering / spread input, never as the primary forecast anchor.

### 2.3 Causality satisfaction

For any CP at 20:00-23:00 UTC on day d, the ECMWF 12Z run of (d-1) has
`run_time_utc` at least 8 hours before the earliest CP. The 18Z run of (d-1)
is 2-5 hours before CP. Both satisfy `run_time <= cp - 60min` with large margin.
The 00Z run of day d satisfies for CP >= 01:00 UTC (i.e., all operational CPs
for NZWN at 20/21/22/23 UTC). The existing `select_nwp_v1` logic picks the
latest qualifying run automatically.

---

## 3. Coverage over walk-forward 2023-2025

### 3.1 Single Runs (causal anchor)

| Period | Coverage | Source |
|--------|----------|--------|
| 2023-01-01 to 2024-02-28 | **NO DATA** (single-runs empty for ECMWF) | P-03 in guia |
| 2024-03-01 to 2025-12-31 | **FULL** (daily 00/06/12/18Z runs available) | nwp_source.md |

This means:
- **Split 1 (test 2023):** NO causal ECMWF single-run data for training (needs
  2020-2022) NOR testing. ECMWF single-runs cannot serve split 1 at all.
- **Split 2 (test 2024):** training needs 2020-2023 (no ECMWF single-run before
  2024-03); test period 2024-01 to 2024-02 also missing. Partial coverage only
  (2024-03 to 2024-12 = 10 months of test, 0 months of NWP-anchored training).
- **Split 3 (test 2025):** training can use 2024-03 to 2024-12 (~10 months of
  ECMWF-anchored rows); test 2025 is fully covered.

### 3.2 HFAPI (stitched, for features/spread only)

| Period | Coverage |
|--------|----------|
| 2017-01-01 to present | FULL |

HFAPI covers all splits for non-anchor uses (spread computation, disagreement
features). The `gfs_probe.json` already shows ECMWF HFAPI data was successfully
retrieved for 2023-2025 (n=366/367/366 per year, pearson 0.965-0.976).

### 3.3 Asymmetry assessment

The coverage gap mirrors (but is worse than) the GFS situation documented in
`reports/phase4.md` "Training-window asymmetry (split-1)": GFS causal starts
2021-03-22, giving split-1 only 21 months of NWP-anchored training. ECMWF
single-runs start 2024-03, giving split-2 only 0 months and split-3 only 10
months of ECMWF-specific anchored training.

**ECMWF single-runs CANNOT be the sole anchor across all 3 splits.** It can
only serve as a SECOND source alongside GFS for the 2024-03+ window.

---

## 4. Cost / licence / GRIB-decode / Windows-file-lock blockers

### 4.1 Cost and licence

- Open-Meteo free tier (10k calls/day) is sufficient for ECMWF backfill via
  Single Runs API. At 4 runs/day x ~670 days (2024-03 to 2025-12) = ~2680 calls.
  Well within daily limits even in a single session.
- Licence: CC BY 4.0 with attribution to Open-Meteo + ECMWF. Attribution already
  documented in `references/legacy/data_sources.md`.
- No commercial-tier upgrade needed for backfill.

### 4.2 GRIB decode: NOT REQUIRED

Unlike GFS (which required a custom GRIB pipeline because Open-Meteo returned
empty single-runs for NZWN -- problem P-02), ECMWF single-runs ARE served by
Open-Meteo natively as JSON. No eccodes dependency, no GRIB byte-range parsing,
no Windows file-lock issues (P-04). The existing `fetch_single_run()` +
`single_run_response_to_dataframe()` path handles ECMWF identically to any
other model.

### 4.3 Windows file-lock

Not a concern: the JSON->Parquet path (`snapshot_single_run`) uses Polars
`write_parquet` which does not trigger the WinError 32 issue (that was specific
to eccodes temp-file handling in the GRIB pipeline).

### 4.4 Known blockers: NONE for the 2024-03+ window

The only blocker is the coverage gap (section 3), which is a data-availability
constraint, not a technical one.

---

## 5. Informativeness (already proven)

`reports/gfs_probe.json` includes ECMWF results:

| Year | n | Pearson | Spearman | Slope | Bias (C) |
|------|---|---------|----------|-------|----------|
| 2023 | 366 | 0.965 | 0.964 | 1.041 | -1.02 |
| 2024 | 367 | 0.976 | 0.973 | 1.132 | -1.29 |
| 2025 | 366 | 0.970 | 0.971 | 1.079 | -1.13 |
| Pooled | 1099 | 0.970 | 0.969 | 1.083 | -- |

ECMWF consistently outperforms GFS (pooled pearson 0.970 vs 0.953; lower
residual variance). The gridpoint carries strong Tmax signal for NZWN. The
informativeness gate (sec 2.3 of guia) is PASSED.

---

## 6. Recommendation

### CONDITIONAL GO

**Rationale:** ECMWF causal single-run data is technically reachable via the
existing code with zero modifications. The informativeness is proven and superior
to GFS. However, coverage is limited to 2024-03-01 onward, which means:

- ECMWF CANNOT replace GFS as the sole anchor (splits 1-2 have no/insufficient
  ECMWF causal training data).
- ECMWF CAN serve as a SECOND causal source for the 2-model ensemble
  (`select_nwp_ensemble`) in the 2024-03+ window, enabling:
  - Real NWP spread (disagreement feature `nwp_spread_c`) with two independent
    centers (ECMWF + GFS) instead of the current single-source spread=0.
  - Potential point-forecast improvement via ensemble mean (ECMWF pearson 0.970
    vs GFS 0.953 suggests ~0.5-1.0 degC RMSE reduction on the residual).

**Conditions for GO:**
1. Accept the split-asymmetry rule already established for GFS: ECMWF enters the
   ensemble only for dates >= 2024-03-01. Splits 1 and early split 2 use GFS-only.
2. The backfill is a data-only task using existing `snapshot_single_run()`.
3. The cross-check obligation (T-OPN-5a, `contracts/nwp_source.md` sec "Cross-check")
   must be executed on the 2024-03 to 2025-12 overlap window before promoting
   ECMWF to production anchor status.

---

## 7. Concrete next action

**Backfill ECMWF single-runs 2024-03-01 to 2025-12-31 via
`single-runs-api.open-meteo.com` using existing `snapshot_single_run()`.**

- Endpoint: `https://single-runs-api.open-meteo.com/v1/forecast`
- Model parameter: `models=ecmwf_ifs`
- Runs to fetch: 4/day (00, 06, 12, 18Z) x ~670 days = ~2680 API calls
- Estimated partitions: 22 monthly parquet files (2024-03 to 2025-12)
- Storage: ~2-5 MB total (comparable to GFS parquet footprint)
- Script: adapt `scripts/gfs_s3_backfill.py` pattern but using
  `snapshot_single_run(model=ECMWF_IFS_HRES, ...)` -- no GRIB, no eccodes
- Rate limit: ~1 req/sec -> ~45 min wall time for full backfill
- Validation: confirm t2m non-null for each run (lesson P-01); abort if any
  month returns empty (lesson P-03 regression check)

---

## Appendix: file evidence cited

| File | Role in this memo |
|------|-------------------|
| `contracts/nwp_source.md` | ECMWF in v1 launch set; single-runs since 2024-03 |
| `core/ingest/nwp_client.py` | `ECMWF_IFS_HRES` ModelSpec; `fetch_single_run()` |
| `core/ingest/nwp.py` | `snapshot_single_run()`; `select_nwp_ensemble()` |
| `docs/guia_portabilidade.md` | P-02 (GFS API empty); P-03 (ECMWF causal >= 2024-03) |
| `reports/gfs_probe.json` | ECMWF informativeness (pearson 0.970 pooled) |
| `reports/phase4.md` | GFS split-1 asymmetry precedent; current single-source results |
