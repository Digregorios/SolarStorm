# T-10-4 Diagnostic IC Display Contract

**Status:** ACTIVE
**Parent:** docs/decisions/calibration_stopgap_2026-05-31.md (T-9-7)
**Scope:** DOC-ONLY governance fence. No code, no config, no decision-engine change.

---

## Purpose

Codify mandatory display rules for the `ridge_conformal_minimal` diagnostic interval
so it cannot be mistaken for a calibrated or operational interval in any report output.

---

## Mandatory Display Rules

Whenever a diagnostic IC appears in ANY report, ALL of the following apply:

### Rule 1 - Banner

The following banner MUST be shown verbatim (or equivalent single-line form):

```
DIAGNOSTIC IC - over-covers ~0.86-0.91 - NOT calibrated (REQ-AUD-5 red) - not for sizing
```

### Rule 2 - Per-CP Empirical Coverage

The per-CP coverage numbers MUST accompany the interval display.
Source: `reports/ridge_conformal_probe.md`.

| split | overall | 20:00 | 21:00 | 22:00 | 23:00 | mean width |
|-------|---------|-------|-------|-------|-------|------------|
| 2023  |  0.888  | 0.82  | 0.88  | 0.96  | 0.89  |    4.50    |
| 2024  |  0.905  | 0.91  | 0.88  | 0.96  | 0.87  |    5.00    |
| 2025  |  0.858  | 0.81  | 0.87  | 0.84  | 0.92  |    4.00    |

REQ-AUD-5 het gate: FAIL on all splits.

### Rule 3 - Never Operational

The diagnostic IC is NEVER presented as an operational or trade interval.
`gate_enabled_in_production: false` remains in force. No sizing, no execution
gating, no trade decision may reference this interval as calibrated.

### Rule 4 - Monitor Only

The interval is a MONITOR. Execution stays frozen and unaffected. The decision
engine path is unchanged. No Polymarket or execution code is touched or enabled.

### Rule 5 - Retirement Condition

This contract is void once a replacement method passes the REQ-AUD-5
heteroscedasticity gate in >= 2/3 walk-forward splits (per-width-quartile
coverage within [0.70, 0.90] per split). Until then, all rules above apply
unconditionally.

---

## Cross-references

- `docs/decisions/calibration_stopgap_2026-05-31.md` (T-9-7): Parent decision.
- `reports/ridge_conformal_probe.md`: Source of per-CP coverage numbers.
- REQ-AUD-5: Conditional calibration requirement (het gate).

---

## Scope Constraints

- DOC-ONLY. No code changes. No config changes.
- Documents display rules; does not implement a renderer.
- Calibration trail is CLOSED; this contract does not reopen it.
