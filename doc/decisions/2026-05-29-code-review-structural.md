# Decision note - 2026-05-29 - Code review structural findings

> Source: `code-review.md` Phase 0/1/2 review.
> Status: decisions logged; implementation tracked in tasks.md.

This note records how we handled review findings that are NOT plain bug fixes
and required an architectural call. The 9 immediate fixes (1, 2, 3, 4, 5, 7, 11,
12, 13) were applied directly in the same commit as this note.

---

## Finding #6 - `build_panel` is O(n^2)

**Status:** PARTIALLY ADDRESSED in this commit; full fix deferred to Phase 3
(when scaling pressure first appears).

**What we changed now:**
- `build_panel` now precomputes a `label_map: dict[date, dict]` in a single O(n)
  pass over `labels` and uses it for `tmax_int` / `day_complete` lookups.
- This collapses ~2 polars `filter` calls per day into a dict lookup.

**What we did not change:**
- `build_cp_features` still scans `observations` (~112k rows) once per
  `(date, cp)` call. That is `len(dates) * len(cp_set)` = ~9 360 scans for the
  full historical dataset. Empirically this completes the smoke run in ~5-8 s,
  so it is not a production blocker today.

**When the deferred work becomes mandatory:**
- Phase 3 walk-forward (`>=3 splits` with grid search over Ridge alpha) will
  multiply the panel build by ~40x. If wall-clock exceeds 60 s, switch to a
  vectorised builder that windows `observations` once per day rather than per
  CP.
- Documented as task `T-3-9` (see tasks.md).

---

## Finding #8 + #9 - `features.yaml` not consumed; declared features not implemented

**Status:** DECIDED to bump `FEATURES_VERSION` from `0.1` to `0.1.1` and trim
the contract to match what `build_cp_features` actually produces today. The
deleted features are moved to a "Reserved for v1.0" appendix in the contract.

**Rationale:**
- Implementing the missing 7 features (`last_obs_dwp_c_int`,
  `time_since_new_max_min`, `wind_dir_sincos`, `dp_qnh_3h`, `vis_km`,
  `ceiling_m`, `wx_has_*`) right now would (a) take ~1 day of work (b) require
  contract bumps and an audit re-run anyway and (c) produce features that we do
  not have a baseline model consuming yet (Phase 2 baselines use only
  climatology + `k_cp`).
- Trimming the contract restores honesty: the artefact `contracts/features.md`
  declares exactly what `build_cp_features` returns. Future expansion is gated
  on a contract bump (REQ-CON-1 change protocol).

**`features.yaml` consumption** is also deferred. Two options remain on the
table for Phase 3 / Phase 4:
1. Wire `nzwn/config/features.yaml` into `build_cp_features` so toggles
   actually skip computation. Aligns with the original spec intent.
2. Delete `features.yaml` and replace it with a Python `FeatureSet` enum in
   `core/contracts/features.py`. Removes the YAML round-trip but loses the
   "one place to look" benefit.

Option (1) is preferred. Tracked as `T-3-10`.

---

## Finding #14 - Manifest reset on every snapshot run

**Status:** ACCEPTED for v0.1; promote to incremental append in Phase 2b
(TAF ingest) or Phase 8 (live odds ingest).

**Rationale:**
- The current ingest pipeline is one-shot historical (read full `NZWN.csv`,
  write all daily snapshots, regenerate manifest sorted). Idempotency is
  preserved: same inputs -> same outputs -> same SHA256s.
- Live / incremental ingest will need an append-with-dedupe model: read
  `manifest.jsonl`, drop entries that mismatch the new file SHA256, append
  new ones, fail if a `(station, date_local)` SHA256 changed (REQ-DAT-1
  forbids silent overwrite of provenance).
- That logic lives in `core/ingest/snapshot.py` and is tracked as `T-2b-5`
  (TAF) and `T-8-3` (live mode).

---

## Finding #15 - Slope uses `tmpf` (Fahrenheit) - REJECTED

**Status:** review finding REJECTED.

**Reasoning:** Design 4.1.1 declares three signal types:
- `T_obs_int` = labels / audit truth (integer from raw METAR).
- `T_obs_dec` = decimal feature derived from `tmpf`. Explicitly the right
  signal for slopes / rolling features.
- `T_latent_dec` = model output (continuous, post-Q quantises to integer).

Using `tmp_c_int` for slope would yield a step function with mostly-zero
slopes and discontinuous transitions, which is strictly worse than decimal
slope. The existing `_compute_slope` is correct.

**Action:** add a one-line comment in `_compute_slope` referencing
design 4.1.1 to make the choice self-documenting. Tracked as part of the
immediate commit (no separate task).
