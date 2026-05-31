# ECMWF causal-ingest PILOT backfill (T-11-1) - **GO**

- Model `ecmwf_ifs_hres`; run_times 12/12 written. Pilot only; no model/calibration/execution change. Snapshots in artifacts/raw/nwp (gitignored).
- Gate: {'downloads_clean': True, 'all_causal_at_cp23': True, 'cp_coverage_ok': True}
- Next: Full backfill ECMWF single-runs 2024-03..2025-12 (~2680 calls, ~22 partitions); accept split-1 asymmetry (ECMWF only for dates >= 2024-03); run T-OPN-5a cross-check before promoting.

## Causal selection at CP23 (run_time <= cp - 60min)

| date | cp_utc | run_time_utc | valid_time_utc | lead_h | t2m_c | causal |
|------|--------|--------------|----------------|--------|-------|--------|
| 2024-03-16 | 2024-03-15T23:00:00+00:00 | 2024-03-15T12:00:00+00:00 | 2024-03-15T23:00:00+00:00 | 11 | 13.7 | True |
| 2024-07-11 | 2024-07-10T23:00:00+00:00 | 2024-07-10T12:00:00+00:00 | 2024-07-10T23:00:00+00:00 | 11 | 11.3 | True |
