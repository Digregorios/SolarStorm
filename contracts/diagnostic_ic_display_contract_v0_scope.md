# Scope: diagnostic_ic_display_contract (T-10-4)

> `scope_version = 1.0` (frozen 2026-05-31). Phase 10. DOC-ONLY governance fence. NO code, NO config,
> NO decision-engine change.

## Why

The T-9-7 stopgap adopted `ridge_conformal_minimal` as a DIAGNOSTIC-ONLY interval. This front turns that
decision into a small, explicit DISPLAY CONTRACT so any future report that shows the diagnostic IC carries
the right fences and cannot be mistaken for a calibrated/operational interval.

## Deliverable

`docs/decisions/diagnostic_ic_display_contract.md` stating the mandatory rules whenever a diagnostic IC is
displayed in ANY report:
1. A banner: "DIAGNOSTIC IC - over-covers ~0.86-0.91 - NOT calibrated (REQ-AUD-5 red) - not for sizing".
2. The per-CP empirical coverage numbers must accompany it (from `reports/ridge_conformal_probe.md`).
3. It must NEVER be presented as the operational/trade interval; `gate_enabled_in_production: false` stays.
4. The interval is a MONITOR; decisions/execution remain frozen and unaffected.
5. Retirement: the contract is void once a method passes the REQ-AUD-5 het gate in >= 2/3 splits.

Cross-reference `docs/decisions/calibration_stopgap_2026-05-31.md` (T-9-7) as the parent decision.

## Scope

ALLOWED: `docs/decisions/diagnostic_ic_display_contract.md` (new). FORBIDDEN: any code, any config flip,
decision-engine, Polymarket/execution. Doc-only; this only DOCUMENTS display rules, it does not implement
a renderer.
