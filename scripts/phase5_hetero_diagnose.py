"""Track A diagnose-first: explain the wide-bin over-coverage BEFORE any method fix.

Read-only. This script changes NO model, gate, threshold, window, sigma proxy, or
contract. It produces the mandatory Track-A diagnostics the reviewer requires before
a heteroscedasticity method change (``references/code-reviews/update.txt`` section 6):

  1. sigma_hat histogram on calib AND test (percentile spread + tail heaviness),
  2. distribution / frequency of each emitted integer width,
  3. correlation of interval width vs |error| magnitude,

plus the per-width-quartile mechanism (gate-mirrored bins): coverage, mean width,
mean |error_int|, and SLACK = mean_width - (2*mean|error_int| + 1). Positive slack in
the wide quartiles is the signature that sigma_hat OVER-states difficulty there (the
interval is wider than the realized error needs), which is exactly the ~1.00 wide-bin
over-coverage the gate flags.

It reuses the EXACT evaluator calibrator: ``fit_normalized_conformal`` fit on the
recent ``per_cp_window_days`` tail of the calib slice with ``sigma_hat = sqrt(p50_var)``,
then ``apply_normalized_conformal`` on calib and test. Selection of the nominal level
``c`` is calib-only (inside the fit); test is readout only. No statistic flows test->calib
(the sigma median/floor are frozen on calib at fit time).
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from core.calibration.conformal import (
    NormalizedConformalConfig,
    apply_normalized_conformal,
    fit_normalized_conformal,
)
from core.contracts.phase5 import (
    C_GRID_START,
    C_GRID_STEP,
    C_GRID_STOP,
    COVERAGE_BAND_HI,
    COVERAGE_BAND_LO,
    COVERAGE_TARGET,
    HETEROSCED_COVERAGE_HIGH,
    HETEROSCED_COVERAGE_LOW,
    HETEROSCED_N_BINS,
    ROLE_CALIB,
    ROLE_TEST,
    SIGMA_IS_VARIANCE,
    SIGMA_PROXY,
)
from core.contracts.quantization import Q
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]

_PCTL = (1, 5, 10, 25, 50, 75, 90, 95, 99)


def _sigma_hat(frame: pl.DataFrame, median: float, floor: float) -> np.ndarray:
    """Reproduce the calibrator's per-row sigma_hat (sqrt of p50_var; impute; floor).

    Uses the CALIB-frozen ``median`` / ``floor`` so calib and test are scaled by the
    same statistics (no test leakage), exactly as ``apply_normalized_conformal`` does.
    """
    raw = frame[SIGMA_PROXY].to_list()
    s = np.array([np.nan if v is None else float(v) for v in raw], dtype=float)
    if SIGMA_IS_VARIANCE:
        s = np.sqrt(np.clip(s, 0.0, None))
    s = np.where(np.isfinite(s), s, median)
    return np.maximum(s, floor)


def _pct(arr: np.ndarray) -> dict:
    """Percentile snapshot + tail-heaviness ratio p99/p50 of a 1-D array."""
    a = np.asarray(arr, dtype=float)
    p = {f"p{q:02d}": float(np.percentile(a, q)) for q in _PCTL}
    p["mean"] = float(a.mean())
    p["max"] = float(a.max())
    p["n_missing_raw"] = 0  # imputed upstream; kept explicit per silent-bug checklist
    p["tail_ratio_p99_p50"] = float(p["p99"] / p["p50"]) if p["p50"] > 0 else None
    return p


def _width_freq(widths: np.ndarray) -> list[dict]:
    """Frequency table of each integer width (value, count, fraction), width-sorted."""
    w = np.asarray(widths, dtype=int)
    vals, counts = np.unique(w, return_counts=True)
    n = int(w.size)
    return [
        {"width": int(v), "count": int(c), "frac": float(c / n)}
        for v, c in zip(vals, counts)
    ]


def _gate_bin_idx(widths: np.ndarray, n_bins: int) -> np.ndarray:
    """Bin assignment IDENTICAL to ``gates_phase5.heteroscedasticity_gate``.

    Quantile edges over the UNIQUE widths, then searchsorted(side='right'). Mirrored
    here so the diagnostic quartiles map 1:1 onto the gate quartiles.
    """
    unique_widths = np.unique(widths)
    probs = np.linspace(0.0, 1.0, n_bins + 1)[1:-1]
    if probs.size:
        edges = np.quantile(unique_widths, probs, method="linear")
        return np.searchsorted(edges, widths, side="right")
    return np.zeros(widths.shape, dtype=int)


def _quartile_mechanism(
    lo: np.ndarray, hi: np.ndarray, y_int: np.ndarray, pred: np.ndarray
) -> list[dict]:
    """Per width-quartile: coverage, mean width, mean |error_int|, and slack.

    ``error_int = y_true_int - Q(y_pred_dec)`` (the integer miss). SLACK =
    mean_width - (2*mean|error_int| + 1): the brackets of width the interval carries
    beyond what the realized error needs. Large positive slack in wide bins == sigma
    over-stating difficulty there (the wide-bin over-coverage mechanism).
    """
    widths = (hi - lo + 1).astype(float)
    covered = (lo <= y_int) & (y_int <= hi)
    qpred = np.array([Q(float(p)) for p in pred], dtype=int)
    err = np.abs(y_int - qpred).astype(float)
    bin_idx = _gate_bin_idx(widths, HETEROSCED_N_BINS)

    out: list[dict] = []
    for b in range(HETEROSCED_N_BINS):
        mask = bin_idx == b
        n_b = int(mask.sum())
        if n_b == 0:
            continue
        w = widths[mask]
        e = err[mask]
        mean_w = float(w.mean())
        mean_e = float(e.mean())
        out.append(
            {
                "bin": b,
                "width_lo": float(w.min()),
                "width_hi": float(w.max()),
                "mean_width": mean_w,
                "coverage": float(covered[mask].mean()),
                "mean_abs_error_int": mean_e,
                "needed_width": 2.0 * mean_e + 1.0,
                "slack_brackets": mean_w - (2.0 * mean_e + 1.0),
                "in_band": bool(HETEROSCED_COVERAGE_LOW <= float(covered[mask].mean()) <= HETEROSCED_COVERAGE_HIGH),
                "n": n_b,
            }
        )
    return out


def _corr(widths: np.ndarray, err_abs: np.ndarray) -> dict:
    """Pearson + Spearman(rank) correlation of width vs |error|. Deterministic."""
    w = np.asarray(widths, dtype=float)
    e = np.asarray(err_abs, dtype=float)
    if w.std() == 0.0 or e.std() == 0.0:
        return {"pearson": None, "spearman": None, "note": "degenerate (zero variance)"}
    pearson = float(np.corrcoef(w, e)[0, 1])
    rw = np.argsort(np.argsort(w)).astype(float)
    re = np.argsort(np.argsort(e)).astype(float)
    spearman = float(np.corrcoef(rw, re)[0, 1])
    return {"pearson": pearson, "spearman": spearman}


def _diagnose_split(split_name: str, calib: pl.DataFrame, test: pl.DataFrame, *, per_cp_window_days: int) -> dict:
    ncfg = NormalizedConformalConfig(
        coverage_target=COVERAGE_TARGET,
        band_lo=COVERAGE_BAND_LO,
        band_hi=COVERAGE_BAND_HI,
        c_start=C_GRID_START,
        c_stop=C_GRID_STOP,
        c_step=C_GRID_STEP,
        sigma_is_variance=SIGMA_IS_VARIANCE,
    )
    calib_max = calib["date_local"].max()
    recent = calib.filter(calib["date_local"] >= calib_max - timedelta(days=per_cp_window_days - 1))
    cal = fit_normalized_conformal(
        recent["y_true_int"].to_numpy().astype(int),
        recent["y_pred_dec"].to_numpy().astype(float),
        recent[SIGMA_PROXY].to_list(),
        config=ncfg,
    )

    blocks: dict[str, dict] = {}
    for role, frame in (("calib", recent), ("test", test)):
        pred = frame["y_pred_dec"].to_numpy().astype(float)
        y_int = frame["y_true_int"].to_numpy().astype(int)
        lo, hi = apply_normalized_conformal(cal, pred, frame[SIGMA_PROXY].to_list())
        widths = (hi - lo + 1).astype(int)
        sig = _sigma_hat(frame, cal.sigma_median, cal.sigma_floor)
        qpred = np.array([Q(float(p)) for p in pred], dtype=int)
        err_abs = np.abs(y_int - qpred).astype(float)
        blocks[role] = {
            "n": int(frame.height),
            "sigma_hat_hist": _pct(sig),
            "width_freq": _width_freq(widths),
            "n_distinct_widths": int(np.unique(widths).size),
            "mean_width": float(widths.mean()),
            "coverage": float(((lo <= y_int) & (y_int <= hi)).mean()),
            "width_vs_abs_error_corr": _corr(widths.astype(float), err_abs),
            "quartile_mechanism": _quartile_mechanism(lo, hi, y_int, pred),
        }

    return {
        "split": split_name,
        "n_calib": int(calib.height),
        "n_calib_recent": int(recent.height),
        "n_test": int(test.height),
        "chosen_c": cal.c,
        "calib_coverage_at_fit": cal.calib_coverage,
        "sigma_median_calib": cal.sigma_median,
        "sigma_floor_calib": cal.sigma_floor,
        "calib": blocks["calib"],
        "test": blocks["test"],
    }


def main() -> int:
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])

    print("[1/2] Building Phase 5 panel (walk-forward, real data) ...")
    panel, _ = build_phase5_panel(_allow_real_data=True)
    print(f"  panel_rows={panel.height}")

    split_names = list(dict.fromkeys(panel["split"].to_list()))
    print(f"[2/2] Diagnosing {len(split_names)} splits (Track A; read-only) ...")
    results: list[dict] = []
    for s in split_names:
        calib = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_CALIB))
        test = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_TEST))
        if calib.height == 0 or test.height == 0:
            continue
        results.append(_diagnose_split(s, calib, test, per_cp_window_days=per_cp_window_days))

    out = {
        "purpose": "Track A diagnose-first: explain wide-bin over-coverage (read-only; no method change)",
        "method": "normalized_quantization_aware",
        "sigma_proxy": SIGMA_PROXY,
        "heterosced_band": [HETEROSCED_COVERAGE_LOW, HETEROSCED_COVERAGE_HIGH],
        "heterosced_n_bins": HETEROSCED_N_BINS,
        "per_cp_window_days": per_cp_window_days,
        "splits": results,
    }
    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase5_hetero_diagnose.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="ascii",
    )
    (out_dir / "phase5_hetero_diagnose.md").write_text(_render_md(out), encoding="ascii")

    print("\n[sigma_hat tail + width spread per split]")
    for r in results:
        for role in ("calib", "test"):
            b = r[role]
            sh = b["sigma_hat_hist"]
            print(
                f"  {r['split']} [{role}]: sigma p50={sh['p50']:.3f} p99={sh['p99']:.3f} "
                f"tail(p99/p50)={sh['tail_ratio_p99_p50']:.2f} max={sh['max']:.3f} | "
                f"widths distinct={b['n_distinct_widths']} mean={b['mean_width']:.2f} "
                f"cov={b['coverage']:.4f}"
            )

    print("\n[width vs |error| correlation + wide-bin slack (test)]")
    for r in results:
        c = r["test"]["width_vs_abs_error_corr"]
        qm = r["test"]["quartile_mechanism"]
        wide = qm[-1] if qm else None
        cp = f"pearson={c['pearson']:.3f} spearman={c['spearman']:.3f}" if c["pearson"] is not None else c.get("note", "n/a")
        if wide is not None:
            print(
                f"  {r['split']}: {cp} | widest bin [{wide['width_lo']:.0f}-{wide['width_hi']:.0f}] "
                f"cov={wide['coverage']:.3f} mean_w={wide['mean_width']:.2f} "
                f"mean|e|={wide['mean_abs_error_int']:.2f} slack={wide['slack_brackets']:.2f} (n={wide['n']})"
            )
    print(f"\n  see {out_dir / 'phase5_hetero_diagnose.md'}")
    return 0


def _render_md(out: dict) -> str:
    lines = [
        "# Phase 5 - Track A diagnose-first (heteroscedasticity; read-only)",
        "",
        f"- Method: `{out['method']}` (sigma_hat = sqrt(`{out['sigma_proxy']}`))",
        f"- Heteroscedasticity band: `{out['heterosced_band'][0]:.2f} .. {out['heterosced_band'][1]:.2f}` "
        f"({out['heterosced_n_bins']} width-quartile bins); per-CP window `{out['per_cp_window_days']}` d",
        "- No model/gate/contract changed. Diagnostics only.",
        "",
        "## sigma_hat distribution (frozen calib median/floor reused on test)",
        "",
        "| split | role | p01 | p25 | p50 | p75 | p95 | p99 | max | tail p99/p50 |",
        "|-------|------|-----|-----|-----|-----|-----|-----|-----|--------------|",
    ]
    for r in out["splits"]:
        for role in ("calib", "test"):
            h = r[role]["sigma_hat_hist"]
            tr = f"{h['tail_ratio_p99_p50']:.2f}" if h["tail_ratio_p99_p50"] is not None else "-"
            lines.append(
                f"| {r['split']} | {role} | {h['p01']:.2f} | {h['p25']:.2f} | {h['p50']:.2f} | "
                f"{h['p75']:.2f} | {h['p95']:.2f} | {h['p99']:.2f} | {h['max']:.2f} | {tr} |"
            )
    lines.extend([
        "",
        "## Integer width frequency (test)",
        "",
        "| split | width:frac (each emitted width) | distinct | mean |",
        "|-------|----------------------------------|----------|------|",
    ])
    for r in out["splits"]:
        b = r["test"]
        freq = " ".join(f"{d['width']}:{d['frac']:.3f}" for d in b["width_freq"])
        lines.append(f"| {r['split']} | {freq} | {b['n_distinct_widths']} | {b['mean_width']:.2f} |")
    lines.extend([
        "",
        "## Width vs |error_int| correlation (test)",
        "",
        "| split | pearson | spearman |",
        "|-------|---------|----------|",
    ])
    for r in out["splits"]:
        c = r["test"]["width_vs_abs_error_corr"]
        if c["pearson"] is None:
            lines.append(f"| {r['split']} | - | - |")
        else:
            lines.append(f"| {r['split']} | {c['pearson']:.3f} | {c['spearman']:.3f} |")
    lines.extend([
        "",
        "## Per width-quartile mechanism (test; gate-mirrored bins)",
        "",
        "_slack = mean_width - (2*mean|error_int| + 1). Positive slack in wide bins = "
        "sigma over-states difficulty (interval wider than the realized miss needs)._",
        "",
        "| split | bin [w_lo-w_hi] | n | coverage | mean width | mean|e| | needed | slack | in band |",
        "|-------|-----------------|---|----------|------------|---------|--------|-------|---------|",
    ])
    for r in out["splits"]:
        for q in r["test"]["quartile_mechanism"]:
            lines.append(
                f"| {r['split']} | [{q['width_lo']:.0f}-{q['width_hi']:.0f}] | {q['n']} | "
                f"{q['coverage']:.3f} | {q['mean_width']:.2f} | {q['mean_abs_error_int']:.2f} | "
                f"{q['needed_width']:.2f} | {q['slack_brackets']:.2f} | {q['in_band']} |"
            )
    lines.extend([
        "",
        "## Reading",
        "",
        "- If the widest quartile carries large positive **slack** with coverage ~1.00,",
        "  the sigma_hat tail inflates widths beyond the realized error -> a sigma-tail",
        "  taming hypothesis (winsorize / transform / Mondrian by sigma-bucket) is indicated.",
        "- If width vs |error| correlation is weak, width is not tracking difficulty at all",
        "  -> the proxy itself is suspect (separate, pre-registered question; not this change).",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
