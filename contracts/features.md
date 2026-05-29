# Contract: Features (FEATURES_VERSION = 0.1)

> Source: REQ-DAT-2, REQ-CON-5, REQ-AUD-4, design 4.5/4.5.1/4.5.2/8.1.1.
> Frozen on 2026-05-29 as v0.1 (Phase 1 baseline). Bumped to v1.0 once Phase 4 (NWP residual) lands.

## Hard rules

1. Every feature SHALL be assigned `last_input_ts_utc`. The dataset builder validates `feature_max_ts_utc <= cp_utc` (REQ-CON-5, REQ-AUD-4). Violation is a hard error.
2. All rolling/aggregation windows SHALL use `closed='left'` (no inclusion of the right edge).
3. No feature SHALL include `tmpf` or `tmp_c_int` for `ts >= cp_utc`.
4. `T_obs_int` (REQ-CON-3) is for labels and audit only; features may use `T_obs_dec`.
5. `support_K` is computed deterministically per design 4.5.1 and stored in each forecast row.

## Feature inventory v0.1 (Phase 1 baseline)

Per `(date_local, cp_utc)` row:

| Feature                  | Source                                | last_input_ts_utc                |
|--------------------------|---------------------------------------|----------------------------------|
| `t_so_far_max_c_int`     | max of `tmp_c_int` in `[day_start, cp_utc)` | last obs `< cp_utc`         |
| `t_so_far_max_age_min`   | minutes since `t_so_far_max_c_int` was set | derived                       |
| `last_obs_tmp_c_int`     | latest `tmp_c_int < cp_utc`           | last obs `< cp_utc`              |
| `last_obs_dwp_c_int`     | latest `dwp_c_int < cp_utc`           | last obs `< cp_utc`              |
| `slope_3h_c_per_h`       | OLS slope of `tmp_c_dec` over `[cp - 3h, cp)` | cp_utc - epsilon         |
| `slope_6h_c_per_h`       | same over 6h                          | cp_utc - epsilon                 |
| `time_since_new_max_min` | minutes since `t_so_far_max_c_int` increased | derived                    |
| `wind_dir_sin`, `wind_dir_cos` | from `drct` of latest obs `< cp_utc` | last obs                     |
| `wind_speed_kt`          | latest `< cp_utc`                     | last obs                         |
| `qnh_hpa`                | latest `< cp_utc`                     | last obs                         |
| `dp_qnh_3h`              | delta over `[cp - 3h, cp)`            | cp_utc - epsilon                 |
| `vis_km`                 | latest `< cp_utc`                     | last obs                         |
| `ceiling_m`              | min skyl over `[cp - 1h, cp)`         | cp_utc - epsilon                 |
| `wx_has_rain`, `wx_has_thunder`, `wx_has_haze` | derived from `wxcodes` over `[cp - 3h, cp)` | cp_utc - epsilon |
| `clim_tmax_c_dec`        | smoothed climatology table by `(month, day)` (train-only) | climatology trained pre-cp |
| `clim_tmax_int`          | `Q(clim_tmax_c_dec)`                  | as above                         |
| `tmax_d_minus_1_int`     | label of D-1                          | end of D-1 local                 |
| `tmin_d_minus_1_int`     | label of D-1                          | end of D-1 local                 |

## Reserved for v1.0 (Phase 4+)

- `nwp_mean_c_dec`, `nwp_spread_c`, `nwp_disagreement_score`, `nwp_selected_run_id`, `nwp_selected_lead_h` (design 4.5.2).
- `regime_id`, `regime_proba` (design 7).

## Change protocol

Bump `FEATURES_VERSION` and re-train baselines/models that depend on the schema. CI guard rejects features without `last_input_ts_utc`.
