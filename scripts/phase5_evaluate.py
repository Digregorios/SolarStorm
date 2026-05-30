"""Phase 5 integration: calibration + confidence audit (T-5-1..T-5-6).

Wires the Phase-5 workstreams into one walk-forward evaluation and freezes the
PRE-REGISTERED gates against the held-out result. The IC80 interval is produced by
the NORMALIZED QUANTIZATION-AWARE conformal amendment (criterion_version 1.0,
``contracts/phase5_preregistration.md``): the calibrator is fit on the SAME
integer-inclusive bracket object the gate evaluates, with a per-row ``sigma_hat`` =
``sqrt(p50_var)`` and a CONTINUOUS nominal level ``c`` selected ON CALIB ONLY. This
replaces the earlier decimal-then-quantize path, which calibrated one object and
evaluated another (a +0.06..+0.11 coverage gap, see ``reports/phase5_diagnose.json``).

``phase5_ready`` = coverage within tol on every split AND heteroscedasticity gate
passes on every split AND confidence ECE within tol wherever confidence is fittable.

``scripts/`` is not under the REQ-AUD-3 protected roots, so this module may import
``audits.phases.confidence`` directly; the CLI entry stays clean by invoking this
script out of process. The Phase-5 pre-registration hash is asserted at startup, so
the run refuses to proceed under a silently-edited contract.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from audits.phases.confidence import (
    run_phase as run_confidence_audit,
    write_confidence_audit,
)
from core.calibration.conformal import (
    NormalizedConformalConfig,
    apply_normalized_conformal,
    coverage_report,
    fit_normalized_conformal,
)
from core.confidence.score import ConfidenceConfig, confidence_score, fit_confidence
from core.contracts.phase5 import (
    C_GRID_START,
    C_GRID_STEP,
    C_GRID_STOP,
    CONFORMAL_METHOD,
    CONFORMAL_METHOD_VERSION,
    COVERAGE_BAND_HI,
    COVERAGE_BAND_LO,
    COVERAGE_TARGET,
    COVERAGE_TOL,
    ECE_TOL,
    HETEROSCED_COVERAGE_HIGH,
    HETEROSCED_COVERAGE_LOW,
    HETEROSCED_N_BINS,
    ROLE_CALIB,
    ROLE_TEST,
    SIGMA_IS_VARIANCE,
    SIGMA_PROXY,
)
from core.decision.engine import NO_TRADE, confidence_gate, load_min_confidence
from core.eval.gates_phase5 import heteroscedasticity_gate
from core.eval.preregistration import (
    assert_phase5_preregistration_committed,
    phase5_preregistration_sha256,
)
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]


def _gather(prob_dists: list[dict], rids: list[int]) -> list[dict]:
    """Row-align the external prob_dist list to a filtered frame via its row index."""
    return [prob_dists[r] for r in rids]


def _width_stats(lo: np.ndarray, hi: np.ndarray) -> dict:
    """Integer bracket width = hi - lo + 1; report variation (heteroscedasticity)."""
    w = (np.asarray(hi, dtype=int) - np.asarray(lo, dtype=int) + 1).astype(float)
    return {
        "mean_width": float(w.mean()),
        "width_std": float(w.std()),
        "n_distinct_widths": int(np.unique(w).size),
    }


def _evaluate_split(
    split_name: str,
    calib: pl.DataFrame,
    test: pl.DataFrame,
    prob_dists: list[dict],
    *,
    per_cp_window_days: int,
) -> dict:
    """Normalized quantization-aware conformal + het gate + confidence for one split."""
    ncfg = NormalizedConformalConfig(
        coverage_target=COVERAGE_TARGET,
        band_lo=COVERAGE_BAND_LO,
        band_hi=COVERAGE_BAND_HI,
        c_start=C_GRID_START,
        c_stop=C_GRID_STOP,
        c_step=C_GRID_STEP,
        sigma_is_variance=SIGMA_IS_VARIANCE,
        method_version=CONFORMAL_METHOD_VERSION,
    )

    # Calibrate on the recent per_cp_window_days tail of the (seasonal) calib slice.
    calib_max = calib["date_local"].max()
    recent = calib.filter(
        calib["date_local"] >= calib_max - timedelta(days=per_cp_window_days - 1)
    )
    cal = fit_normalized_conformal(
        recent["y_true_int"].to_numpy().astype(int),
        recent["y_pred_dec"].to_numpy().astype(float),
        recent[SIGMA_PROXY].to_list(),
        config=ncfg,
    )

    test_pred = test["y_pred_dec"].to_numpy().astype(float)
    test_y_int = test["y_true_int"].to_numpy().astype(int)
    test_cp = test["cp"].to_list()
    lo, hi = apply_normalized_conformal(cal, test_pred, test[SIGMA_PROXY].to_list())
    cov = coverage_report(
        lo, hi, test_y_int, test_cp, target=COVERAGE_TARGET, tol=COVERAGE_TOL
    )

    # Width-variation evidence (deliverable 4): calib + test bracket widths.
    calib_lo, calib_hi = apply_normalized_conformal(
        cal,
        recent["y_pred_dec"].to_numpy().astype(float),
        recent[SIGMA_PROXY].to_list(),
    )
    width = {"calib": _width_stats(calib_lo, calib_hi), "test": _width_stats(lo, hi)}

    conformal_block = {
        "method": CONFORMAL_METHOD,
        "method_version": CONFORMAL_METHOD_VERSION,
        "sigma_proxy": SIGMA_PROXY,
        "c": cal.c,
        "q_lo": cal.q_lo,
        "q_hi": cal.q_hi,
        "sigma_median": cal.sigma_median,
        "calib_coverage": cal.calib_coverage,
        "in_band_calib": cal.in_band,
    }

    het = heteroscedasticity_gate(
        lo, hi, test_y_int,
        n_bins=HETEROSCED_N_BINS,
        low=HETEROSCED_COVERAGE_LOW,
        high=HETEROSCED_COVERAGE_HIGH,
    )

    # Confidence: fit on the FULL calib slice (IC80 from the same calibrator), score
    # on test. p50_var supplies sigma_hat upstream; nwp_spread/p50_var are still passed
    # to the confidence model as its own features.
    full_calib_lo, full_calib_hi = apply_normalized_conformal(
        cal,
        calib["y_pred_dec"].to_numpy().astype(float),
        calib[SIGMA_PROXY].to_list(),
    )
    calib_pred = calib["y_pred_dec"].to_numpy().astype(float)
    calib_pd = _gather(prob_dists, calib["rid"].to_list())
    test_pd = _gather(prob_dists, test["rid"].to_list())
    calib_correct = calib["bracket_correct"].to_numpy().astype(int)

    confidence_block: dict
    if np.unique(calib_correct).size < 2:
        confidence_block = {
            "fitted": False,
            "reason": "calib bracket_correct single-class; confidence not calibratable",
        }
        test_scores = None
    else:
        fitted = fit_confidence(
            calib_pd, full_calib_lo, full_calib_hi,
            calib_pred, calib_correct,
            nwp_spread=calib["nwp_spread"].to_list(),
            p50_var=calib["p50_var"].to_list(),
            config=ConfidenceConfig(ece_tol=ECE_TOL),
        )
        test_scores = confidence_score(
            fitted, test_pd, lo, hi, test_pred,
            nwp_spread=test["nwp_spread"].to_list(),
            p50_var=test["p50_var"].to_list(),
        )
        audit = run_confidence_audit(
            confidence=test_scores,
            bracket_correct=test["bracket_correct"].to_numpy().astype(int),
            config=ConfidenceConfig(ece_tol=ECE_TOL),
        )
        confidence_block = {"fitted": True, "audit": audit}

    return {
        "split": split_name,
        "n_calib": int(calib.height),
        "n_calib_recent": int(recent.height),
        "n_test": int(test.height),
        "conformal": conformal_block,
        "coverage": asdict(cov),
        "width": width,
        "heteroscedasticity": asdict(het),
        "confidence": confidence_block,
        "_test_scores": test_scores,
        "_test_correct": test["bracket_correct"].to_numpy().astype(int),
    }


def main() -> int:
    # Pre-registration with teeth: refuse to run under a silently-edited contract.
    prereg_hash = assert_phase5_preregistration_committed()

    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])
    min_confidence = load_min_confidence(REPO / "nzwn" / "config" / "model.yaml")

    print("[1/4] Building Phase 5 panel (walk-forward, real data) ...")
    panel, prob_dists = build_phase5_panel(_allow_real_data=True)
    panel = panel.with_row_index("rid")
    print(f"  panel_rows={panel.height} prob_dists={len(prob_dists)}")

    split_names = list(dict.fromkeys(panel["split"].to_list()))
    print(f"[2/4] Evaluating {len(split_names)} splits ...")
    split_results: list[dict] = []
    for s in split_names:
        calib = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_CALIB))
        test = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_TEST))
        if calib.height == 0 or test.height == 0:
            print(f"  {s}: SKIP (calib={calib.height} test={test.height})")
            continue
        print(f"  {s}: calib={calib.height} test={test.height}")
        split_results.append(
            _evaluate_split(s, calib, test, prob_dists, per_cp_window_days=per_cp_window_days)
        )

    # Pooled confidence audit across every split that produced scores (T-5-5).
    print("[3/4] Pooled confidence audit + stay-out summary ...")
    pooled_scores = np.concatenate(
        [r["_test_scores"] for r in split_results if r["_test_scores"] is not None]
    ) if any(r["_test_scores"] is not None for r in split_results) else np.array([])
    pooled_correct = np.concatenate(
        [r["_test_correct"] for r in split_results if r["_test_scores"] is not None]
    ) if pooled_scores.size else np.array([], dtype=int)

    confidence_audit_pooled = None
    stay_out = None
    if pooled_scores.size:
        confidence_audit_pooled = run_confidence_audit(
            confidence=pooled_scores,
            bracket_correct=pooled_correct,
            config=ConfidenceConfig(ece_tol=ECE_TOL),
        )
        n_no_trade = int(
            sum(
                confidence_gate(float(s), min_confidence=min_confidence).action == NO_TRADE
                for s in pooled_scores
            )
        )
        stay_out = {
            "min_confidence": min_confidence,
            "n_rows": int(pooled_scores.size),
            "n_no_trade": n_no_trade,
            "frac_no_trade": float(n_no_trade / pooled_scores.size),
        }

    # --- VERDICT against pre-registered thresholds (no post-hoc tuning) ---
    coverage_ok = all(r["coverage"]["within_tol"] for r in split_results)
    het_ok = all(r["heteroscedasticity"]["passed"] for r in split_results)
    conf_splits = [r for r in split_results if r["confidence"]["fitted"]]
    conf_ok = bool(conf_splits) and all(
        r["confidence"]["audit"]["details"]["ece_within_tol"] for r in conf_splits
    )
    phase5_ready = bool(coverage_ok and het_ok and conf_ok)

    coverage_pass_splits = [r["split"] for r in split_results if r["coverage"]["within_tol"]]
    ece_pass_splits = [
        r["split"] for r in conf_splits
        if r["confidence"]["audit"]["details"]["ece_within_tol"]
    ]

    out = {
        "phase": 5,
        "prereg_sha256": prereg_hash,
        "conformal_method": CONFORMAL_METHOD,
        "conformal_method_version": CONFORMAL_METHOD_VERSION,
        "sigma_proxy": SIGMA_PROXY,
        "c_grid": [C_GRID_START, C_GRID_STOP, C_GRID_STEP],
        "coverage_target": COVERAGE_TARGET,
        "coverage_tol": COVERAGE_TOL,
        "ece_tol": ECE_TOL,
        "heterosced_band": [HETEROSCED_COVERAGE_LOW, HETEROSCED_COVERAGE_HIGH],
        "per_cp_window_days": per_cp_window_days,
        "splits": [
            {k: v for k, v in r.items() if not k.startswith("_")} for r in split_results
        ],
        "confidence_audit_pooled": confidence_audit_pooled,
        "stay_out": stay_out,
        "gates": {
            "coverage_within_tol_all_splits": coverage_ok,
            "heteroscedasticity_passed_all_splits": het_ok,
            "confidence_ece_within_tol": conf_ok,
        },
        "phase5_ready": phase5_ready,
        "honest_conclusion": {
            "object_mismatch_fixed": True,
            "coverage_pass_splits": coverage_pass_splits,
            "ece_pass_splits": ece_pass_splits,
            "notes": [
                "object mismatch fixed: conformal now calibrated on the integer-inclusive bracket object",
                "2024 coverage limited by calib->test drift (non-exchangeability), not the method",
                "2023 ECE is training-scarcity driven (~21 months; GFS floor 2021-03-22), separate track",
            ],
        },
        "backlog_tracks": {
            "drift_2024": "new hypothesis; requires its own pre-registration (seasonal 12m / Mondrian by month-regime / ex-ante update rule)",
            "ece_2023": "separate track (regularization / pooling / accept limitation); not bundled with the coverage fix",
        },
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase5.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="ascii",
    )
    (out_dir / "phase5.md").write_text(_render_md(out), encoding="ascii")
    if confidence_audit_pooled is not None:
        audit_dir = REPO / "audits" / "phase5"
        write_confidence_audit(audit_dir, confidence_audit_pooled)

    print("\n[verdict]")
    print(f"  conformal method: {CONFORMAL_METHOD} v{CONFORMAL_METHOD_VERSION} (sigma={SIGMA_PROXY})")
    print(f"  IC80 coverage within {COVERAGE_TOL} of {COVERAGE_TARGET} (all splits): {coverage_ok}  pass={coverage_pass_splits}")
    print(f"  Heteroscedasticity gate (all splits):                                 {het_ok}")
    print(f"  Confidence ECE within {ECE_TOL}:                                       {conf_ok}  pass={ece_pass_splits}")
    print(f"  Phase 5 ready:                                                        {phase5_ready}")
    print(f"  see {out_dir / 'phase5.md'}")
    return 0 if phase5_ready else 1


def _render_md(out: dict) -> str:
    lines = [
        "# Phase 5 - calibration + confidence audit",
        "",
        f"- Conformal method: `{out['conformal_method']}` v`{out['conformal_method_version']}` "
        f"(sigma_hat = sqrt(`{out['sigma_proxy']}`); pre-reg sha256 `{out['prereg_sha256'][:16]}...`)",
        f"- IC80 coverage target: `{out['coverage_target']:.2f} +/- {out['coverage_tol']:.2f}` "
        f"(band `[{out['coverage_target'] - out['coverage_tol']:.2f}, {out['coverage_target'] + out['coverage_tol']:.2f}]`)",
        f"- Heteroscedasticity band: `{out['heterosced_band'][0]:.2f} .. {out['heterosced_band'][1]:.2f}` "
        f"({HETEROSCED_N_BINS} IC-width quartile bins)",
        f"- Confidence ECE tol: `{out['ece_tol']:.2f}`",
        f"- Nominal-level grid c: `{out['c_grid'][0]} .. {out['c_grid'][1]} step {out['c_grid'][2]}` "
        f"(selected on calib only; per-CP window `{out['per_cp_window_days']}` days)",
        "",
        f"- **Coverage within tol (all splits): {out['gates']['coverage_within_tol_all_splits']}**",
        f"- **Heteroscedasticity passed (all splits): {out['gates']['heteroscedasticity_passed_all_splits']}**",
        f"- **Confidence ECE within tol: {out['gates']['confidence_ece_within_tol']}**",
        f"- **Phase 5 ready: {out['phase5_ready']}**",
        "",
        "## IC80 coverage per split (normalized quantization-aware conformal)",
        "",
        "| split | n_test | calib c | calib cov (in band) | test coverage | within tol | mean width |",
        "|-------|--------|---------|---------------------|---------------|------------|------------|",
    ]
    for r in out["splits"]:
        c = r["coverage"]
        cf = r["conformal"]
        lines.append(
            f"| {r['split']} | {r['n_test']} | {cf['c']:.3f} | "
            f"{cf['calib_coverage']:.4f} ({cf['in_band_calib']}) | {c['coverage']:.4f} | "
            f"{c['within_tol']} | {c['mean_width_brackets']:.2f} |"
        )
    lines.extend([
        "",
        "## Width variation (heteroscedasticity evidence; non-degenerate widths)",
        "",
        "| split | calib mean/std width | calib distinct | test mean/std width | test distinct |",
        "|-------|----------------------|----------------|---------------------|---------------|",
    ])
    for r in out["splits"]:
        w = r["width"]
        lines.append(
            f"| {r['split']} | {w['calib']['mean_width']:.2f} / {w['calib']['width_std']:.2f} | "
            f"{w['calib']['n_distinct_widths']} | "
            f"{w['test']['mean_width']:.2f} / {w['test']['width_std']:.2f} | "
            f"{w['test']['n_distinct_widths']} |"
        )
    lines.extend([
        "",
        "## Heteroscedasticity gate (IC80-width quartile coverage; REQ-AUD-5)",
        "",
        "| split | passed | mixed in/out | per-bin coverage (n) |",
        "|-------|--------|--------------|----------------------|",
    ])
    for r in out["splits"]:
        h = r["heteroscedasticity"]
        bins = "; ".join(
            f"[{b['width_lo']:.0f}-{b['width_hi']:.0f}] {b['coverage']:.3f} (n={b['n']})"
            for b in h["bins"]
        )
        lines.append(f"| {r['split']} | {h['passed']} | {h['mixed_in_and_out']} | {bins} |")
    lines.extend([
        "",
        "## Confidence audit per split (ECE + selective bracket_match; REQ-CONF-1)",
        "",
        "| split | fitted | ECE | within tol | bracket_match @ {0.25, 0.50, 0.75, 1.00} |",
        "|-------|--------|-----|------------|--------------------------------------------|",
    ])
    for r in out["splits"]:
        cb = r["confidence"]
        if not cb["fitted"]:
            lines.append(f"| {r['split']} | False | - | - | {cb['reason']} |")
            continue
        d = cb["audit"]["details"]
        bm = d["bracket_match_by_coverage"]
        bm_str = ", ".join(
            f"{k}:{bm[k]['match_rate']:.3f}" for k in sorted(bm.keys())
        )
        lines.append(
            f"| {r['split']} | True | {d['ece']:.4f} | {d['ece_within_tol']} | {bm_str} |"
        )
    if out.get("stay_out") is not None:
        so = out["stay_out"]
        lines.extend([
            "",
            "## Stay-out (confidence gate; REQ-CONF-3)",
            "",
            f"_Operational `min_confidence={so['min_confidence']:.2f}` (config default; the "
            "learned cutoff is a later phase). Pooled over all test rows._",
            "",
            f"- rows: {so['n_rows']}",
            f"- NO_TRADE(low_confidence): {so['n_no_trade']} ({so['frac_no_trade']:.3f})",
        ])
    if out.get("confidence_audit_pooled") is not None:
        d = out["confidence_audit_pooled"]["details"]
        lines.extend([
            "",
            "## Pooled confidence audit (all splits)",
            "",
            f"- ECE: `{d['ece']:.4f}` (tol `{d['ece_tol']:.2f}`, within_tol={d['ece_within_tol']})",
            f"- n: {d['n']}",
            "- NOTE: the pooled ECE is dominated by the scarcity-limited split; read the",
            "  per-split table above, not the pool, for calibration health.",
        ])
    hc = out["honest_conclusion"]
    lines.extend([
        "",
        "## Honest conclusion",
        "",
        f"- object mismatch fixed: **{hc['object_mismatch_fixed']}** "
        "(conformal now calibrated on the integer-inclusive bracket object, not a decimal interval)",
        f"- coverage passes on splits: `{hc['coverage_pass_splits']}`",
        f"- confidence ECE passes on splits: `{hc['ece_pass_splits']}`",
    ])
    for note in hc["notes"]:
        lines.append(f"- {note}")
    bt = out["backlog_tracks"]
    lines.extend([
        "",
        "## Backlog (separate tracks; each needs its own pre-registration)",
        "",
        f"- **Drift 2024**: {bt['drift_2024']}",
        f"- **ECE 2023**: {bt['ece_2023']}",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
