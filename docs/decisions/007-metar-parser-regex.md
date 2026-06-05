# ADR-007: METAR Parser with Regex on Raw Text

- **Date:** 2026-06-04
- **Status:** Accepted

## Context

Polymarket NZWN Tmax contracts settle on the integer degree Celsius reported in the METAR TT/DD group. The IEM ASOS feed provides both the raw METAR text string and a pre-computed `tmpf` (Fahrenheit decimal) field. Using `tmpf` to derive the integer temperature introduces two failure modes:

1. **Rounding mismatch:** `round(F_to_C(tmpf))` can differ from the integer in the METAR text due to Fahrenheit-to-Celsius conversion precision and rounding conventions.
2. **Missing METAR fallback:** When the METAR string is blank or malformed, `tmpf` may still be populated from sensor data that the METAR format could not encode.

The old project's postmortems identified this as a source of silent label errors -- the settlement integer is the METAR text, not a derived conversion. The METAR regex is the authoritative parser.

## Decision

**Extract TT/DD from raw METAR text via anchored regex, with `tmpf` as fallback only.**

The regex in `solarstorm/data/_metar.py`:
```python
_METAR_TT_DD = re.compile(r"\s(M?\d{1,2})/(M?\d{1,2})(?=\s|$)")
```

Key design choices:
- The regex captures the TT/DD group: optional `M` prefix for negative values, 1-2 digits for temperature and dewpoint, separated by `/`.
- The `(?=\s|$)` lookahead (added in commit `54079fe`) ensures the match is at the end of the METAR string or followed by whitespace -- preventing false matches mid-string. The original missing `$` caused the regex to grab temperature groups from REMARKS sections.
- `parse_tmp_c_int_from_row()` returns a `quality` tag: `"ok"` (parsed from METAR), `"imputed"` (fallback from `tmpf`), or `"missing"` (no data).
- `parse_tmp_c_int_from_row()` also validates against plausibility bounds (`tmp_min_c=-10`, `tmp_max_c=40` from `_config.py`).
- Imputation via `tmpf` uses `round((tmpf - 32.0) * 5.0 / 9.0)` -- but the `quality` tag preserves the source, so downstream consumers know whether the integer comes from the METAR text or a conversion.

## Alternatives Considered

1. **Parse `tmpf` only:** Round `F_to_C(tmpf)` and ignore raw METAR. Rejected -- settlement is on the METAR integer, not a derived conversion. The old project's postmortems documented discrepancies.
2. **Parse all temperature groups:** Match every `M?DD/M?DD` pattern in the string. Rejected -- REMARKS sections can contain temperature groups that are not the official TT/DD. The end-of-string anchoring is essential.
3. **Use IEM's pre-parsed `tmpc` field:** The IEM API does not reliably provide a parsed Celsius integer. Rejected because the field is not part of the standard ASOS schema.

## Consequences

### Enabled
- Audit trail from raw METAR text through `quality` tag to settlement integer.
- `ParseStats` tracking: `fallback_rate` and `missing_rate` provide operational monitoring of data quality.
- The `ok`/`imputed`/`missing` quality system allows downstream consumers to condition on data provenance.

### Prevents
- Silent settlement mismatches from Fahrenheit-to-Celsius rounding errors.
- False temperature matches from REMARKS text (e.g., "RMK AO2 T01860149" -- the `6-hourly max temp` group, not the current TT/DD).

## References

- `solarstorm/data/_metar.py` -- `_METAR_TT_DD`, `parse_tmp_c_int_from_row()`, `ParseStats`
- `solarstorm/_config.py` -- `TMP_C_INT_PLAUSIBILITY`
- Commit `54079fe` -- Added `$` (end-of-string) to METAR TT/DD regex to prevent REMARKS contamination
