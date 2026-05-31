# Scope: ecmwf_causal_ingest_feasibility (T-10-1)

> `scope_version = 1.0` (frozen 2026-05-31). Phase 10. FEASIBILITY MEMO ONLY - no real ingest, no network
> backfill in this front. The output is a decision memo, not a data pipeline.

## Why

T-9-6 found the local NWP archive has only ONE causal model (NCEP GFS) -> no real spread. A second causal
NWP source (ECMWF IFS HRES) is the ONLY remaining lever for both (a) better point and (b) a real NWP-spread
uncertainty axis. Before any ingest work, assess feasibility honestly.

## The feasibility questions (answer from existing project evidence + documented API facts)

1. Does the existing code already SUPPORT ECMWF? (`contracts/nwp_source.md` lists ECMWF IFS HRES in the v1
   launch set; `core/ingest/nwp.py` `select_nwp_v1` is model-parameterized.) What is actually MISSING -
   data, not code?
2. Causal availability: can ECMWF historical FORECAST (not reanalysis/archive) be fetched with explicit
   `run_time_utc` / `valid_time_utc` / `lead_h`, satisfying `run_time <= cp - safety_margin` (60 min)?
   Open-Meteo historical-forecast vs single-runs - which gives causal ECMWF runs, and over what date span?
3. Coverage: would the causal ECMWF overlap the walk-forward splits (2023-2025) enough to be usable, or
   only a partial window (like the GFS 2021-03-22 start that already limited split-1)?
4. Cost / licence / decoder constraints (the GRIB-decode + Windows file-lock issues already hit in this
   project) - what blocks a real backfill?

## Deliverable

`reports/nwp/ecmwf_causal_ingest_feasibility.md` - a memo with GO/NO-GO/CONDITIONAL recommendation:
- GO if a causal ECMWF forecast feed with explicit run_time + adequate 2023-2025 coverage is reachable
  with the existing ingestor (data-only task);
- CONDITIONAL if reachable but with a limited window (propagate the split-1 asymmetry rule already used);
- NO-GO if only reanalysis (non-causal) or no run_time is available, or licence/decoder is blocking.
State the concrete NEXT action (e.g. "backfill ECMWF single-runs 2022-2025 via X; est. N partitions").

## Scope

ALLOWED: `reports/nwp/ecmwf_causal_ingest_feasibility.md` (new memo). May READ `contracts/nwp_source.md`,
`core/ingest/nwp.py`, `docs/guia_portabilidade.md`, prior NWP reports. May make SMALL read-only probes of
already-cached data, but NO large network backfill, NO new ingest pipeline here.
FORBIDDEN: decide.py, decision/**, Polymarket/odds, execution, any contract change, building the ingest.
Doc/feasibility only.
