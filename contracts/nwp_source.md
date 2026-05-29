# Contract: NWP source (NWP_SOURCE_VERSION = 1.0)

> Source: REQ-DAT-5, REQ-AUD-2, design 4.5.2, OPN-5.
> Frozen on 2026-05-29 as v1.0 (Phase 4 enable).
> Promotes from "open" (OPN-5) to "decided" with this contract.

## Provider

**Open-Meteo** (https://open-meteo.com), free non-commercial tier
(`historical-forecast-api.open-meteo.com` and `single-runs-api.open-meteo.com`),
plus the `customer-api.open-meteo.com` tier if commercial use is later required.

License: CC BY 4.0; attribution to Open-Meteo and upstream providers (NOAA NCEP,
ECMWF, DWD, UK Met Office) recorded in `references/legacy/data_sources.md`.

## Endpoint usage matrix

| Endpoint | Use | Phase 4 role |
|---|---|---|
| `historical-forecast-api.open-meteo.com/v1/forecast` | continuous historical timeseries (stitched from short leads) | feature engineering / backfill |
| `single-runs-api.open-meteo.com/v1/forecast?run=YYYY-MM-DDTHH:00` | strict-causal: a single model run picked by `run_time_utc` | causality validation in T-OPN-5a; ECMWF available since 2024-03 |
| `previous-runs-api.open-meteo.com/v1/forecast` | fixed lead offsets 1..7 days | NOT used in v1 (lead too long for our CP-target horizon) |
| `ensemble-api.open-meteo.com/v1/ensemble` | perturbed members | NOT used in v1 (only 3 days historical retention) |

## Models (v1 set)

**v1 launch set (2 models):** ECMWF IFS HRES + NCEP GFS.

| Model | Resolution | Cadence | Archive start | Rationale |
|---|---|---|---|---|
| ECMWF IFS HRES | 9 km global | hourly, 6h init cycle | 2017-01-01 | gold-standard accuracy, full coverage of all splits |
| NCEP GFS | 0.11 deg (~13 km) global | hourly, 6h init cycle | 2021-03-23 | independent center (NOAA); covers all splits; widely used baseline |

**Scale-up set (4 models, only after v1 passes Phase 4 gates):**
ECMWF IFS HRES + NCEP GFS + UKMO Global 10 km + DWD ICON Global.

Adding UKMO + ICON requires:
- v1 (2-model) Phase 4 verdict: REQ-MET-4 PASS in >= 2/3 splits.
- Disagreement features (`nwp_spread_c`) computed across the 2-model ensemble proven to add skill (REQ-AUD-2 SS over Ridge baseline).
- NWP_SOURCE_VERSION bump to 1.1 + audit re-run.

> **Anti-pattern explicitly rejected:** starting Phase 4 with 4 models and tuning
> the ensemble weight by validation set. The contract pins `simple mean of available
> models at CP` until 1.1.

## Selection rule v1 (deterministic)

Per design 4.5.2, for each `(date_local, cp_utc)` and each model `M`:

```
safety_margin = 60 minutes   # Open-Meteo publication latency for ECMWF/GFS at our latency
candidate_runs = { r in archive(M) : r.run_time_utc <= cp_utc - safety_margin }
selected_run   = max(candidate_runs, key=run_time_utc)

target_valid_utc = climo_tmax_hour_local(date_local) -> UTC
lead_h_raw       = (target_valid_utc - selected_run.run_time_utc).total_seconds() / 3600
lead_h           = round_to_step(lead_h_raw, step=model.lead_step_h)   # 1h ECMWF/GFS

if lead_h not in selected_run.available_leads:
    lead_h = nearest_available_lead(selected_run, lead_h_raw)
```

**Hard rules:**
- `safety_margin = 60 minutes` (vs design 4.5.2 default of 30; bumped per Open-Meteo
  observed publication latency for free tier). Configurable in `nzwn/config/model.yaml`
  under `nwp.safety_margin_minutes` but registered with the NWP_SOURCE_VERSION.
- Selection is **deterministic** for a given `(cp_utc, date_local, model_M)`.
- For the 2-model v1 ensemble, both models are selected independently; aggregation
  is `simple mean of t2m at lead_h` and `np.std` for spread.

## Required snapshot fields (REQ-DAT-5 + reforco A)

Each snapshot row, per model, MUST include:

| Field | Type | Source |
|---|---|---|
| `model` | str | one of {`ecmwf_ifs_hres`, `ncep_gfs_global`} in v1 |
| `run_time_utc` | datetime[UTC] | model initialisation time (= "issued") |
| `lead_h` | int | hours from run_time to valid_time |
| `valid_time_utc` | datetime[UTC] | run_time_utc + lead_h hours |
| `t2m_c` | float | temperature_2m forecast in C |
| `cp_utc` | datetime[UTC] | the CP this snapshot serves |
| `source_endpoint` | str | "historical-forecast-api" or "single-runs-api" |
| `sha256` | str | hash of the response payload |

**Causality enforced at dataset-build time (reforco B):**
the builder `core/ingest/nwp.py::ingest_run` MUST validate
`run_time_utc <= cp_utc - safety_margin` and raise `RuntimeError` otherwise.
The `Frozen observation test` (audit phase 2) gets a dedicated check for NWP rows.

## Variables (v1 minimum)

- `temperature_2m` (target signal for residual learning)
- `wind_speed_10m`, `wind_direction_10m`
- `pressure_msl`
- `cloud_cover` (total)
- `precipitation`

Pressure-level variables (500/700/850 hPa T and geopotential) reserved for v1.1.

## Cross-check obligation (T-OPN-5a, reforco C)

Before promoting Phase 4 to "ready", the pipeline MUST run a binary cross-check
between Historical Forecast API and Single Runs API on the overlap window
`2024-03-01 .. 2025-12-31` for ECMWF IFS HRES. Acceptance criteria:

1. `|bracket_match_HFAPI - bracket_match_SingleRuns|` lies inside the bootstrap
   IC95% paired-difference for both 2024 and 2025 sub-windows.
2. `|RPS_HFAPI - RPS_SingleRuns|` lies inside IC95%.
3. `|ECE_HFAPI - ECE_SingleRuns|` <= 0.02.
4. Per-split sanity: split 1 (2023, HFAPI only) gain over baselines is NOT
   more than 1.5 x the gain in splits 2 and 3 (HFAPI w/ SingleRuns coverage).
   Larger split-1-only gain is treated as suspected stitching leakage.

If criteria 1-3 pass and criterion 4 holds, HFAPI is the production source.
If criteria 1-3 pass but criterion 4 fails, HFAPI is allowed only for less
sensitive features (spread/disagreement) and the primary forecast falls back to
SingleRuns ECMWF for the 2024-2025 splits, dropping split 1 from the kill criterion.
If criteria 1-3 fail, HFAPI is rejected; pipeline uses SingleRuns ECMWF only.

## Change protocol

Bump `NWP_SOURCE_VERSION` and re-run T-OPN-5a + the H0 audit. Adding/removing
models, changing `safety_margin`, switching to `customer-api`, or selecting a
different `target_valid_utc` anchor all qualify as version bumps.

## Open items

- API key for `customer-api.open-meteo.com` (Standard tier USD/month) is **not**
  required for v1 backfill (free tier 10k calls/day is sufficient). If we move
  to live operations beyond non-commercial use, Professional tier is needed for
  Historical/Single-Runs APIs.
- Per Open-Meteo licence, attribution is mandatory; we already attribute IEM ASOS
  separately. Both attributions live in `references/legacy/data_sources.md`.
