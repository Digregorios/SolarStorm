# Serving Runbook -- `forecast --model auto` (Phase 3, T-11-9)

**Status:** Phase 3 (no live NWP). Conservative per-CP routing with graceful fallback.
**Cross-ref:** serving matrix `reports/serving/candidate_matrix_v0.{md,json}` (prereg
`contracts/serving_candidate_matrix_v0_prereg.md`, review PASS 10/10); router `core/cli/routing.py`;
CLI `core/cli/forecast.py`; tests `tests/unit/test_routing.py`, `tests/unit/test_cli_auto.py`.

## What `--model auto` does

`tmax forecast --model auto` consults the FROZEN per-CP routing table from the serving candidate matrix
and serves the most conservative model the CLI can run today.

Routing table (`recommend_route`):

| CP        | NWP availability         | model_route     |
|-----------|--------------------------|-----------------|
| 20/21/22  | ECMWF causal present     | ecmwf_residual  |
| 20/21/22  | only GFS causal present  | gfs_residual    |
| 20/21/22  | no causal NWP            | ridge           |
| 23        | (any)                    | ridge           |

Invariants (unit-pinned in `tests/unit/test_routing.py`):
- The `|GFS-ECMWF|` spread is NEVER a routing input (`recommend_route` has no spread parameter; every
  decision records `spread_used=False`). Rationale: the T-11-6 spread study was only FEASIBLE-CONDITIONAL.
- CP23 is decided independently of CP20-22 and is never promoted to GFS: GFS has the lower pooled MAE at
  CP23 but degrades the calm stratum (`calm_ok=false`), so the conservative rule keeps Ridge.

## Phase 3 reality: no live NWP

Phase 3 serving has no NWP wired (live NWP is Phase 5). The CLI calls the router with
`ecmwf_available=False, gfs_available=False`, so:
- every CP routes to `ridge` (CP20-22 via the no-NWP fallback, CP23 by rule), and
- `resolve_servable` keeps `ridge` (the residual models are not servable yet).

If the chosen CP has `< 100` training rows, `auto` degrades to the `empirical` floor instead of raising.
`--model ridge` (explicit) still raises in that case -- only `auto` degrades, and it records the reason
in `routing.degraded_reason`.

## The three `--model` values

- `empirical` (DEFAULT, unchanged): Phase-2 conditional baseline. Still the default; `auto` does NOT
  change it silently.
- `ridge`: Phase-3 band-aware Ridge with climatology anchor (opt-in).
- `auto`: the conservative router above.

## Diagnostic banner

With `--model auto` a diagnostic banner is printed to STDERR (so `--dry-run` STDOUT stays pure JSON):

```
[forecast --model auto] CP22 route=ridge served=ridge fallback=True reason=no_causal_nwp_fallback_ridge
  nwp: ecmwf=False gfs=False run_time=none spread_used=False
  train: 2020-01-01..2025-07-14  IC80: [13, 15]
```

CP23 is a conservative *decision*, not a fallback, so its banner shows `fallback=False` and the
reason comes from `decision_reason` (with `fallback_reason=None`):

```
[forecast --model auto] CP23 route=ridge served=ridge fallback=False reason=cp23_conservative_ridge
  nwp: ecmwf=False gfs=False run_time=none spread_used=False
  train: 2020-01-01..2025-07-14  IC80: [13, 15]
```

(When live NWP lands and GFS is causally available, the CP23 reason becomes
`cp23_conservative_ridge_gfs_not_promoted_calm_degraded` -- still `fallback=False`.)

The emitted forecast row also gains a `routing` block: `cp`, `model_route`, `served_model`,
`fallback_used`, `fallback_reason`, `decision_reason`, `degraded_reason`, `ecmwf_available`,
`gfs_available`, `nwp_run_time_utc`, `spread_used`, `train_start`, `train_end`.

`fallback_reason` is set ONLY when a fallback actually happened (`fallback_used=True`, e.g. ECMWF
absent so CP20-22 drops to GFS or Ridge). A conservative decision that is NOT a fallback -- chiefly
CP23 keeping Ridge instead of the lower-MAE GFS because GFS degrades the calm stratum -- is recorded
separately in `decision_reason`, with `fallback_used=False` and `fallback_reason=None`. This keeps the
two concepts from being conflated in logs (reviewer 2nd-pass A1).

## Usage

```
# dry run: forecast JSON on stdout, diagnostic banner on stderr
tmax forecast --date 2025-07-15 --cp 22 --model auto --dry-run

# write artifact under artifacts/forecasts/
tmax forecast --date 2025-07-15 --cp 22 --model auto
```

`--cp` must be one of the matrix CPs (20/21/22/23); any other CP raises (the matrix covers those only).
The default remains `--model empirical`; pass `--model auto` (or `--model ridge`) explicitly.

## Phase 5 forward-path (no router change)

When live NWP lands (Phase 5), the ONLY change is that the CLI passes real
`ecmwf_available`/`gfs_available` (and `nwp_run_time_utc`) into `recommend_route`, and the residual
models become servable. The SAME table then routes CP20-22 to `ecmwf_residual` / `gfs_residual`. The
router logic and its two invariants do not change.

**Carried risk (from the matrix review):** ECMWF availability at inference time. The CP20-22
ECMWF-residual recommendation depends on a causal ECMWF run (`run_time <= cp - 60min`). The router's
fallback chain (ECMWF -> GFS -> Ridge) is exactly the graceful-degradation path that risk requires.
