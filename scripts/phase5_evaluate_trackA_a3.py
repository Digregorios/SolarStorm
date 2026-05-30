"""Track A.A3 one-shot evaluation: Mondrian conditional conformal vs the v1.0 baseline.

Pre-registered in ``contracts/phase5_amendment_trackA_a3.md`` (conformal_method_version
1.2). The hash is asserted at startup, so the run refuses to proceed under a
silently-edited amendment. Per ``references/code-reviews/update.txt`` this script is
executed EXACTLY ONCE; the test split is readout only; nothing here re-tunes n_buckets,
n0, min_n_bucket, the edge quantiles, the quantile method, or the c-rule after seeing the
result.

For each split it fits two calibrators on the SAME recent-90d calib tail -- v1.0
(global ``(q_lo, q_hi)``, the BEFORE) and A3 (per-sigma-bucket shrunk quantiles, the
AFTER) -- applies each to test, and reports exactly what A3 promises:

  - the frozen sigma-bucket partition per split (merged edges + per-bucket calib counts +
    per-bucket shrunk quantiles) and a baked-in no-leak check (far-tail test rows are
    assigned to the TOP bucket via the frozen edges),
  - per-width-quartile coverage BEFORE vs AFTER (the binding het gate, per split),
  - widths stay non-degenerate (distinct widths, width std),
  - global calib coverage stays in ``[0.76, 0.84]``,
  - the kill check: every surviving bucket is non-empty (``>= min_n_bucket``).

The het gate is the binding, unchanged bar (per split, never pooled). ECE is a separate
track (C) and is NOT bundled here.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from core.calibration.conformal import (
    MondrianConformalCalibrator,
    MondrianConformalConfig,
    NormalizedConformalConfig,
    apply_mondrian_conformal,
    apply_normalized_conformal,
    coverage_report,
    fit_mondrian_conformal,
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
from core.eval.preregistration import assert_phase5a3_preregistration_committed
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]
CONFORMAL_METHOD_VERSION_A3 = "1.2"
A3_N_BUCKETS = 4
A3_EDGE_QUANTILES = (0.25, 0.50, 0.75)
A3_QUANTILE_METHOD = "linear"
A3_SEARCHSORTED_SIDE = "right"
A3_MIN_N_BUCKET = 50
A3_SHRINKAGE_N0 = 200.0


def _recent_tail(calib: pl.DataFrame, per_cp_window_days: int) -> pl.DataFrame:
    from datetime import timedelta

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


def _a3_config() -> MondrianConformalConfig:
    return MondrianConformalConfig(
        coverage_target=COVERAGE_TARGET,
        band_lo=COVERAGE_BAND_LO,
        band_hi=COVERAGE_BAND_HI,
        c_start=C_GRID_START,
        c_stop=C_GRID_STOP,
        c_step=C_GRID_STEP,
        sigma_is_variance=SIGMA_IS_VARIANCE,
        method_version=CONFORMAL_METHOD_VERSION_A3,
        n_buckets=A3_N_BUCKETS,
        edge_quantiles=A3_EDGE_QUANTILES,
        quantile_method=A3_QUANTILE_METHOD,
        searchsorted_side=A3_SEARCHSORTED_SIDE,
        min_n_bucket=A3_MIN_N_BUCKET,
        shrinkage_n0=A3_SHRINKAGE_N0,
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
    return {
        "test_coverage": cov.coverage,
        "test_coverage_within_tol": cov.within_tol,
        "width": _width_stats(lo, hi),
        "het_bins": bins,
        "het_passed": het_passed,
    }


def _evaluate_split(split_name: str, calib: pl.DataFrame, test: pl.DataFrame, *, per_cp_window_days: int) -> dict:
    recent = _recent_tail(calib, per_cp_window_days)
    rc_y = recent["y_true_int"].to_numpy().astype(int)
    rc_pred = recent["y_pred_dec"].to_numpy().astype(float)
    rc_sigma = recent[SIGMA_PROXY].to_list()

    test_pred = test["y_pred_dec"].to_numpy().astype(float)
    test_y = test["y_true_int"].to_numpy().astype(int)
    test_cp = test["cp"].to_list()
    test_sigma = test[SIGMA_PROXY].to_list()

    # BEFORE: v1.0 global normalized conformal.
    cal_v1 = fit_normalized_conformal(rc_y, rc_pred, rc_sigma, config=_v1_config())
    lo_b, hi_b = apply_normalized_conformal(cal_v1, test_pred, test_sigma)
    before = _coverage_arm(lo_b, hi_b, test_y, test_cp)

    # AFTER: A3 Mondrian conditional conformal.
    cal_a3 = fit_mondrian_conformal(rc_y, rc_pred, rc_sigma, config=_a3_config())
    lo_a, hi_a = apply_mondrian_conformal(cal_a3, test_pred, test_sigma)
    after = _coverage_arm(lo_a, hi_a, test_y, test_cp)

    # Baked-in no-leak check: rows whose sigma is far above the top calib edge must be
    # assigned to the TOP bucket via the frozen edges (apply reuses calib partition).
    if cal_a3.edges:
        top_var = (cal_a3.edges[-1] * 10.0) ** 2
        probe_pred = np.full(4, float(test_pred.mean()))
        lo_top, hi_top = apply_mondrian_conformal(cal_a3, probe_pred, [top_var] * 4)
        # The same interval must result from explicitly using the top bucket's quantiles.
        from core.calibration.conformal import _normalized_int_interval_vec, _prepare_sigma

        sig_top = _prepare_sigma(
            [top_var] * 4, is_variance=True, median=cal_a3.sigma_median, floor=cal_a3.sigma_floor
        )[0]
        top = len(cal_a3.edges)
        exp_lo, exp_hi = _normalized_int_interval_vec(
            probe_pred, sig_top,
            np.full(4, cal_a3.bucket_q_lo[top]), np.full(4, cal_a3.bucket_q_hi[top]),
        )
        reuse_ok = bool(np.array_equal(lo_top, exp_lo) and np.array_equal(hi_top, exp_hi))
    else:
        reuse_ok = True  # single bucket: trivially reuses the (only) frozen partition

    buckets_non_empty = all(n >= A3_MIN_N_BUCKET for n in cal_a3.bucket_n)

    return {
        "split": split_name,
        "n_calib": int(calib.height),
        "n_calib_recent": int(recent.height),
        "n_test": int(test.height),
        "c_before": cal_v1.c,
        "c_after": cal_a3.c,
        "n_buckets_effective": len(cal_a3.bucket_n),
        "edges": list(cal_a3.edges),
        "bucket_n": list(cal_a3.bucket_n),
        "bucket_q_lo": list(cal_a3.bucket_q_lo),
        "bucket_q_hi": list(cal_a3.bucket_q_hi),
        "q_lo_global": cal_a3.q_lo_global,
        "q_hi_global": cal_a3.q_hi_global,
        "calib_coverage_after": cal_a3.calib_coverage,
        "calib_in_band_after": cal_a3.in_band,
        "buckets_non_empty": buckets_non_empty,
        "test_reuses_calib_partition": reuse_ok,
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
    prereg_hash = assert_phase5a3_preregistration_committed()

    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])

    print("[1/3] Building Phase 5 panel (walk-forward, real data) ...")
    panel, _ = build_phase5_panel(_allow_real_data=True)
    print(f"  panel_rows={panel.height}")

    split_names = list(dict.fromkeys(panel["split"].to_list()))
    print(f"[2/3] Evaluating {len(split_names)} splits (Track A.A3; Mondrian sigma buckets) ...")
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
    calib_in_band_all = all(COVERAGE_BAND_LO <= r["calib_coverage_after"] <= COVERAGE_BAND_HI for r in results)
    widths_non_degenerate = all(r["after"]["width"]["n_distinct_widths"] >= 3 for r in results)
    buckets_non_empty_all = all(r["buckets_non_empty"] for r in results)
    reuse_ok_all = all(r["test_reuses_calib_partition"] for r in results)

    # Acceptance (pre-registered): the het gate PASSES per split on test AND calib global
    # in band AND widths non-degenerate. Kill: degenerate widths, calib out of band, or any
    # empty bucket after merge.
    accept_a3 = bool(het_ok and calib_in_band_all and widths_non_degenerate)
    kill_hit = bool((not widths_non_degenerate) or (not calib_in_band_all) or (not buckets_non_empty_all))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = {
        "method": CONFORMAL_METHOD,
        "conformal_method_version": CONFORMAL_METHOD_VERSION_A3,
        "sigma_proxy": SIGMA_PROXY,
        "n_buckets": A3_N_BUCKETS,
        "edge_quantiles": list(A3_EDGE_QUANTILES),
        "quantile_method": A3_QUANTILE_METHOD,
        "searchsorted_side": A3_SEARCHSORTED_SIDE,
        "min_n_bucket": A3_MIN_N_BUCKET,
        "shrinkage_n0": A3_SHRINKAGE_N0,
        "c_grid": [C_GRID_START, C_GRID_STOP, C_GRID_STEP],
        "coverage_target": COVERAGE_TARGET,
        "coverage_tol": COVERAGE_TOL,
        "heterosced_band": [HETEROSCED_COVERAGE_LOW, HETEROSCED_COVERAGE_HIGH],
        "heterosced_n_bins": HETEROSCED_N_BINS,
        "per_cp_window_days": per_cp_window_days,
    }

    out = {
        "phase": 5,
        "track": "A.A3",
        "hypothesis": "trackA_a3_mondrian_sigma_bucket",
        "prereg_sha256": prereg_hash,
        "run_id": run_id,
        "config": snapshot,
        "splits": results,
        "gates_after": {
            "coverage_within_tol_all_splits": coverage_ok,
            "heteroscedasticity_passed_all_splits": het_ok,
            "calib_global_in_band_all_splits": calib_in_band_all,
            "widths_non_degenerate_all_splits": widths_non_degenerate,
            "buckets_non_empty_all_splits": buckets_non_empty_all,
            "test_reuses_calib_partition_all_splits": reuse_ok_all,
        },
        "acceptance": {
            "het_gate_passes_all_splits": het_ok,
            "accept_a3": accept_a3,
            "kill_hit": kill_hit,
        },
        "notes": [
            "ECE is a separate track (C); NOT bundled here (one hypothesis per change-set).",
            "het gate is the unchanged binding bar, evaluated per split (never pooled).",
            "no n_buckets/n0/min_n/edge/quantile-method/c-rule re-tuning after results.",
            "A3 is a branch off v1.0 (NOT bundled with A1 winsorization).",
        ],
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase5_trackA_a3.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii"
    )
    (out_dir / "phase5_trackA_a3.md").write_text(_render_md(out), encoding="ascii")
    audit_dir = _write_audit(
        run_id, prereg_hash, snapshot, "py -m scripts.phase5_evaluate_trackA_a3"
    )

    print("\n[3/3] verdict (AFTER arm vs unchanged gates)")
    print(f"  prereg sha256: {prereg_hash[:16]}...  run_id={run_id}")
    for r in results:
        print(
            f"  {r['split']}: buckets={r['n_buckets_effective']} n={r['bucket_n']} "
            f"reuse={r['test_reuses_calib_partition']} non_empty={r['buckets_non_empty']} "
            f"| het_passed={r['after']['het_passed']} "
            f"| test_cov={r['after']['test_coverage']:.4f} "
            f"distinct_w={r['after']['width']['n_distinct_widths']}"
        )
    print(f"  het passed (all splits):            {het_ok}")
    print(f"  coverage within tol (all splits):   {coverage_ok}")
    print(f"  calib global in band (all splits):  {calib_in_band_all}")
    print(f"  widths non-degenerate (all splits): {widths_non_degenerate}")
    print(f"  buckets non-empty (all splits):     {buckets_non_empty_all}")
    print(f"  ACCEPT A3: {accept_a3}   KILL hit: {kill_hit}")
    print(f"  see {out_dir / 'phase5_trackA_a3.md'}  audit {audit_dir}")
    return 0 if het_ok else 1


def _render_md(out: dict) -> str:
    cfg = out["config"]
    lines = [
        "# Phase 5 - Track A.A3: Mondrian conditional conformal by sigma bucket (one-shot)",
        "",
        f"- Hypothesis: `{out['hypothesis']}` (conformal_method_version "
        f"`{cfg['conformal_method_version']}`; pre-reg sha256 `{out['prereg_sha256'][:16]}...`)",
        f"- Change: per-`sigma_hat`-bucket shrunk tail quantiles "
        f"(`n_buckets={cfg['n_buckets']}`, edges via `np.quantile{tuple(cfg['edge_quantiles'])}` "
        f"method=`{cfg['quantile_method']}`, frozen-on-calib; `min_n_bucket={cfg['min_n_bucket']}`; "
        f"shrinkage `n0={cfg['shrinkage_n0']}`); `c` global per split.",
        f"- Unchanged gates: coverage `{cfg['coverage_target']:.2f} +/- {cfg['coverage_tol']:.2f}`; "
        f"het per-width-quartile in `[{cfg['heterosced_band'][0]:.2f}, {cfg['heterosced_band'][1]:.2f}]` "
        f"({cfg['heterosced_n_bins']} bins); run_id `{out['run_id']}`.",
        "",
        f"- **ACCEPT A3: {out['acceptance']['accept_a3']}**  (het gate passes all splits: "
        f"{out['acceptance']['het_gate_passes_all_splits']}; KILL hit: {out['acceptance']['kill_hit']})",
        f"- **Heteroscedasticity passed (all splits): {out['gates_after']['heteroscedasticity_passed_all_splits']}**",
        f"- **Coverage within tol (all splits): {out['gates_after']['coverage_within_tol_all_splits']}**",
        f"- Calib global in band (all splits): {out['gates_after']['calib_global_in_band_all_splits']}",
        f"- Widths non-degenerate (all splits): {out['gates_after']['widths_non_degenerate_all_splits']}",
        f"- Buckets non-empty after merge (all splits): {out['gates_after']['buckets_non_empty_all_splits']}",
        f"- Test reuses calib partition (no leak, all splits): {out['gates_after']['test_reuses_calib_partition_all_splits']}",
        "",
        "## Frozen sigma-bucket partition per split (calib; reused on test)",
        "",
        "| split | eff buckets | calib counts | merged edges | calib cov (after) | in band |",
        "|-------|-------------|--------------|--------------|-------------------|---------|",
    ]
    for r in out["splits"]:
        edges = ", ".join(f"{e:.3f}" for e in r["edges"]) if r["edges"] else "(single bucket)"
        lines.append(
            f"| {r['split']} | {r['n_buckets_effective']} | {r['bucket_n']} | {edges} | "
            f"{r['calib_coverage_after']:.4f} | {r['calib_in_band_after']} |"
        )
    lines.extend([
        "",
        "## Per-bucket shrunk quantiles (after)",
        "",
        "| split | bucket | n | q_lo_eff | q_hi_eff |",
        "|-------|--------|---|----------|----------|",
    ])
    for r in out["splits"]:
        for b in range(r["n_buckets_effective"]):
            lines.append(
                f"| {r['split']} | {b} | {r['bucket_n'][b]} | "
                f"{r['bucket_q_lo'][b]:.3f} | {r['bucket_q_hi'][b]:.3f} |"
            )
    lines.extend([
        "",
        "## Per-width-quartile coverage: BEFORE (v1.0) vs AFTER (Mondrian)",
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
