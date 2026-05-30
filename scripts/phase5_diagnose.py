"""Phase 5 diagnose-first: confirm the quantization diagnosis BEFORE any method fix.

This script does NOT change any model, gate, or contract. It answers the two
questions the Phase-4/5 reviewer asked to be settled on the EXISTING panel before
implementing the principled fix (``references/code-reviews/update.txt``):

  1. CONFIRMATORY (is conformal sound, only quantization broken?):
     does the DECIMAL interval (calibrated on calib, no ``Q``) hit ~0.80 coverage?
     If yes -> the split-conformal math is sound and integer quantization alone
     inflates coverage to ~0.93.

  2. FEASIBILITY (calib-only, test-blind): is the 0.80 +/- 0.04 gate even
     ATTAINABLE by an integer-bracket object? Scan integer half-widths
     ``(w_lo, w_hi)`` on the CALIB integer residual ``e = y_true_int - Q(y_pred_dec)``
     and report whether any combination lands calib coverage in [0.76, 0.84],
     plus the symmetric-``w`` coverage ladder so the granularity STEP SIZE is
     visible (the "straddle" risk: w -> w+1 may jump over the band).

Selection of ``(w_lo, w_hi)`` is done on CALIB ONLY. Test coverage for the
calib-optimal combo is reported for READOUT, not used to pick anything.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import yaml

from core.calibration.conformal import (
    ConformalConfig,
    apply_conformal,
    fit_conformal,
    interval_dec,
)
from core.contracts.phase5 import COVERAGE_TARGET, COVERAGE_TOL, ROLE_CALIB, ROLE_TEST
from core.contracts.quantization import Q
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]
BAND_LO = COVERAGE_TARGET - COVERAGE_TOL  # 0.76
BAND_HI = COVERAGE_TARGET + COVERAGE_TOL  # 0.84
W_MAX = 8


def _decimal_coverage(lo_dec, hi_dec, y_true_int) -> float:
    yt = np.asarray(y_true_int, dtype=float)
    return float(((lo_dec <= yt) & (yt <= hi_dec)).mean())


def _int_coverage(e: np.ndarray, w_lo: int, w_hi: int) -> float:
    """Coverage of inclusive integer interval [Q(pred)-w_lo, Q(pred)+w_hi]."""
    return float(((e >= -w_lo) & (e <= w_hi)).mean())


def _symmetric_ladder(e: np.ndarray) -> list[dict]:
    """Coverage at each symmetric integer half-width w (exposes step granularity)."""
    return [
        {"w": w, "width_brackets": 2 * w + 1, "coverage": _int_coverage(e, w, w)}
        for w in range(0, W_MAX + 1)
    ]


def _sigma_from(frame, proxy: str, n: int) -> np.ndarray:
    """Per-row sigma_hat(x) from a panel proxy; null -> median, floored > 0."""
    if proxy == "const":
        return np.ones(n, dtype=float)
    raw = frame[proxy].to_list()
    vals = np.array([np.nan if v is None else float(v) for v in raw], dtype=float)
    if proxy == "p50_var":  # variance -> std
        vals = np.sqrt(np.clip(vals, 0.0, None))
    finite = vals[np.isfinite(vals)]
    med = float(np.median(finite)) if finite.size else 1.0
    vals = np.where(np.isfinite(vals), vals, med)
    return np.maximum(vals, max(med * 1e-3, 1e-6))


def _normalized_feasibility(
    pred_cal, ytrue_cal, sigma_cal, pred_eval, ytrue_eval, sigma_eval
) -> dict:
    """Sweep the continuous nominal level; can integer coverage land in band?

    Signed normalized score u = (y_true_int - pred)/sigma. At nominal level c the
    tails are (1-c)/2 each (asymmetric offsets, refinement #3). Per-row width =
    Q(pred + q_hi*sigma) - Q(pred + q_lo*sigma): varies with sigma -> finer effective
    resolution than a single global integer w, and preserves heteroscedasticity.
    Selection of c is IN-SAMPLE on calib (test-blind); test coverage is readout only.
    """
    u = (ytrue_cal - pred_cal) / sigma_cal
    best = None
    insample_at_080 = None
    for c in np.round(np.arange(0.50, 0.961, 0.005), 3):
        p_lo, p_hi = (1.0 - c) / 2.0, 1.0 - (1.0 - c) / 2.0
        q_lo = float(np.quantile(u, p_lo))
        q_hi = float(np.quantile(u, p_hi))
        lo_int = np.array([Q(float(p + q_lo * s)) for p, s in zip(pred_cal, sigma_cal)])
        hi_int = np.array([Q(float(p + q_hi * s)) for p, s in zip(pred_cal, sigma_cal)])
        hi_int = np.maximum(hi_int, lo_int)
        cov = float(((lo_int <= ytrue_cal) & (ytrue_cal <= hi_int)).mean())
        width = float((hi_int - lo_int + 1).mean())
        width_std = float((hi_int - lo_int + 1).std())
        rec = {"c": float(c), "calib_cov": cov, "mean_width": width, "width_std": width_std,
               "q_lo": q_lo, "q_hi": q_hi}
        if insample_at_080 is None or abs(cov - COVERAGE_TARGET) < abs(insample_at_080["calib_cov"] - COVERAGE_TARGET):
            insample_at_080 = rec
        if BAND_LO <= cov <= BAND_HI:
            if best is None or abs(cov - COVERAGE_TARGET) < abs(best["calib_cov"] - COVERAGE_TARGET):
                best = rec
    chosen = best or insample_at_080
    # READOUT: apply chosen c's offsets to the eval (test) set.
    lo_int = np.array([Q(float(p + chosen["q_lo"] * s)) for p, s in zip(pred_eval, sigma_eval)])
    hi_int = np.array([Q(float(p + chosen["q_hi"] * s)) for p, s in zip(pred_eval, sigma_eval)])
    hi_int = np.maximum(hi_int, lo_int)
    test_cov = float(((lo_int <= ytrue_eval) & (ytrue_eval <= hi_int)).mean())
    test_widths = hi_int - lo_int + 1
    return {
        "band_attainable_calib": best is not None,
        "chosen_c": chosen["c"],
        "calib_cov_at_chosen": chosen["calib_cov"],
        "calib_mean_width": chosen["mean_width"],
        "calib_width_std": chosen["width_std"],
        "test_cov_at_chosen": test_cov,
        "test_mean_width": float(test_widths.mean()),
        "test_n_distinct_widths": int(np.unique(test_widths).size),
    }


def _feasible_combos(e: np.ndarray) -> list[dict]:
    """All integer (w_lo, w_hi) with calib coverage in [BAND_LO, BAND_HI]."""
    out: list[dict] = []
    for w_lo in range(0, W_MAX + 1):
        for w_hi in range(0, W_MAX + 1):
            cov = _int_coverage(e, w_lo, w_hi)
            if BAND_LO <= cov <= BAND_HI:
                out.append(
                    {
                        "w_lo": w_lo,
                        "w_hi": w_hi,
                        "width_brackets": w_lo + w_hi + 1,
                        "coverage": cov,
                    }
                )
    # Min width first, then closest to target.
    out.sort(key=lambda d: (d["width_brackets"], abs(d["coverage"] - COVERAGE_TARGET)))
    return out


def _diagnose_split(split_name, calib, test, *, per_cp_window_days) -> dict:
    calib_pred = calib["y_pred_dec"].to_numpy().astype(float)
    calib_y = calib["y_true_int"].to_numpy().astype(float)
    calib_cp = calib["cp"].to_list()
    test_pred = test["y_pred_dec"].to_numpy().astype(float)
    test_y_int = test["y_true_int"].to_numpy().astype(int)
    test_cp = test["cp"].to_list()

    # Mirror the integrator: per-CP signed calibrator on the recent window.
    cfg = ConformalConfig(coverage=COVERAGE_TARGET, method="signed")
    calib_max = calib["date_local"].max()
    recent = calib.filter(
        calib["date_local"] >= calib_max - timedelta(days=per_cp_window_days - 1)
    )
    cal = fit_conformal(
        recent["y_true_int"].to_numpy().astype(float),
        recent["y_pred_dec"].to_numpy().astype(float),
        recent["cp"].to_list(),
        config=cfg,
    )

    # (1) CONFIRMATORY: decimal vs integer coverage on test (same calibrator).
    lo_dec, hi_dec = interval_dec(cal, test_pred, test_cp)
    dec_cov_test = _decimal_coverage(lo_dec, hi_dec, test_y_int)
    lo_int, hi_int = apply_conformal(cal, test_pred, test_cp)
    int_cov_test = float(((lo_int <= test_y_int) & (test_y_int <= hi_int)).mean())
    # In-sample calib decimal coverage (sanity: should sit right at ~0.80).
    lo_dec_c, hi_dec_c = interval_dec(cal, recent["y_pred_dec"].to_numpy().astype(float),
                                      recent["cp"].to_list())
    dec_cov_calib = _decimal_coverage(
        lo_dec_c, hi_dec_c, recent["y_true_int"].to_numpy().astype(int)
    )

    # (2) FEASIBILITY on CALIB integer residual e = y_true_int - Q(y_pred_dec).
    e_calib = np.array(
        [int(round(y)) - Q(float(p)) for y, p in zip(calib_y, calib_pred)], dtype=int
    )
    e_calib_recent = np.array(
        [
            int(round(y)) - Q(float(p))
            for y, p in zip(
                recent["y_true_int"].to_numpy().astype(float),
                recent["y_pred_dec"].to_numpy().astype(float),
            )
        ],
        dtype=int,
    )
    ladder = _symmetric_ladder(e_calib_recent)
    combos = _feasible_combos(e_calib_recent)
    chosen = combos[0] if combos else None

    chosen_test_cov = None
    if chosen is not None:
        # READOUT ONLY: test coverage at the calib-chosen integer half-widths.
        qpred_test = np.array([Q(float(p)) for p in test_pred], dtype=int)
        e_test = test_y_int - qpred_test
        chosen_test_cov = _int_coverage(e_test, chosen["w_lo"], chosen["w_hi"])

    # Normalized-conformal feasibility (continuous nominal level + per-row sigma).
    recent_pred = recent["y_pred_dec"].to_numpy().astype(float)
    recent_y = recent["y_true_int"].to_numpy().astype(float)
    normalized = {}
    for proxy in ("const", "nwp_spread", "p50_var"):
        sig_cal = _sigma_from(recent, proxy, recent.height)
        sig_test = _sigma_from(test, proxy, test.height)
        normalized[proxy] = _normalized_feasibility(
            recent_pred, recent_y, sig_cal, test_pred, test_y_int.astype(float), sig_test
        )

    return {
        "split": split_name,
        "n_calib": int(calib.height),
        "n_calib_recent": int(recent.height),
        "n_test": int(test.height),
        "confirmatory": {
            "decimal_coverage_calib_insample": dec_cov_calib,
            "decimal_coverage_test": dec_cov_test,
            "integer_coverage_test": int_cov_test,
            "quantization_gap": int_cov_test - dec_cov_test,
        },
        "feasibility_calib": {
            "band": [BAND_LO, BAND_HI],
            "symmetric_ladder": ladder,
            "n_feasible_combos": len(combos),
            "min_width_feasible": chosen,
            "all_feasible_combos": combos,
            "band_attainable": chosen is not None,
        },
        "readout_test_cov_at_calib_choice": chosen_test_cov,
        "normalized_feasibility": normalized,
    }


def main() -> int:
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])

    print("[1/2] Building Phase 5 panel (walk-forward, real data) ...")
    panel, _ = build_phase5_panel(_allow_real_data=True)
    print(f"  panel_rows={panel.height}")

    split_names = list(dict.fromkeys(panel["split"].to_list()))
    print(f"[2/2] Diagnosing {len(split_names)} splits ...")
    results: list[dict] = []
    for s in split_names:
        calib = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_CALIB))
        test = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_TEST))
        if calib.height == 0 or test.height == 0:
            continue
        results.append(
            _diagnose_split(s, calib, test, per_cp_window_days=per_cp_window_days)
        )

    out = {
        "purpose": "diagnose-first: confirm quantization diagnosis + calib-only band feasibility",
        "coverage_target": COVERAGE_TARGET,
        "coverage_tol": COVERAGE_TOL,
        "band": [BAND_LO, BAND_HI],
        "splits": results,
        "all_splits_decimal_near_target": all(
            abs(r["confirmatory"]["decimal_coverage_test"] - COVERAGE_TARGET) < 0.05
            for r in results
        ),
        "all_splits_band_attainable_calib": all(
            r["feasibility_calib"]["band_attainable"] for r in results
        ),
        "all_splits_band_attainable_normalized": {
            proxy: all(
                r["normalized_feasibility"][proxy]["band_attainable_calib"] for r in results
            )
            for proxy in ("const", "nwp_spread", "p50_var")
        },
    }
    out_path = REPO / "reports" / "phase5_diagnose.json"
    out_path.write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="ascii",
    )

    print("\n[confirmatory: decimal vs integer coverage on test]")
    for r in results:
        c = r["confirmatory"]
        print(
            f"  {r['split']}: decimal={c['decimal_coverage_test']:.4f}  "
            f"integer={c['integer_coverage_test']:.4f}  "
            f"gap=+{c['quantization_gap']:.4f}  "
            f"(calib in-sample decimal={c['decimal_coverage_calib_insample']:.4f})"
        )
    print(f"  -> decimal ~= 0.80 on all splits: {out['all_splits_decimal_near_target']}")

    print("\n[feasibility: integer (w_lo,w_hi) landing calib coverage in band]")
    for r in results:
        f = r["feasibility_calib"]
        mw = f["min_width_feasible"]
        ladder_str = " ".join(
            f"w{d['w']}:{d['coverage']:.3f}" for d in f["symmetric_ladder"] if d["w"] <= 5
        )
        if mw is None:
            print(f"  {r['split']}: NO integer combo in band; ladder [{ladder_str}]")
        else:
            print(
                f"  {r['split']}: {f['n_feasible_combos']} combo(s); "
                f"min-width (w_lo={mw['w_lo']},w_hi={mw['w_hi']}) "
                f"calib_cov={mw['coverage']:.4f} -> test_cov={r['readout_test_cov_at_calib_choice']:.4f}; "
                f"ladder [{ladder_str}]"
            )
    print(f"  -> band attainable (calib) on all splits: {out['all_splits_band_attainable_calib']}")

    print("\n[normalized conformal: continuous level + per-row sigma; calib-only selection]")
    for proxy in ("const", "nwp_spread", "p50_var"):
        print(f"  proxy={proxy}:")
        for r in results:
            nf = r["normalized_feasibility"][proxy]
            print(
                f"    {r['split']}: band_attainable={nf['band_attainable_calib']} "
                f"c={nf['chosen_c']:.3f} calib_cov={nf['calib_cov_at_chosen']:.4f} "
                f"-> test_cov={nf['test_cov_at_chosen']:.4f} "
                f"(test mean_width={nf['test_mean_width']:.2f}, "
                f"distinct_widths={nf['test_n_distinct_widths']})"
            )
        print(f"    -> all splits attainable: {out['all_splits_band_attainable_normalized'][proxy]}")
    print(f"\n  see {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
