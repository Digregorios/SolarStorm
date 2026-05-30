# Data sources

## NZWN historic METAR (NZWN.csv)

- Source: Iowa Environmental Mesonet (IEM) ASOS network archive.
- URL pattern: https://mesonet.agron.iastate.edu/request/download.phtml?network=NZ__ASOS
- Station: NZWN (Wellington International Airport, New Zealand).
- Timezone of `valid` column: UTC (tz-naive in the CSV; treated as UTC by the ingest layer).
- Cadence: nominal 30 minutes; SPECI messages may appear off-cadence.
- Range observed in the local snapshot: 2020-01-01 to 2026-05-27 (~112,190 rows).
- Use: historic only. Live ingest must come from a feed contract registered below.

## NZWN live METAR (aviationweather.gov) - LIVE feed (registered 2026-05-30)

- Source: NOAA Aviation Weather Center API.
- URL pattern: `https://aviationweather.gov/api/data/metar?ids=<ICAO>&format=raw&hours=<H>`
  (same pattern for every station; NZWN here). Returns raw METAR lines, ~30-min cadence.
- Consumer: `core/ingest/metar_live.py` (`fetch_observations` / `merge_observations`), exposed
  as the `ingest-live` CLI command. Part of the explicit data chain, not just a helper script.
- Timestamp policy: METAR carries only `DDHHMMZ` (day-of-month + time, no month/year). Resolved
  to a full UTC datetime against `now` (current year-month, rolling back one month at the
  boundary; never resolves into the future). See `metar_live._resolve_ts`.
- Schema parity: parsed via the SAME `parse_observations` as the historical CSV (one source of
  truth for the integer temperature `T_obs_int`); wind/QNH extracted for `build_cp_features`.
- Dedupe policy (historical + live): union then `unique(subset=["ts_utc"], keep="last")` sorted
  by `ts_utc` - live wins on an overlapping timestamp. No silent overwrite of the historical CSV.
- License / terms: U.S. Government (NOAA/NWS) public-domain data. Preserve attribution to the
  NOAA Aviation Weather Center; respect the API's fair-use/rate guidance for polling.

## Citation

Iowa Environmental Mesonet, Iowa State University. ASOS-AWOS-METAR Network. Retrieved 2026.

## License / terms

The IEM ASOS download portal states the data are public domain (NOAA / FAA upstream). Uses must:
- preserve attribution to IEM,
- avoid mass mirroring without contacting IEM first,
- prefer derived/aggregated artefacts in this repo over the raw CSV (which is git-ignored).

## NWP forecasts (Phase 4+)

- Provider: Open-Meteo (https://open-meteo.com).
- Endpoints used: `historical-forecast-api.open-meteo.com` (continuous stitched
  timeseries) and `single-runs-api.open-meteo.com` (single-init causal lookup).
- Models in v1: ECMWF IFS HRES (9 km) and NCEP GFS (~13 km), per
  `contracts/nwp_source.md` v1.0.
- Upstream providers: ECMWF (European Centre for Medium-Range Weather Forecasts),
  NOAA NCEP (National Centers for Environmental Prediction).
- License: CC BY 4.0 (Creative Commons Attribution 4.0 International).
- Attribution requirement: any redistribution or derived publication MUST credit
  Open-Meteo and the upstream operational centers (ECMWF, NOAA NCEP).
- Tier: free non-commercial during research / Phase 4 backfill (10k calls/day,
  300k/month). Move to API Professional plan if live commercial use is required.
