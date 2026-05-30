"""Read-only wide-bin audit for REQ-AUD-5 (update.txt Passo 1).

This script changes NO method, NO gate threshold, and NO contract. It reads the
standing v1.0 normalized quantization-aware conformal method -- the method that
remains after Track A.A1 (winsorization) and Track A.A3 (Mondrian by sigma bucket)
both closed as real-but-insufficient -- and reports, per walk-forward split and per
REQ-AUD-5 width bin:

  - n, successes, empirical coverage, and the Wilson 95% binomial interval, so a
    ``coverage = 1.000`` on ``n ~ 11`` is read as a small-sample estimate, not a
    deterministic fact (update.txt Passo 1, item 3);
  - the composition of the UPPER (wide) bins by month, by CP, and by the sigma proxy
    (``p50_var``) / ``nwp_spread``, to separate an unavoidable structural effect from a
    clustered operational regime / sampling instability (item 4).

The binning is reproduced EXACTLY from ``core.eval.gates_phase5.heteroscedasticity_gate``
(rank-based quantiles over distinct widths, ``searchsorted(..., side="right")``); see the
frozen normative definition in ``docs/req_aud5_normative.md``. The gate function itself is
also called to assert the per-bin (n, coverage) reproduced here match it.

Output: ``reports/phase5_wide_bin_audit.{md,json}``. No audit/run-id directory and no
pre-registration gate -- this is a diagnostic readout, not a one-shot pre-registered run.
"""

from __future__ import annotations

import json
import math
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
from core.eval.gates_phase5 import heteroscedasticity_gate
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]
WILSON_Z = 1.959963984540054  # 95% two-sided normal quantile


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


def _recent_tail(calib: pl.DataFrame, per_cp_window_days: int) -> pl.DataFrame:
    from datetime import timedelta

    calib_max = calib["date_local"].max()
    return calib.filter(
        calib["date_local"] >= calib_max - timedelta(days=per_cp_window_days - 1)
    )


def _wilson(successes: int, n: int, z: float = WILSON_Z) -> tuple[float, float]:
    """Wilson score 95% interval for a binomial proportion (closed form; no scipy)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _bin_assignment(widths: np.ndarray, n_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Replicate the het-gate binning EXACTLY; return (bin_idx, interior_edges)."""
    unique_widths = np.unique(widths)
    probs = np.linspace(0.0, 1.0, n_bins + 1)[1:-1]
    if probs.size:
        edges = np.quantile(unique_widths, probs, method="linear")
        bin_idx = np.searchsorted(edges, widths, side="right")
    else:
        edges = np.asarray([], dtype=float)
        bin_idx = np.zeros(widths.shape, dtype=int)
    return bin_idx.astype(int), edges


def _compose(sub: pl.DataFrame) -> dict:
    """Composition summary for a set of (wide-bin) rows: months, CPs, sigma, spread."""
    def _counts(col: str) -> dict:
        vc = sub[col].value_counts()
        # polars value_counts -> columns [col, "count"]; sort by the key for stability.
        vc = vc.sort(col)
        return {str(k): int(v) for k, v in zip(vc[col].to_list(), vc["count"].to_list())}

    sig = sub[SIGMA_PROXY].drop_nulls().to_numpy().astype(float)
    spr = sub["nwp_spread"].drop_nulls().to_numpy().astype(float)
    dates = [str(d) for d in sub["date_local"].to_list()]

    def _stats(a: np.ndarray) -> dict:
        if a.size == 0:
            return {"n": 0}
        return {
            "n": int(a.size),
            "min": float(a.min()),
            "p50": float(np.median(a)),
            "max": float(a.max()),
            "mean": float(a.mean()),
        }

    return {
        "n_rows": int(sub.height),
        "by_month": _counts("month"),
        "by_cp": _counts("cp"),
        "sigma_proxy_stats": _stats(sig),
        "nwp_spread_stats": _stats(spr),
        "n_distinct_dates": len(set(dates)),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
    }


def _audit_split(split_name: str, calib: pl.DataFrame, test: pl.DataFrame, *, per_cp_window_days: int) -> dict:
    recent = _recent_tail(calib, per_cp_window_days)
    rc_y = recent["y_true_int"].to_numpy().astype(int)
    rc_pred = recent["y_pred_dec"].to_numpy().astype(float)
    rc_sigma = recent[SIGMA_PROXY].to_list()

    test_pred = test["y_pred_dec"].to_numpy().astype(float)
    test_y = test["y_true_int"].to_numpy().astype(int)
    test_sigma = test[SIGMA_PROXY].to_list()

    cal = fit_normalized_conformal(rc_y, rc_pred, rc_sigma, config=_v1_config())
    lo, hi = apply_normalized_conformal(cal, test_pred, test_sigma)
    lo = np.asarray(lo, dtype=int)
    hi = np.asarray(hi, dtype=int)
    widths = (hi - lo + 1).astype(int)
    covered = ((lo <= test_y) & (test_y <= hi)).astype(int)

    bin_idx, edges = _bin_assignment(widths.astype(float), HETEROSCED_N_BINS)

    # Cross-check against the gate's own (n, coverage) so the reproduced binning is faithful.
    rep = heteroscedasticity_gate(
        lo, hi, test_y,
        n_bins=HETEROSCED_N_BINS,
        low=HETEROSCED_COVERAGE_LOW,
        high=HETEROSCED_COVERAGE_HIGH,
    )
    gate_by_index = {b.bin_index: (b.n, b.coverage) for b in rep.bins}

    test_aug = test.with_columns(
        pl.Series("__bin", bin_idx),
        pl.Series("__width", widths),
        pl.Series("__covered", covered),
    )

    present_bins = sorted(int(b) for b in np.unique(bin_idx))
    top_bin = present_bins[-1]
    bins_out: list[dict] = []
    for b in present_bins:
        mask = bin_idx == b
        n_b = int(mask.sum())
        succ = int(covered[mask].sum())
        cov = succ / n_b if n_b else float("nan")
        w_lo, w_hi = _wilson(succ, n_b)
        in_band = HETEROSCED_COVERAGE_LOW <= cov <= HETEROSCED_COVERAGE_HIGH
        # Faithfulness check against the gate.
        gate_match = b in gate_by_index and gate_by_index[b][0] == n_b and abs(gate_by_index[b][1] - cov) < 1e-12
        bins_out.append({
            "bin_index": b,
            "width_lo": int(widths[mask].min()),
            "width_hi": int(widths[mask].max()),
            "mean_width": float(widths[mask].mean()),
            "n": n_b,
            "successes": succ,
            "coverage": cov,
            "wilson95_lo": w_lo,
            "wilson95_hi": w_hi,
            "in_band": in_band,
            "is_wide_bin": b >= present_bins[len(present_bins) // 2],
            "gate_match": bool(gate_match),
        })

    # Composition of the UPPER half of the (present) bins -- the wide tail.
    wide_bins = present_bins[len(present_bins) // 2:]
    wide_mask = np.isin(bin_idx, wide_bins)
    wide_rows = test_aug.filter(pl.Series(wide_mask))
    top_rows = test_aug.filter(pl.col("__bin") == top_bin)

    return {
        "split": split_name,
        "n_test": int(test.height),
        "interior_edges": [float(e) for e in edges],
        "c": cal.c,
        "calib_coverage": cal.calib_coverage,
        "gate_passed": bool(rep.passed),
        "gate_mixed_in_and_out": bool(rep.mixed_in_and_out),
        "bins": bins_out,
        "wide_bins_index": wide_bins,
        "wide_bins_composition": _compose(wide_rows),
        "top_bin_index": top_bin,
        "top_bin_composition": _compose(top_rows),
    }


def _fmt_pct(x: float) -> str:
    return f"{x:.3f}" if x == x else "nan"  # nan-safe


def _render_md(out: dict) -> str:
    lines = [
        "# Phase 5 - REQ-AUD-5 wide-bin audit (read-only)",
        "",
        "Read-only diagnostic (update.txt Passo 1). NO method/gate/contract change. "
        "Method audited: standing **v1.0** normalized quantization-aware conformal "
        "(Track A.A1 and A.A3 both closed as real-but-insufficient). Normative intent + "
        "binning definition are frozen in `docs/req_aud5_normative.md`.",
        "",
        f"- Het band (unchanged): `[{HETEROSCED_COVERAGE_LOW:.2f}, {HETEROSCED_COVERAGE_HIGH:.2f}]`, "
        f"{HETEROSCED_N_BINS} width bins (rank-based over distinct widths). "
        f"Aggregate coverage target `{COVERAGE_TARGET:.2f}`.",
        "- Binomial CI: Wilson score, 95% two-sided. A `coverage=1.000` with small `n` is a "
        "point estimate; read the Wilson interval.",
        "",
        "## Per-bin coverage + Wilson 95% CI (v1.0, per split)",
        "",
        "| split | bin | width [lo-hi] | n | succ | coverage | Wilson 95% CI | in band | gate match |",
        "|-------|-----|---------------|---|------|----------|---------------|---------|------------|",
    ]
    for r in out["splits"]:
        for b in r["bins"]:
            lines.append(
                f"| {r['split']} | {b['bin_index']} | {b['width_lo']}-{b['width_hi']} | "
                f"{b['n']} | {b['successes']} | {_fmt_pct(b['coverage'])} | "
                f"[{_fmt_pct(b['wilson95_lo'])}, {_fmt_pct(b['wilson95_hi'])}] | "
                f"{b['in_band']} | {b['gate_match']} |"
            )
    lines.extend([
        "",
        "Reading: where the wide-bin Wilson interval still excludes the upper band edge "
        f"({HETEROSCED_COVERAGE_HIGH:.2f}), the over-coverage is unlikely to be pure sampling "
        "noise; where the interval straddles it, `n` is too small to call.",
        "",
        "## Wide-bin composition (upper half of present bins, per split)",
        "",
        "| split | wide bins | n rows | distinct dates | date range | by CP | sigma p50 | spread p50 |",
        "|-------|-----------|--------|----------------|------------|-------|-----------|------------|",
    ])
    for r in out["splits"]:
        comp = r["wide_bins_composition"]
        sig = comp["sigma_proxy_stats"]
        spr = comp["nwp_spread_stats"]
        by_cp = ", ".join(f"{k}:{v}" for k, v in comp["by_cp"].items())
        lines.append(
            f"| {r['split']} | {r['wide_bins_index']} | {comp['n_rows']} | "
            f"{comp['n_distinct_dates']} | {comp['date_min']}..{comp['date_max']} | "
            f"{by_cp} | {sig.get('p50', float('nan')):.4f} | "
            f"{(spr.get('p50') if spr.get('n') else float('nan')):.3f} |"
        )
    lines.extend([
        "",
        "### Wide-bin month histogram (operational-cluster check)",
        "",
        "| split | by month (month:count) |",
        "|-------|------------------------|",
    ])
    for r in out["splits"]:
        comp = r["wide_bins_composition"]
        by_month = ", ".join(f"{k}:{v}" for k, v in comp["by_month"].items())
        lines.append(f"| {r['split']} | {by_month} |")
    lines.extend([
        "",
        "## Notes",
        "",
        "- This artifact is read-only: no parameter, gate, window, or contract was changed.",
        "- v1.0 is the standing method; A1/A3 are closed (real but insufficient).",
        "- Decision on the next track (Track P: proxy/difficulty-axis change) is documented "
        "separately, docs-before-code, per update.txt Passo 2.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])

    print("[1/2] Building Phase 5 panel (walk-forward, real data) ...")
    panel, _ = build_phase5_panel(_allow_real_data=True)
    print(f"  panel_rows={panel.height}")

    split_names = list(dict.fromkeys(panel["split"].to_list()))
    print(f"[2/2] Auditing {len(split_names)} splits (v1.0; read-only) ...")
    results: list[dict] = []
    for s in split_names:
        calib = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_CALIB))
        test = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_TEST))
        if calib.height == 0 or test.height == 0:
            continue
        results.append(_audit_split(s, calib, test, per_cp_window_days=per_cp_window_days))

    out = {
        "phase": 5,
        "artifact": "req_aud5_wide_bin_audit",
        "read_only": True,
        "method": "v1.0_normalized_quantization_conformal",
        "het_band": [HETEROSCED_COVERAGE_LOW, HETEROSCED_COVERAGE_HIGH],
        "het_n_bins": HETEROSCED_N_BINS,
        "coverage_target": COVERAGE_TARGET,
        "sigma_proxy": SIGMA_PROXY,
        "ci_method": "wilson_score_95",
        "splits": results,
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase5_wide_bin_audit.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii"
    )
    (out_dir / "phase5_wide_bin_audit.md").write_text(_render_md(out), encoding="ascii")

    print("\nsummary (v1.0, read-only):")
    for r in results:
        for b in r["bins"]:
            tag = "WIDE" if b["is_wide_bin"] else "    "
            print(
                f"  {r['split']} bin{b['bin_index']} {tag} w={b['width_lo']}-{b['width_hi']} "
                f"n={b['n']} cov={_fmt_pct(b['coverage'])} "
                f"wilson=[{_fmt_pct(b['wilson95_lo'])},{_fmt_pct(b['wilson95_hi'])}] "
                f"gate_match={b['gate_match']}"
            )
    print(f"  see {out_dir / 'phase5_wide_bin_audit.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
