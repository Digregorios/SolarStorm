# ADR-001: Causal Firewall

- **Date:** 2026-06-04
- **Status:** Accepted

## Context

Time-series forecasting is trivially vulnerable to look-ahead bias. A feature computed from observations at or after the checkpoint leaks future information into the forecast, inflating apparent skill. For Polymarket settlement, where trades execute at known checkpoint times, any feature using data from `ts_utc >= cp_utc` constitutes unauthorized access to the answer.

The old Wellington project did not enforce causality systematically -- features were built from full-day observations without timestamp filtering, making it impossible to distinguish a forecast from a nowcast.

## Decision

Every feature at a checkpoint `cp_utc` MUST satisfy `feature_max_ts < cp_utc` (strict inequality). The invariant is enforced by `require_causal()` in `solarstorm/_contracts.py`, which raises `RuntimeError` on violation -- no silent fallback, no diagnostic downgrade.

The function signature:
```python
def require_causal(*, feature_max_ts: dt.datetime, cp_utc: dt.datetime, label: str = "") -> None:
    if feature_max_ts >= cp_utc:
        raise RuntimeError(...)
```

## Alternatives Considered

1. **Warning-only:** Emit a warning but proceed. Rejected -- a silent violation is worse than a crash because it produces invalid results that look valid.
2. **Per-feature auditing:** Tag each feature with a timestamp and validate at eval time. Rejected as equivalent complexity with less safety -- a centralized firewall is simpler and harder to circumvent.
3. **Closed-left interval semantics:** Allow `feature_max_ts <= cp_utc`. Rejected -- the checkpoint is the moment the market freezes; using an observation at exactly that moment is still a look-ahead (the observation typically posts minutes after the hour).

## Consequences

### Enabled
- Audit trail: every feature row carries an implicit causal timestamp bound.
- Replicability: a second team can independently verify that no feature leaks.
- Nowcast detection: G4 (anti-nowcaster gate) depends on this firewall to identify features that are regressions on `k_cp` in disguise.

### Prevents
- Accidental future-peeking through aggregate windows that extend past the checkpoint.
- Silent inflation of backtest metrics.
- The old project's pattern of "it probably doesn't matter" accumulating into NULL_NOT_BEATEN.

## References

- `solarstorm/_contracts.py` -- `require_causal()`, `ensure_closed_left()`
- `solarstorm/features/builder.py` -- `build_features()` calls `require_causal()` at row assembly
- `solarstorm/data/_labels.py` -- `build_tmax_labels()` filters `valid < cp` for k_cp computation
