"""Track P one-shot evaluation: predictive-distribution uncertainty as the difficulty axis.

Pre-registered in ``contracts/phase5_amendment_trackP_predictive_uncertainty.md``
(conformal_method_version 1.3; canonical PREREG sha256 pinned as ``PHASE5P_COMMITTED_SHA256``).
The hash is asserted at startup, so the run refuses to proceed under a silently-edited
amendment. Per ``references/code-reviews/update.txt`` Passo 3 the single change is
``sigma_hat = entropy(prob_dist)`` (Shannon, nats, raw) plugged into the UNCHANGED v1.0
normalized quantization-aware conformal machinery (``sigma_is_variance=False``, floor at the
calib P1). NOTHING else moves: gates, windows, splits, c-rule are all v1.0.

RUN DISCIPLINE (binding, reviewer-required):

  1. The two MANDATORY read-only sanity checks run FIRST, on CALIB ONLY, per split:
       - Spearman rho(sigma_hat, |y_true_int - Q(y_pred_dec)|) positive and >= 0.10;
       - every CP (explicitly 22:00 and 23:00) has >= 3 distinct calib sigma_hat values.
  2. ONLY if BOTH checks pass on EVERY split is the single ``phase5_evaluate`` one-shot
     permitted. If ANY check fails on ANY split, the proxy is REJECTED: the one-shot is
     NOT run, the result is recorded as ``proxy_rejected``, and a NEW pre-registered
     hypothesis (Track P') is opened. No threshold/floor/c-rule re-tuning, ever.

The het gate is the binding, unchanged bar (per split, never pooled). ECE is a separate
track (C) and is NOT bundled here. The test split is readout only.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from core.calibration.conformal import (
    NormalizedConformalConfig,
    apply_normalized_conformal,
    coverage_report,
    fit_normalized_conformal,
)
from core.contracts.phase5 import (
    C_GRID_START,
    C_GRID_STEP,
    C_GRID_STOP,
    CONFORMAL_METHOD,
    COVERAGE_BAND_HI,
    COVERAGE_BAND_LO,
    COVERAGE_TARGET,
    COVERAGE_TOL,
    HETEROSCED_COVERAGE_HIGH,
    HETEROSCED_COVERAGE_LOW,
    HETEROSCED_N_BINS,
    ROLE_CALIB,
    ROLE_TEST,
    SIGMA_IS_VARIANCE,
    SIGMA_PROXY,
)
from core.contracts.quantization import Q
from core.eval.gates_phase5 import heteroscedasticity_gate
from core.eval.preregistration import assert_phase5p_preregistration_committed
from core.eval.sanity_trackP import (
    entropy_sigma_hat,
    monotonicity_sanity,
    per_cp_distinct_sanity,
)
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]
CONFORMAL_METHOD_VERSION_P = "1.3"
# These mirror the hashed PREREG block; the startup hash assert guards against drift.
TRACKP_SIGMA_FLOOR_PERCENTILE = 1.0
TRACKP_MONOTONICITY_MIN_RHO = 0.10
TRACKP_BY_CP_MIN_DISTINCT = 3
TRACKP_BY_CP_FOCUS = ("22:00", "23:00")
ENTROPY_COL = "entropy_sigma"


def _recent_tail(calib: pl.DataFrame, per_cp_window_days: int) -> pl.DataFrame:
    calib_max = calib["date_local"].max()
    return calib.filter(calib["date_local"] >= calib_max - timedelta(days=per_cp_window_days - 1))


def _v1_config() -> NormalizedConformalConfig:
    return NormalizedConformalConfig(
        coverage_target=COVERAGE_TARGET,
        band_lo=COVERAGE_BAND_LO,
        band_hi=COVERAGE_BAND_HI,
        c_start=C_GRID_START,
        c_stop=C_GRID_STOP,
        c_step=C_GRID_STEP,
        sigma_is_variance=SIGMA_IS_VARIANCE,
        method_version="1.0",
        winsorize=False,
    )


def _trackP_config() -> NormalizedConformalConfig:
    # Exactly one variable changes vs v1.0: sigma_hat = entropy (not a variance), floored
    # at the calib P1. The c-grid, bands, and method family are identical to v1.0.
    return NormalizedConformalConfig(
        coverage_target=COVERAGE_TARGET,
        band_lo=COVERAGE_BAND_LO,
        band_hi=COVERAGE_BAND_HI,
        c_start=C_GRID_START,
        c_stop=C_GRID_STOP,
        c_step=C_GRID_STEP,
        sigma_is_variance=False,
        method_version=CONFORMAL_METHOD_VERSION_P,
        winsorize=False,
        sigma_floor_percentile=TRACKP_SIGMA_FLOOR_PERCENTILE,
    )


def _het_bins(lo: np.ndarray, hi: np.ndarray, y_int: np.ndarray):
    rep = heteroscedasticity_gate(
        lo, hi, y_int,
        n_bins=HETEROSCED_N_BINS,
        low=HETEROSCED_COVERAGE_LOW,
        high=HETEROSCED_COVERAGE_HIGH,
    )
    return [
        {
            "width_lo": b.width_lo, "width_hi": b.width_hi,
            "coverage": b.coverage, "mean_width": b.mean_width, "n": b.n,
            "in_band": HETEROSCED_COVERAGE_LOW <= b.coverage <= HETEROSCED_COVERAGE_HIGH,
        }
        for b in rep.bins
    ], rep.passed


def _width_stats(lo: np.ndarray, hi: np.ndarray) -> dict:
    w = (np.asarray(hi, dtype=int) - np.asarray(lo, dtype=int) + 1).astype(float)
    return {
        "mean_width": float(w.mean()),
        "width_std": float(w.std()),
        "n_distinct_widths": int(np.unique(w).size),
    }


def _coverage_arm(lo, hi, y_int, cp) -> dict:
    cov = coverage_report(lo, hi, y_int, cp, target=COVERAGE_TARGET, tol=COVERAGE_TOL)
    bins, het_passed = _het_bins(lo, hi, y_int)
    # Stratified per-CP coverage (the late-CP regime 22:00/23:00 is where the audit
    # localized the structural over-coverage).
    by_cp = {
        str(k): {"coverage": v[0], "mean_width": v[1], "n": v[2]}
        for k, v in cov.by_cp.items()
    }
    return {
        "test_coverage": cov.coverage,
        "test_coverage_within_tol": cov.within_tol,
        "width": _width_stats(lo, hi),
        "het_bins": bins,
        "het_passed": het_passed,
        "by_cp": by_cp,
    }


def _sanity_for_split(recent: pl.DataFrame) -> dict:
    """The two MANDATORY calib-only sanity checks on the recent-tail calib set."""
    sigma_hat = recent[ENTROPY_COL].to_numpy().astype(float)
    y_int = recent["y_true_int"].to_numpy().astype(int)
    pred = recent["y_pred_dec"].to_numpy().astype(float)
    cp = recent["cp"].to_list()
    abs_error_int = np.abs(y_int - np.array([Q(float(p)) for p in pred], dtype=int)).astype(float)

    mono = monotonicity_sanity(
        sigma_hat, abs_error_int, min_rho=TRACKP_MONOTONICITY_MIN_RHO, require_positive=True
    )
    distinct = per_cp_distinct_sanity(
        sigma_hat, cp, focus_cps=TRACKP_BY_CP_FOCUS, min_distinct=TRACKP_BY_CP_MIN_DISTINCT
    )
    return {
        "monotonicity": mono,
        "per_cp_distinct": distinct,
        "passed": bool(mono["passed"] and distinct["passed"]),
    }


def _evaluate_split_oneshot(
    split_name: str, recent: pl.DataFrame, test: pl.DataFrame
) -> dict:
    """Fit BEFORE (v1.0, p50_var) and AFTER (Track P, entropy) and read out on test."""
    rc_y = recent["y_true_int"].to_numpy().astype(int)
    rc_pred = recent["y_pred_dec"].to_numpy().astype(float)
    rc_sigma_v1 = recent[SIGMA_PROXY].to_list()
    rc_sigma_p = recent[ENTROPY_COL].to_list()

    test_pred = test["y_pred_dec"].to_numpy().astype(float)
    test_y = test["y_true_int"].to_numpy().astype(int)
    test_cp = test["cp"].to_list()
    test_sigma_v1 = test[SIGMA_PROXY].to_list()
    test_sigma_p = test[ENTROPY_COL].to_list()

    cal_v1 = fit_normalized_conformal(rc_y, rc_pred, rc_sigma_v1, config=_v1_config())
    lo_b, hi_b = apply_normalized_conformal(cal_v1, test_pred, test_sigma_v1)
    before = _coverage_arm(lo_b, hi_b, test_y, test_cp)

    cal_p = fit_normalized_conformal(rc_y, rc_pred, rc_sigma_p, config=_trackP_config())
    lo_a, hi_a = apply_normalized_conformal(cal_p, test_pred, test_sigma_p)
    after = _coverage_arm(lo_a, hi_a, test_y, test_cp)

    # No-leak evidence: the calib-frozen entropy floor is reused on apply unchanged.
    calib_p1 = float(np.percentile(np.asarray(rc_sigma_p, dtype=float), TRACKP_SIGMA_FLOOR_PERCENTILE))

    return {
        "split": split_name,
        "n_calib_recent": int(recent.height),
        "n_test": int(test.height),
        "c_before": cal_v1.c,
        "c_after": cal_p.c,
        "q_lo_after": cal_p.q_lo,
        "q_hi_after": cal_p.q_hi,
        "sigma_floor_after": cal_p.sigma_floor,
        "sigma_floor_is_calib_p1": bool(abs(cal_p.sigma_floor - calib_p1) < 1e-12),
        "sigma_median_after": cal_p.sigma_median,
        "calib_coverage_after": cal_p.calib_coverage,
        "calib_in_band_after": cal_p.in_band,
        "before": before,
        "after": after,
    }


def _write_audit(run_id: str, prereg_hash: str, snapshot: dict, command: str) -> Path:
    audit_dir = REPO / "audits" / run_id / "phase5"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "prereg_hash.txt").write_text(prereg_hash + "\n", encoding="ascii")
    (audit_dir / "config_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii"
    )
    (audit_dir / "command.txt").write_text(command + "\n", encoding="ascii")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - audit must not crash the run if git is unavailable
        commit = "unavailable"
    (audit_dir / "git_commit.txt").write_text(commit + "\n", encoding="ascii")
    return audit_dir


def main() -> int:
    prereg_hash = assert_phase5p_preregistration_committed()

    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])

    print("[1/4] Building Phase 5 panel + prob_dists (walk-forward, real data) ...")
    panel, prob_dists = build_phase5_panel(_allow_real_data=True)
    if len(prob_dists) != panel.height:
        raise AssertionError(
            f"prob_dists ({len(prob_dists)}) not aligned to panel ({panel.height})"
        )
    panel = panel.with_columns(
        pl.Series(ENTROPY_COL, entropy_sigma_hat(prob_dists), dtype=pl.Float64)
    )
    print(f"  panel_rows={panel.height}  entropy attached (nats)")

    split_names = list(dict.fromkeys(panel["split"].to_list()))

    # --- STEP 1 (binding): MANDATORY calib-only sanity checks, per split ---------
    print(f"[2/4] Sanity checks (calib-only, per split) on {len(split_names)} splits ...")
    sanity: list[dict] = []
    recents: dict[str, pl.DataFrame] = {}
    tests: dict[str, pl.DataFrame] = {}
    for s in split_names:
        calib = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_CALIB))
        test = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_TEST))
        if calib.height == 0 or test.height == 0:
            continue
        recent = _recent_tail(calib, per_cp_window_days)
        recents[s] = recent
        tests[s] = test
        res = _sanity_for_split(recent)
        res["split"] = s
        sanity.append(res)
        print(
            f"  {s}: rho={res['monotonicity']['rho']:.4f} "
            f"(>= {TRACKP_MONOTONICITY_MIN_RHO}: {res['monotonicity']['passed']}) "
            f"| per-cp-distinct ok={res['per_cp_distinct']['passed']} "
            f"focus={res['per_cp_distinct']['focus_present']} -> sanity_passed={res['passed']}"
        )

    sanity_all_pass = bool(sanity) and all(r["passed"] for r in sanity)
    proxy_rejected = not sanity_all_pass

    # --- STEP 2: the SINGLE one-shot, ONLY if every split passed sanity ----------
    results: list[dict] = []
    if sanity_all_pass:
        print("[3/4] Sanity PASSED on all splits -> running the one-shot test readout ...")
        for s in split_names:
            if s in recents and s in tests:
                results.append(_evaluate_split_oneshot(s, recents[s], tests[s]))
    else:
        print("[3/4] Sanity FAILED -> proxy REJECTED; one-shot NOT run (open Track P').")

    # Verdict (only meaningful when the one-shot ran).
    het_ok = bool(results) and all(r["after"]["het_passed"] for r in results)
    coverage_ok = bool(results) and all(r["after"]["test_coverage_within_tol"] for r in results)
    calib_in_band_all = bool(results) and all(
        COVERAGE_BAND_LO <= r["calib_coverage_after"] <= COVERAGE_BAND_HI for r in results
    )
    widths_non_degenerate = bool(results) and all(
        r["after"]["width"]["n_distinct_widths"] >= 3 for r in results
    )
    floor_frozen_all = bool(results) and all(r["sigma_floor_is_calib_p1"] for r in results)

    # Acceptance (pre-registered): sanity passes per split AND het gate passes per split on
    # test AND calib global in band AND widths non-degenerate. Kill: sanity fails (reject),
    # or degenerate widths, or calib out of band.
    accept_p = bool(sanity_all_pass and het_ok and calib_in_band_all and widths_non_degenerate)
    kill_hit = bool(
        proxy_rejected
        or (results and ((not widths_non_degenerate) or (not calib_in_band_all)))
    )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = {
        "method": CONFORMAL_METHOD,
        "conformal_method_version": CONFORMAL_METHOD_VERSION_P,
        "sigma_proxy_before": SIGMA_PROXY,
        "sigma_proxy_after": "entropy(prob_dist) [shannon nats, raw]",
        "sigma_floor_percentile": TRACKP_SIGMA_FLOOR_PERCENTILE,
        "monotonicity_min_rho": TRACKP_MONOTONICITY_MIN_RHO,
        "by_cp_min_distinct": TRACKP_BY_CP_MIN_DISTINCT,
        "by_cp_focus": list(TRACKP_BY_CP_FOCUS),
        "c_grid": [C_GRID_START, C_GRID_STOP, C_GRID_STEP],
        "coverage_target": COVERAGE_TARGET,
        "coverage_tol": COVERAGE_TOL,
        "heterosced_band": [HETEROSCED_COVERAGE_LOW, HETEROSCED_COVERAGE_HIGH],
        "heterosced_n_bins": HETEROSCED_N_BINS,
        "per_cp_window_days": per_cp_window_days,
    }

    out = {
        "phase": 5,
        "track": "P",
        "hypothesis": "trackP_predictive_uncertainty_sigma",
        "prereg_sha256": prereg_hash,
        "run_id": run_id,
        "config": snapshot,
        "sanity": sanity,
        "sanity_all_pass": sanity_all_pass,
        "proxy_rejected": proxy_rejected,
        "one_shot_ran": bool(results),
        "splits": results,
        "gates_after": {
            "coverage_within_tol_all_splits": coverage_ok,
            "heteroscedasticity_passed_all_splits": het_ok,
            "calib_global_in_band_all_splits": calib_in_band_all,
            "widths_non_degenerate_all_splits": widths_non_degenerate,
            "sigma_floor_frozen_calib_p1_all_splits": floor_frozen_all,
        },
        "acceptance": {
            "sanity_checks_pass_per_split": sanity_all_pass,
            "het_gate_passes_all_splits": het_ok,
            "accept_p": accept_p,
            "kill_hit": kill_hit,
        },
        "notes": [
            "Exactly one variable changed: sigma_hat = entropy(prob_dist); nothing else moved.",
            "Sanity checks are calib-only, per split, BINDING: a fail rejects the proxy and "
            "the one-shot is NOT run (open Track P', new prereg).",
            "het gate is the unchanged binding bar, evaluated per split (never pooled).",
            "ECE is a separate track (C); NOT bundled here (one hypothesis per change-set).",
            "Track P is a branch off v1.0 (NOT bundled with A1 winsorization or A3 Mondrian).",
            "No floor/threshold/c-rule re-tuning after results.",
        ],
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase5_trackP.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii"
    )
    (out_dir / "phase5_trackP.md").write_text(_render_md(out), encoding="ascii")
    audit_dir = _write_audit(
        run_id, prereg_hash, snapshot, "py -m scripts.phase5_evaluate_trackP"
    )

    print("\n[4/4] verdict")
    print(f"  prereg sha256: {prereg_hash[:16]}...  run_id={run_id}")
    print(f"  sanity passed (all splits): {sanity_all_pass}   proxy_rejected: {proxy_rejected}")
    if results:
        for r in results:
            print(
                f"  {r['split']}: het_passed={r['after']['het_passed']} "
                f"test_cov={r['after']['test_coverage']:.4f} "
                f"distinct_w={r['after']['width']['n_distinct_widths']} "
                f"calib_cov={r['calib_coverage_after']:.4f} floor_p1={r['sigma_floor_is_calib_p1']}"
            )
        print(f"  het passed (all splits):            {het_ok}")
        print(f"  coverage within tol (all splits):   {coverage_ok}")
        print(f"  calib global in band (all splits):  {calib_in_band_all}")
        print(f"  widths non-degenerate (all splits): {widths_non_degenerate}")
    print(f"  ACCEPT P: {accept_p}   KILL hit: {kill_hit}")
    print(f"  see {out_dir / 'phase5_trackP.md'}  audit {audit_dir}")
    # Exit 0 only when the het gate passes on every split (the binding bar). A proxy
    # rejection or an honest het-fail returns non-zero, mirroring the A1/A3 evaluators.
    return 0 if (sanity_all_pass and het_ok) else 1


def _render_md(out: dict) -> str:
    cfg = out["config"]
    lines = [
        "# Phase 5 - Track P: predictive-distribution uncertainty as the difficulty axis (one-shot)",
        "",
        f"- Hypothesis: `{out['hypothesis']}` (conformal_method_version "
        f"`{cfg['conformal_method_version']}`; pre-reg sha256 `{out['prereg_sha256'][:16]}...`)",
        f"- Change (exactly one variable): `sigma_hat = {cfg['sigma_proxy_after']}` "
        f"(before: `{cfg['sigma_proxy_before']}`); floored at calib "
        f"P{cfg['sigma_floor_percentile']:.0f}. Everything else is v1.0.",
        f"- Unchanged gates: coverage `{cfg['coverage_target']:.2f} +/- {cfg['coverage_tol']:.2f}`; "
        f"het per-width-quartile in `[{cfg['heterosced_band'][0]:.2f}, {cfg['heterosced_band'][1]:.2f}]` "
        f"({cfg['heterosced_n_bins']} bins); run_id `{out['run_id']}`.",
        "",
        f"- **Sanity passed (all splits): {out['sanity_all_pass']}**  "
        f"(proxy_rejected: {out['proxy_rejected']}; one_shot_ran: {out['one_shot_ran']})",
        f"- **ACCEPT P: {out['acceptance']['accept_p']}**  "
        f"(het gate passes all splits: {out['acceptance']['het_gate_passes_all_splits']}; "
        f"KILL hit: {out['acceptance']['kill_hit']})",
        "",
        "## MANDATORY pre-run sanity checks (calib-only, per split)",
        "",
        "| split | Spearman rho | rho >= min | per-CP distinct ok | 22:00 distinct | 23:00 distinct | sanity passed |",
        "|-------|--------------|------------|--------------------|----------------|----------------|---------------|",
    ]
    for r in out["sanity"]:
        mono = r["monotonicity"]
        dist = r["per_cp_distinct"]
        d2200 = dist["by_cp_distinct"].get("22:00", "absent")
        d2300 = dist["by_cp_distinct"].get("23:00", "absent")
        lines.append(
            f"| {r['split']} | {mono['rho']:.4f} | {mono['passed']} | {dist['passed']} | "
            f"{d2200} | {d2300} | {r['passed']} |"
        )

    if not out["one_shot_ran"]:
        lines.extend([
            "",
            "## One-shot NOT run (proxy rejected)",
            "",
            "At least one split failed a MANDATORY sanity check, so per the pre-registration "
            "the single `phase5_evaluate` one-shot was NOT executed. The entropy proxy is "
            "rejected on its honest terms; the next step is a DIFFERENT pre-registered "
            "hypothesis (Track P'), NOT a re-tuning of this one.",
            "",
            "## Notes",
            "",
        ])
        for n in out["notes"]:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    lines.extend([
        "",
        "## Per-width-quartile coverage: BEFORE (v1.0 p50_var) vs AFTER (Track P entropy)",
        "",
        "| split | arm | per-bin coverage [w_lo-w_hi] cov (n) | het passed |",
        "|-------|-----|--------------------------------------|------------|",
    ])
    for r in out["splits"]:
        for arm in ("before", "after"):
            a = r[arm]
            bins = "; ".join(
                f"[{b['width_lo']:.0f}-{b['width_hi']:.0f}] {b['coverage']:.3f} (n={b['n']})"
                for b in a["het_bins"]
            )
            lines.append(f"| {r['split']} | {arm} | {bins} | {a['het_passed']} |")
    lines.extend([
        "",
        "## Late-CP stratified coverage (22:00 / 23:00) - AFTER",
        "",
        "| split | cp | coverage | mean width | n |",
        "|-------|----|----------|------------|---|",
    ])
    for r in out["splits"]:
        by_cp = r["after"]["by_cp"]
        for cp in ("22:00", "23:00"):
            if cp in by_cp:
                v = by_cp[cp]
                lines.append(
                    f"| {r['split']} | {cp} | {v['coverage']:.3f} | {v['mean_width']:.2f} | {v['n']} |"
                )
    lines.extend([
        "",
        "## Width non-degeneracy + global coverage + frozen floor (after)",
        "",
        "| split | distinct widths | width std | mean width | test cov | within tol | calib cov | floor=calib P1 |",
        "|-------|-----------------|-----------|------------|----------|------------|-----------|----------------|",
    ])
    for r in out["splits"]:
        a = r["after"]
        w = a["width"]
        lines.append(
            f"| {r['split']} | {w['n_distinct_widths']} | {w['width_std']:.2f} | "
            f"{w['mean_width']:.2f} | {a['test_coverage']:.4f} | {a['test_coverage_within_tol']} | "
            f"{r['calib_coverage_after']:.4f} | {r['sigma_floor_is_calib_p1']} |"
        )
    lines.extend(["", "## Notes", ""])
    for n in out["notes"]:
        lines.append(f"- {n}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
