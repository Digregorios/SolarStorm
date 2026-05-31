# ECMWF daily-per-CP causal coverage audit (T-11-7) - **GO**

- Window 2024-03-01..2025-12-31, every local date x 4 CPs. Read-only daily audit over local snapshots; no fetch, no model. run_time <= cp-60min enforced by select_nwp_v1; every selected run re-checked here.
- All CP coverage >= 0.99: True; all selected runs causal: True

| CP | coverage | causal/days | gaps | lead_h min/median/max |
|----|----------|-------------|------|------------------------|
| 20:00 | 1.0 | 671/671 | 0 | 8/8.0/8 |
| 21:00 | 1.0 | 671/671 | 0 | 9/9.0/9 |
| 22:00 | 1.0 | 671/671 | 0 | 10/10.0/10 |
| 23:00 | 1.0 | 671/671 | 0 | 11/11.0/11 |
