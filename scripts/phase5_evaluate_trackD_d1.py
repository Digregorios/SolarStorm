"""Phase 5 - Track D.D1 one-shot evaluator (randomized rounding Q_rand at quantization).

Pre-registered in ``contracts/phase5_amendment_trackD_d1_randomized_Q.md``
(conformal_method_version 2.0, q_version 1.1; PHASE5D1_COMMITTED_SHA256). The single method
change vs v1.0 is the endpoint quantizer: ``Q -> Q_rand`` (unbiased randomized rounding keyed
by (global_seed, row_id, endpoint_side)). The conformal family, sigma proxy, c-rule, windows,
splits and every gate are unchanged. Discipline: assert the frozen hash at startup; build the
v1.0 BEFORE arm and the D1 AFTER arm on the SAME calib/test rows; evaluate the pre-registered
accept/kill criteria; run exactly ONCE; publish reports + audit. No re-tuning after results.
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
    apply_normalized_conformal_qrand,
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
from core.contracts.quantization import row_id
from core.eval.gates_phase5 import heteroscedasticity_gate
from core.eval.preregistration import assert_phase5d1_preregistration_committed
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]
CONFORMAL_METHOD_VERSION_D1 = "2.0"
GLOBAL_SEED = 20260530  # mirrors the hashed PREREG quantization.seed_global
STATION_ID = "NZWN"
MIN_DISTINCT_WIDTHS = 3


def _v1_config() -> NormalizedConformalConfig:
    return NormalizedConformalConfig(
        coverage_target=COVERAGE_TARGET, band_lo=COVERAGE_BAND_LO, band_hi=COVERAGE_BAND_HI,
        c_start=C_GRID_START, c_stop=C_GRID_STOP, c_step=C_GRID_STEP,
        sigma_is_variance=SIGMA_IS_VARIANCE, method_version="1.0", winsorize=False,
    )


def _recent_tail(calib: pl.DataFrame, per_cp_window_days: int) -> pl.DataFrame:
    calib_max = calib["date_local"].max()
    return calib.filter(calib["date_local"] >= calib_max - timedelta(days=per_cp_window_days - 1))


def _row_ids(df: pl.DataFrame) -> list[str]:
    return [
        row_id(STATION_ID, r["date_local"], r["cp_utc"])
        for r in df.select(["date_local", "cp_utc"]).iter_rows(named=True)
    ]


def _width_stats(lo: np.ndarray, hi: np.ndarray) -> dict:
    w = (np.asarray(hi, dtype=int) - np.asarray(lo, dtype=int) + 1).astype(float)
    return {
        "mean_width": float(w.mean()),
        "width_std": float(w.std()),
        "n_distinct_widths": int(np.unique(w).size),
    }


def _coverage_arm(lo, hi, y_int, cp) -> dict:
    cov = coverage_report(lo, hi, y_int, cp, target=COVERAGE_TARGET, tol=COVERAGE_TOL)
    rep = heteroscedasticity_gate(
        lo, hi, y_int, n_bins=HETEROSCED_N_BINS,
        low=HETEROSCED_COVERAGE_LOW, high=HETEROSCED_COVERAGE_HIGH,
    )
    bins = [
        {"width_lo": b.width_lo, "width_hi": b.width_hi, "coverage": b.coverage,
         "mean_width": b.mean_width, "n": b.n}
        for b in rep.bins
    ]
    by_cp = {str(k): {"coverage": v[0], "mean_width": v[1], "n": v[2]} for k, v in cov.by_cp.items()}
    return {
        "test_coverage": cov.coverage,
        "test_coverage_within_tol": cov.within_tol,
        "width": _width_stats(lo, hi),
        "het_bins": bins,
        "het_passed": rep.passed,
        "by_cp": by_cp,
    }


def _evaluate_split_oneshot(split_name: str, recent: pl.DataFrame, test: pl.DataFrame) -> dict:
    rc_y = recent["y_true_int"].to_numpy().astype(int)
    rc_pred = recent["y_pred_dec"].to_numpy().astype(float)
    rc_sigma = recent[SIGMA_PROXY].to_list()

    test_pred = test["y_pred_dec"].to_numpy().astype(float)
    test_y = test["y_true_int"].to_numpy().astype(int)
    test_cp = test["cp"].to_list()
    test_sigma = test[SIGMA_PROXY].to_list()
    test_rids = _row_ids(test)

    cal = fit_normalized_conformal(rc_y, rc_pred, rc_sigma, config=_v1_config())

    # BEFORE: deterministic Q (v1.0). AFTER: Q_rand at the endpoints (D1). Same calibrator.
    lo_b, hi_b = apply_normalized_conformal(cal, test_pred, test_sigma)
    before = _coverage_arm(lo_b, hi_b, test_y, test_cp)
    lo_a, hi_a = apply_normalized_conformal_qrand(
        cal, test_pred, test_sigma, test_rids, global_seed=GLOBAL_SEED, split_name=split_name
    )
    after = _coverage_arm(lo_a, hi_a, test_y, test_cp)

    # A/B seed (read-only evidence): different seed must keep invariants + stable coverage.
    lo_ab, hi_ab = apply_normalized_conformal_qrand(
        cal, test_pred, test_sigma, test_rids, global_seed=GLOBAL_SEED + 1, split_name=split_name
    )
    ab_cov = float(((lo_ab <= test_y) & (test_y <= hi_ab)).mean())
    ab = {
        "alt_seed": GLOBAL_SEED + 1,
        "coverage": ab_cov,
        "coverage_delta_vs_primary": abs(ab_cov - after["test_coverage"]),
        "hi_ge_lo": bool(np.all(hi_ab >= lo_ab)),
        "assignment_changed": not (np.array_equal(lo_ab, lo_a) and np.array_equal(hi_ab, hi_a)),
    }

    return {
        "split": split_name,
        "n_calib_recent": int(recent.height),
        "n_test": int(test.height),
        "c": cal.c,
        "q_lo": cal.q_lo,
        "q_hi": cal.q_hi,
        "calib_coverage": cal.calib_coverage,
        "calib_in_band": cal.in_band,
        "before": before,
        "after": after,
        "ab_seed": ab,
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
    prereg_hash = assert_phase5d1_preregistration_committed()

    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])

    print("[1/3] Building Phase 5 panel (walk-forward, real data) ...")
    panel, _prob_dists = build_phase5_panel(_allow_real_data=True)
    print(f"  panel_rows={panel.height}  seed={GLOBAL_SEED}  Q -> Q_rand at endpoints only")

    split_names = list(dict.fromkeys(panel["split"].to_list()))
    print(f"[2/3] One-shot evaluation on {len(split_names)} splits ...")
    results: list[dict] = []
    for s in split_names:
        calib = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_CALIB))
        test = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_TEST))
        if calib.height == 0 or test.height == 0:
            continue
        recent = _recent_tail(calib, per_cp_window_days)
        results.append(_evaluate_split_oneshot(s, recent, test))

    het_ok = bool(results) and all(r["after"]["het_passed"] for r in results)
    calib_in_band_all = bool(results) and all(
        COVERAGE_BAND_LO <= r["calib_coverage"] <= COVERAGE_BAND_HI for r in results
    )
    widths_non_degenerate = bool(results) and all(
        r["after"]["width"]["n_distinct_widths"] >= MIN_DISTINCT_WIDTHS for r in results
    )
    coverage_ok = bool(results) and all(r["after"]["test_coverage_within_tol"] for r in results)

    accept_d1 = bool(het_ok and calib_in_band_all and widths_non_degenerate)
    kill_hit = bool(results and ((not widths_non_degenerate) or (not calib_in_band_all)))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = {
        "method": CONFORMAL_METHOD,
        "conformal_method_version": CONFORMAL_METHOD_VERSION_D1,
        "q_version": "1.1",
        "change": "endpoint quantizer Q -> Q_rand (unbiased randomized rounding)",
        "global_seed": GLOBAL_SEED,
        "row_id": "sha256(NZWN|date_local|cp_utc)",
        "c_grid": [C_GRID_START, C_GRID_STOP, C_GRID_STEP],
        "coverage_target": COVERAGE_TARGET,
        "coverage_tol": COVERAGE_TOL,
        "heterosced_band": [HETEROSCED_COVERAGE_LOW, HETEROSCED_COVERAGE_HIGH],
        "heterosced_n_bins": HETEROSCED_N_BINS,
        "per_cp_window_days": per_cp_window_days,
    }
    out = {
        "phase": 5,
        "track": "D1",
        "hypothesis": "trackD_d1_randomized_q",
        "prereg_sha256": prereg_hash,
        "run_id": run_id,
        "config": snapshot,
        "splits": results,
        "gates_after": {
            "coverage_within_tol_all_splits": coverage_ok,
            "heteroscedasticity_passed_all_splits": het_ok,
            "calib_global_in_band_all_splits": calib_in_band_all,
            "widths_non_degenerate_all_splits": widths_non_degenerate,
        },
        "acceptance": {
            "het_gate_passes_per_split_on_test": het_ok,
            "global_calib_coverage_in_band": calib_in_band_all,
            "widths_non_degenerate_min_distinct_3": widths_non_degenerate,
            "accept_d1": accept_d1,
            "kill_hit": kill_hit,
        },
        "notes": [
            "Exactly one variable changed: endpoint quantizer Q -> Q_rand (q_version 1.1).",
            "Q_rand is unbiased randomized rounding (ceil w.p. frac(x)); seed-fixed, row-local.",
            "Q_rand formula corrected pre-execution from a biased factor-2 transcription "
            "(P(ceil)=2t) to P(ceil)=t; hash re-pinned in the same change-set (see contract).",
            "het gate is the unchanged binding bar, per split, never pooled.",
            "A/B seed is read-only evidence (coverage stability + invariants), NOT a gate.",
            "No seed / Q_rand / floor / c-rule re-tuning after results; a fail opens D2 or a "
            "tie-only D1 variant as a NEW pre-registration.",
        ],
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase5_trackD_d1.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii"
    )
    (out_dir / "phase5_trackD_d1.md").write_text(_render_md(out), encoding="ascii")
    audit_dir = _write_audit(run_id, prereg_hash, snapshot, "py -m scripts.phase5_evaluate_trackD_d1")

    print("\n[3/3] verdict")
    print(f"  prereg sha256: {prereg_hash[:16]}...  run_id={run_id}")
    for r in results:
        print(
            f"  {r['split']}: het before={r['before']['het_passed']} after={r['after']['het_passed']} "
            f"| test_cov {r['before']['test_coverage']:.4f} -> {r['after']['test_coverage']:.4f} "
            f"| distinct_w={r['after']['width']['n_distinct_widths']} "
            f"| calib_cov={r['calib_coverage']:.4f} | ab_dcov={r['ab_seed']['coverage_delta_vs_primary']:.4f}"
        )
    print(f"  het passed (all splits):            {het_ok}")
    print(f"  calib global in band (all splits):  {calib_in_band_all}")
    print(f"  widths non-degenerate (all splits): {widths_non_degenerate}")
    print(f"  ACCEPT D1: {accept_d1}   KILL hit: {kill_hit}")
    print(f"  see {out_dir / 'phase5_trackD_d1.md'}  audit {audit_dir}")
    return 0 if accept_d1 else 1


def _render_md(out: dict) -> str:
    cfg = out["config"]
    lines = [
        "# Phase 5 - Track D.D1: randomized rounding Q_rand at quantization (one-shot)",
        "",
        f"- Hypothesis: `{out['hypothesis']}` (conformal_method_version "
        f"`{cfg['conformal_method_version']}`, q_version `{cfg['q_version']}`; "
        f"pre-reg sha256 `{out['prereg_sha256'][:16]}...`)",
        f"- Change (exactly one variable): `{cfg['change']}`; seed `{cfg['global_seed']}`, "
        f"row_id `{cfg['row_id']}`. Everything else is v1.0.",
        f"- Unchanged gates: coverage `{cfg['coverage_target']:.2f} +/- {cfg['coverage_tol']:.2f}`; "
        f"het per-width-quartile in `[{cfg['heterosced_band'][0]:.2f}, {cfg['heterosced_band'][1]:.2f}]` "
        f"({cfg['heterosced_n_bins']} bins); run_id `{out['run_id']}`.",
        "",
        f"- **ACCEPT D1: {out['acceptance']['accept_d1']}**  "
        f"(het all splits: {out['acceptance']['het_gate_passes_per_split_on_test']}; "
        f"calib in band: {out['acceptance']['global_calib_coverage_in_band']}; "
        f"widths non-degenerate: {out['acceptance']['widths_non_degenerate_min_distinct_3']}; "
        f"KILL hit: {out['acceptance']['kill_hit']})",
        "",
        "## Per-width-quartile coverage: BEFORE (v1.0 Q) vs AFTER (D1 Q_rand)",
        "",
        "| split | arm | per-bin coverage [w_lo-w_hi] cov (n) | het passed |",
        "|-------|-----|--------------------------------------|------------|",
    ]
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
        "## Global coverage + width non-degeneracy (after) + A/B seed (read-only)",
        "",
        "| split | test cov (before->after) | within tol | calib cov | distinct widths | A/B dcov | A/B hi>=lo | assign changed |",
        "|-------|--------------------------|------------|-----------|-----------------|----------|------------|----------------|",
    ])
    for r in out["splits"]:
        a, b, ab = r["after"], r["before"], r["ab_seed"]
        lines.append(
            f"| {r['split']} | {b['test_coverage']:.4f} -> {a['test_coverage']:.4f} | "
            f"{a['test_coverage_within_tol']} | {r['calib_coverage']:.4f} | "
            f"{a['width']['n_distinct_widths']} | {ab['coverage_delta_vs_primary']:.4f} | "
            f"{ab['hi_ge_lo']} | {ab['assignment_changed']} |"
        )
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
    lines.extend(["", "## Notes", ""])
    for n in out["notes"]:
        lines.append(f"- {n}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
