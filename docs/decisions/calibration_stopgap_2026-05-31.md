# T-9-7 Decision Memo: Calibration Stopgap (2026-05-31)

**Status:** ACTIVE (diagnostic only)
**Supersedes:** None
**Retired when:** A method passes REQ-AUD-5 het gate in >= 2/3 splits (e.g. T-9-5 GO)

---

## 1. Decision

Formalize `ridge_conformal_minimal` (per-CP IC80 = 80th-percentile of Ridge integer
abs-residuals) as the DIAGNOSTIC-ONLY stopgap interval while the calibration roof
remains open.

This interval has NOT passed conditional calibration. REQ-AUD-5 remains RED.

---

## 2. Calibration status (NOT passed)

`ridge_conformal_minimal` over-covers at ~0.86-0.91 across walk-forward test splits.
Intervals are conservatively wide. The structural over-coverage is global (both calm
and non-calm regimes exceed band; conditioning does not isolate slack).

Per-CP observed coverage (from `reports/ridge_conformal_probe.md`):

| split | overall | 20:00 | 21:00 | 22:00 | 23:00 | mean width |
|-------|---------|-------|-------|-------|-------|------------|
| 2023  |  0.888  | 0.82  | 0.88  | 0.96  | 0.89  |    4.50    |
| 2024  |  0.905  | 0.91  | 0.88  | 0.96  | 0.87  |    5.00    |
| 2025  |  0.858  | 0.81  | 0.87  | 0.84  | 0.92  |    4.00    |

REQ-AUD-5 het gate: FAIL on all splits (width-quartile coverage not within [0.70, 0.90]).

---

## 3. Trade gate: UNCHANGED, DISABLED

`confidence.gate_enabled_in_production: false` remains in force (nzwn/config/model.yaml).
The decision engine path is frozen and unchanged. This stopgap does NOT gate, enable,
or influence any trade or execution decision. No Polymarket or execution code is touched.

---

## 4. Required report fences

Whenever the stopgap IC is displayed in any report or output, the following banner
MUST be shown:

```
DIAGNOSTIC IC | over-covers ~0.86-0.91 | NOT calibrated | not for sizing
```

Additionally, the per-CP coverage table from Section 2 above must accompany any
display of the interval to provide honest context on per-CP variation.

---

## 5. Exit condition

This stopgap is RETIRED when:

- A replacement method passes the REQ-AUD-5 heteroscedasticity gate in >= 2/3
  walk-forward splits (per-width-quartile coverage within [0.70, 0.90] per split).

Until that condition is met, `ridge_conformal_minimal` is the only interval the
project displays, and only as a diagnostic monitor.

---

## 6. Cross-references

- **T-9-5** (native integer conformal): Active replacement attempt targeting the
  calibration roof directly. If T-9-5 passes REQ-AUD-5, this stopgap is retired.
- **T-9-6** (NWP-spread feasibility): If T-9-5 KILLs, NWP-spread sigma becomes the
  next physical axis for a calibrated IC; this stopgap remains standing diagnostic
  until that or another hypothesis delivers a GO.
- `reports/ridge_conformal_probe.md`: Source of per-CP coverage numbers.
- `reports/phase5_closure.md`: Phase 5 NOT READY closure (structural over-coverage).
- `reports/calibration/conditional_calibration_v0.md`: T-9-3 KILL (global over-coverage).

---

## 7. Scope constraints (this memo)

- DOC-ONLY. No code changes. No config changes.
- Documents existing state; does not alter any system behavior.
- Phase 5 closure is not reopened.
