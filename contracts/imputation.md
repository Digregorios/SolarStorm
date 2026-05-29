# Contract: Imputation policy (IMPUTATION_VERSION = 1.0)

> Source: REQ-DAT-3, REQ-CON-8. Frozen on 2026-05-29.

## Default rule per feature

| Feature                  | "M" / NaN policy                                    | data_quality flag |
|--------------------------|-----------------------------------------------------|-------------------|
| `tmp_c_int` (T_obs_int)  | regex on `metar`; fallback to `Q(round((tmpf-32)*5/9))` only if `metar` is empty/illegible | `ok`/`imputed`/`missing` (REQ-CON-8) |
| `tmp_c_dec` (T_obs_dec)  | propagate NaN if tmpf is M                          | `ok`/`missing`    |
| `dwp_c_int`              | analogue of `tmp_c_int` (same regex group 2)        | `ok`/`imputed`/`missing` |
| `wind_dir_deg`, `wind_speed_kt` | NaN if M; do not impute                      | `ok`/`missing`    |
| `wind_gust_kt`           | NaN if M; flag `gust_present` False otherwise       | `ok`/`missing`    |
| `qnh_hpa`                | derive from `alti` (inHg -> hPa) when `mslp` is M   | `ok`/`derived`/`missing` |
| `vis_km`                 | converter from `vsby`; NaN if M                     | `ok`/`missing`    |
| `ceiling_m`              | min over skyl1..4 expressed in metres; NaN if all M | `ok`/`missing`    |
| `precip_mm_30m`          | from `p01i` (inches -> mm); NaN if M                | `ok`/`missing`    |
| any rolling feature      | NaN-skip; if `n_valid < n_min`, propagate NaN       | `ok`/`missing`    |

## Hard rules

1. Imputation is **never silent**: every imputation flips `data_quality` for the affected field.
2. The `tmp_c_int` fallback is allowed **only** when the raw `metar` is missing or unreadable (REQ-CON-8).
   Partial regex matches with implausible values (`< -10` or `> 40`) are flagged `missing`, not imputed.
3. Models and labels in `core/` SHALL never read `data_quality == "missing"` rows as truth.
4. Reports SHALL include the per-month rate of `imputed` and `missing` for `tmp_c_int`.
5. Kill criterion: if `fallback_rate_global > 0.5%` over the full dataset, the build fails.

## Change protocol

Bump `IMPUTATION_VERSION` and re-run H0 audit (same as quantization).
