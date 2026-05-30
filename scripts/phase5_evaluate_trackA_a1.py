"""Track A.A1 one-shot evaluation: sigma winsorization vs the v1.0 baseline.

Pre-registered in ``contracts/phase5_amendment.md`` (conformal_method_version 1.1).
The hash is asserted at startup, so the run refuses to proceed under a silently-edited
amendment. Per ``references/code-reviews/update.txt`` this script is executed EXACTLY
ONCE; the test split is readout only; nothing here re-tunes windows, buckets,
percentiles, the sigma proxy, or the c-rule after seeing the result.

For each split it fits two calibrators on the SAME recent-90d calib tail -- v1.0
(``winsorize=False``, the BEFORE) and A1 (``winsorize=True`` at the frozen ``[P25, P95]``,
the AFTER) -- applies each to test, and reports exactly what A1 promises:

  - effective ``clip_lo`` / ``clip_hi`` per split (calib) + confirmation they are reused
    on test (a leakage check baked into the artifact),
  - per-width-quartile coverage BEFORE vs AFTER (target: pull wide bins from ~1.00 into
    ``[0.70, 0.90]``),
  - widths stay non-degenerate (distinct widths, width std),
  - global calib coverage stays in ``[0.76, 0.84]``.

The het gate is the binding, unchanged bar (per split, never pooled). ECE is a separate
track (C) and is NOT bundled here.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from core.calibration.conformal import (
    NormalizedConformalCalibrator,
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
from core.eval.gates_phase5 import heteroscedasticity_gate
from core.eval.preregistration import (
    PHASE5A_COMMITTED_SHA256,
    assert_phase5a_preregistration_committed,
)
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]
CONFORMAL_METHOD_VERSION_A1 = "1.1"
WINSOR_PCTL_LO = 25.0
WINSOR_PCTL_HI = 95.0


def _recent_tail(calib: pl.DataFrame, per_cp_window_days: int) -> pl.DataFrame:
    from datetime import timedelta

    calib_max = calib["date_local"].max()
    return calib.filter(calib["date_local"] >= calib_max - timedelta(days=per_cp_window_days - 1))


def _config(winsorize: bool) -> NormalizedConformalConfig:
    return NormalizedConformalConfig(
        coverage_target=COVERAGE_TARGET,
        band_lo=COVERAGE_BAND_LO,
        band_hi=COVERAGE_BAND_HI,
        c_start=C_GRID_START,
        c_stop=C_GRID_STOP,
        c_step=C_GRID_STEP,
        sigma_is_variance=SIGMA_IS_VARIANCE,
        method_version=CONFORMAL_METHOD_VERSION_A1 if winsorize else "1.0",
        winsorize=winsorize,
        winsor_pctl_lo=WINSOR_PCTL_LO,
        winsor_pctl_hi=WINSOR_PCTL_HI,
    )


def _fit(recent: pl.DataFrame, winsorize: bool) -> NormalizedConformalCalibrator:
    return fit_normalized_conformal(
        recent["y_true_int"].to_numpy().astype(int),
        recent["y_pred_dec"].to_numpy().astype(float),
        recent[SIGMA_PROXY].to_list(),
        config=_config(winsorize),
    )


def _het_bins(lo: np.ndarray, hi: np.ndarray, y_int: np.ndarray) -> list[dict]:
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


def _evaluate_split(split_name: str, calib: pl.DataFrame, test: pl.DataFrame, *, per_cp_window_days: int) -> dict:
    recent = _recent_tail(calib, per_cp_window_days)
    test_pred = test["y_pred_dec"].to_numpy().astype(float)
    test_y = test["y_true_int"].to_numpy().astype(int)
    test_cp = test["cp"].to_list()
    test_sigma_raw = test[SIGMA_PROXY].to_list()

    arms: dict[str, dict] = {}
    cal_after: NormalizedConformalCalibrator | None = None
    for arm, winsorize in (("before", False), ("after", True)):
        cal = _fit(recent, winsorize)
        if arm == "after":
            cal_after = cal
        lo, hi = apply_normalized_conformal(cal, test_pred, test_sigma_raw)
        cov = coverage_report(lo, hi, test_y, test_cp, target=COVERAGE_TARGET, tol=COVERAGE_TOL)
        bins, het_passed = _het_bins(lo, hi, test_y)
        arms[arm] = {
            "c": cal.c,
            "clip_lo": cal.clip_lo,
            "clip_hi": cal.clip_hi,
            "calib_coverage": cal.calib_coverage,
            "calib_in_band": cal.in_band,
            "test_coverage": cov.coverage,
            "test_coverage_within_tol": cov.within_tol,
            "width": _width_stats(lo, hi),
            "het_bins": bins,
            "het_passed": het_passed,
        }

    # Leakage check baked into the artifact: a test row with raw sigma above the frozen
    # clip_hi must be clamped to clip_hi (apply reuses calib bounds, not test percentiles).
    assert cal_after is not None
    big = [(cal_after.clip_hi * 5.0) ** 2] * 4  # variance whose sqrt is 5x clip_hi
    lo_b, hi_b = apply_normalized_conformal(cal_after, np.full(4, float(test_pred.mean())), big)
    lo_at, hi_at = apply_normalized_conformal(
        cal_after, np.full(4, float(test_pred.mean())), [cal_after.clip_hi ** 2] * 4
    )
    reuse_ok = bool(np.array_equal(lo_b, lo_at) and np.array_equal(hi_b, hi_at))

    return {
        "split": split_name,
        "n_calib": int(calib.height),
        "n_calib_recent": int(recent.height),
        "n_test": int(test.height),
        "clip_lo": cal_after.clip_lo,
        "clip_hi": cal_after.clip_hi,
        "winsor_pctl": [WINSOR_PCTL_LO, WINSOR_PCTL_HI],
        "test_reuses_calib_clip": reuse_ok,
        "before": arms["before"],
        "after": arms["after"],
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
    prereg_hash = assert_phase5a_preregistration_committed()

    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])

    print("[1/3] Building Phase 5 panel (walk-forward, real data) ...")
    panel, _ = build_phase5_panel(_allow_real_data=True)
    print(f"  panel_rows={panel.height}")

    split_names = list(dict.fromkeys(panel["split"].to_list()))
    print(f"[2/3] Evaluating {len(split_names)} splits (Track A.A1; winsorize [P25,P95]) ...")
    results: list[dict] = []
    for s in split_names:
        calib = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_CALIB))
        test = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_TEST))
        if calib.height == 0 or test.height == 0:
            continue
        results.append(_evaluate_split(s, calib, test, per_cp_window_days=per_cp_window_days))

    # Verdict on the AFTER arm against the UNCHANGED gates (per split, never pooled).
    het_ok = all(r["after"]["het_passed"] for r in results)
    coverage_ok = all(r["after"]["test_coverage_within_tol"] for r in results)
    calib_in_band_all = all(COVERAGE_BAND_LO <= r["after"]["calib_coverage"] <= COVERAGE_BAND_HI for r in results)
    widths_non_degenerate = all(r["after"]["width"]["n_distinct_widths"] >= 3 for r in results)
    reuse_ok_all = all(r["test_reuses_calib_clip"] for r in results)

    # Acceptance (pre-registered): wide-bin over-coverage reduced AND calib global in band
    # AND widths non-degenerate. Kill: degenerate widths or calib coverage out of band.
    def _widest_cov(arm: dict) -> float:
        return arm["het_bins"][-1]["coverage"] if arm["het_bins"] else float("nan")

    wide_reduced_all = all(
        _widest_cov(r["after"]) <= _widest_cov(r["before"]) + 1e-9 for r in results
    )
    accept_a1 = bool(wide_reduced_all and calib_in_band_all and widths_non_degenerate)
    kill_hit = bool((not widths_non_degenerate) or (not calib_in_band_all))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = {
        "method": CONFORMAL_METHOD,
        "conformal_method_version": CONFORMAL_METHOD_VERSION_A1,
        "sigma_proxy": SIGMA_PROXY,
        "winsor_pctl": [WINSOR_PCTL_LO, WINSOR_PCTL_HI],
        "c_grid": [C_GRID_START, C_GRID_STOP, C_GRID_STEP],
        "coverage_target": COVERAGE_TARGET,
        "coverage_tol": COVERAGE_TOL,
        "heterosced_band": [HETEROSCED_COVERAGE_LOW, HETEROSCED_COVERAGE_HIGH],
        "heterosced_n_bins": HETEROSCED_N_BINS,
        "per_cp_window_days": per_cp_window_days,
    }

    out = {
        "phase": 5,
        "track": "A.A1",
        "hypothesis": "trackA_a1_sigma_winsor",
        "prereg_sha256": prereg_hash,
        "run_id": run_id,
        "config": snapshot,
        "splits": results,
        "gates_after": {
            "coverage_within_tol_all_splits": coverage_ok,
            "heteroscedasticity_passed_all_splits": het_ok,
            "calib_global_in_band_all_splits": calib_in_band_all,
            "widths_non_degenerate_all_splits": widths_non_degenerate,
            "test_reuses_calib_clip_all_splits": reuse_ok_all,
        },
        "acceptance": {
            "wide_bin_overcoverage_reduced_all_splits": wide_reduced_all,
            "accept_a1": accept_a1,
            "kill_hit": kill_hit,
        },
        "notes": [
            "ECE is a separate track (C); NOT bundled here (one hypothesis per change-set).",
            "het gate is the unchanged binding bar, evaluated per split (never pooled).",
            "no percentile/window/proxy/c-rule re-tuning after results (anti-gaming).",
        ],
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase5_trackA_a1.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii"
    )
    (out_dir / "phase5_trackA_a1.md").write_text(_render_md(out), encoding="ascii")
    audit_dir = _write_audit(
        run_id, prereg_hash, snapshot, "py -m scripts.phase5_evaluate_trackA_a1"
    )

    print("\n[3/3] verdict (AFTER arm vs unchanged gates)")
    print(f"  prereg sha256: {prereg_hash[:16]}...  run_id={run_id}")
    for r in results:
        print(
            f"  {r['split']}: clip=[{r['clip_lo']:.3f},{r['clip_hi']:.3f}] reuse={r['test_reuses_calib_clip']} "
            f"| widest bin cov {_widest_cov(r['before']):.3f}->{_widest_cov(r['after']):.3f} "
            f"| het_passed={r['after']['het_passed']} "
            f"| test_cov={r['after']['test_coverage']:.4f} "
            f"distinct_w={r['after']['width']['n_distinct_widths']}"
        )
    print(f"  het passed (all splits):            {het_ok}")
    print(f"  coverage within tol (all splits):   {coverage_ok}")
    print(f"  calib global in band (all splits):  {calib_in_band_all}")
    print(f"  widths non-degenerate (all splits): {widths_non_degenerate}")
    print(f"  ACCEPT A1: {accept_a1}   KILL hit: {kill_hit}")
    print(f"  see {out_dir / 'phase5_trackA_a1.md'}  audit {audit_dir}")
    return 0 if het_ok else 1


def _render_md(out: dict) -> str:
    cfg = out["config"]
    lines = [
        "# Phase 5 - Track A.A1: sigma winsorization (one-shot)",
        "",
        f"- Hypothesis: `{out['hypothesis']}` (conformal_method_version "
        f"`{cfg['conformal_method_version']}`; pre-reg sha256 `{out['prereg_sha256'][:16]}...`)",
        f"- Change: winsorize `sigma_hat = sqrt({cfg['sigma_proxy']})` to calib-frozen "
        f"`[P{int(cfg['winsor_pctl'][0])}, P{int(cfg['winsor_pctl'][1])}]`, used in score u AND interval.",
        f"- Unchanged gates: coverage `{cfg['coverage_target']:.2f} +/- {cfg['coverage_tol']:.2f}`; "
        f"het per-width-quartile in `[{cfg['heterosced_band'][0]:.2f}, {cfg['heterosced_band'][1]:.2f}]` "
        f"({cfg['heterosced_n_bins']} bins); run_id `{out['run_id']}`.",
        "",
        f"- **ACCEPT A1: {out['acceptance']['accept_a1']}**  (wide-bin over-coverage reduced "
        f"all splits: {out['acceptance']['wide_bin_overcoverage_reduced_all_splits']}; "
        f"KILL hit: {out['acceptance']['kill_hit']})",
        f"- **Heteroscedasticity passed (all splits): {out['gates_after']['heteroscedasticity_passed_all_splits']}**",
        f"- **Coverage within tol (all splits): {out['gates_after']['coverage_within_tol_all_splits']}**",
        f"- Calib global in band (all splits): {out['gates_after']['calib_global_in_band_all_splits']}",
        f"- Widths non-degenerate (all splits): {out['gates_after']['widths_non_degenerate_all_splits']}",
        f"- Test reuses calib clip (no leak, all splits): {out['gates_after']['test_reuses_calib_clip_all_splits']}",
        "",
        "## Effective clip bounds per split (calib-frozen; reused on test)",
        "",
        "| split | clip_lo | clip_hi | test reuses clip | calib cov (after) | in band |",
        "|-------|---------|---------|------------------|-------------------|---------|",
    ]
    for r in out["splits"]:
        a = r["after"]
        lines.append(
            f"| {r['split']} | {r['clip_lo']:.3f} | {r['clip_hi']:.3f} | "
            f"{r['test_reuses_calib_clip']} | {a['calib_coverage']:.4f} | {a['calib_in_band']} |"
        )
    lines.extend([
        "",
        "## Per-width-quartile coverage: BEFORE (v1.0) vs AFTER (winsorized)",
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
        "## Width non-degeneracy + global coverage (after)",
        "",
        "| split | distinct widths | width std | mean width | test coverage | within tol |",
        "|-------|-----------------|-----------|------------|---------------|------------|",
    ])
    for r in out["splits"]:
        a = r["after"]
        w = a["width"]
        lines.append(
            f"| {r['split']} | {w['n_distinct_widths']} | {w['width_std']:.2f} | "
            f"{w['mean_width']:.2f} | {a['test_coverage']:.4f} | {a['test_coverage_within_tol']} |"
        )
    lines.extend(["", "## Notes", ""])
    for n in out["notes"]:
        lines.append(f"- {n}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
