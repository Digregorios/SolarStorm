"""Phase 5 - Track S tail-budget vtest (Part A, CALIB-ONLY winner selection).

Per references/code-reviews/update.txt (2026-05-30): compare two FIXED tail budgets on the
SAME object the gate evaluates, using CALIB rows only (never touches test), and pick the
winner by minimum slack in the mod-wide REQ-AUD-5 bin in the late-CP regime (22Z/23Z).

  S1 (sym):  alpha_lo=0.10, alpha_hi=0.10
  S2 (asym): alpha_lo=0.05, alpha_hi=0.15   (fixed direction; NOT re-tuned)

This is a read-only analysis: no contract, no wiring, no test split, no phase5_evaluate.
It only emits reports/phase5_trackS_vtest.{md,json} to inform the winner choice. Wiring +
the single one-shot of the winner happen ONLY after approval (Part B).
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import yaml

from core.calibration.conformal import _prepare_sigma
from core.contracts.phase5 import ROLE_CALIB, SIGMA_IS_VARIANCE, SIGMA_PROXY
from core.contracts.quantization import Q
from core.eval.gates_phase5 import heteroscedasticity_gate
from scripts.phase5_panel import build_phase5_panel

REPO = Path(__file__).resolve().parents[1]
LATE_CPS = ("22:00", "23:00")
BUDGETS = {"S1": (0.10, 0.10), "S2": (0.05, 0.15)}
HET_N_BINS = 4
HET_LOW, HET_HIGH = 0.70, 0.90


def _endpoints(y_pred_dec, sigma, q_lo, q_hi):
    lo = np.array([Q(float(p + q_lo * s)) for p, s in zip(y_pred_dec, sigma)], dtype=np.int32)
    hi = np.array([Q(float(p + q_hi * s)) for p, s in zip(y_pred_dec, sigma)], dtype=np.int32)
    return lo, np.maximum(hi, lo)


def _modwide_slack(lo, hi, y_int, y_pred_dec):
    """Reproduce the REQ-AUD-5 binning; return slack stats for the mod-wide (largest-n) bin."""
    rep = heteroscedasticity_gate(lo, hi, y_int, n_bins=HET_N_BINS, low=HET_LOW, high=HET_HIGH)
    if not rep.bins:
        return None
    mod = max(rep.bins, key=lambda b: b.n)  # mod-wide = the large-n bin
    # rows in that bin (width in [width_lo, width_hi])
    widths = (hi - lo + 1).astype(int)
    mask = (widths >= int(mod.width_lo)) & (widths <= int(mod.width_hi))
    qpred = np.array([Q(float(p)) for p in y_pred_dec], dtype=int)
    mean_abs_err = float(np.mean(np.abs(y_int[mask] - qpred[mask]))) if mask.any() else 0.0
    needed = 2 * mean_abs_err + 1
    return {
        "coverage_bin": mod.coverage,
        "mean_width_bin": mod.mean_width,
        "mean_abs_error_bin": mean_abs_err,
        "needed": needed,
        "slack": mod.mean_width - needed,
        "n": mod.n,
        "coverage_in_band": HET_LOW <= mod.coverage <= HET_HIGH,
    }


def _arm(df, q_lo, q_hi):
    yp = df["y_pred_dec"].to_numpy().astype(float)
    yt = df["y_true_int"].to_numpy().astype(int)
    sigma, _, _ = _prepare_sigma(df[SIGMA_PROXY].to_list(), is_variance=SIGMA_IS_VARIANCE)
    u = (yt - yp) / sigma
    ql = float(np.quantile(u, q_lo))
    qh = float(np.quantile(u, 1.0 - q_hi))
    lo, hi = _endpoints(yp, sigma, ql, qh)
    cov_global = float(((lo <= yt) & (yt <= hi)).mean())
    n_distinct = int(np.unique((hi - lo + 1)).size)
    return lo, hi, yt, yp, cov_global, n_distinct, ql, qh


def main() -> int:
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    per_cp_window_days = int(mcfg["conformal"]["per_cp_window_days"])

    print("[1/2] Building Phase 5 panel (CALIB-ONLY vtest; test never touched) ...")
    panel, _ = build_phase5_panel(_allow_real_data=True)
    split_names = list(dict.fromkeys(panel["split"].to_list()))

    per_split = []
    for s in split_names:
        calib = panel.filter((panel["split"] == s) & (panel["role"] == ROLE_CALIB))
        if calib.height == 0:
            continue
        calib_max = calib["date_local"].max()
        recent = calib.filter(calib["date_local"] >= calib_max - timedelta(days=per_cp_window_days - 1))
        late = recent.filter(recent["cp"].is_in(list(LATE_CPS)))
        row = {"split": s, "n_recent": int(recent.height), "n_late": int(late.height), "arms": {}}
        for name, (a_lo, a_hi) in BUDGETS.items():
            _, _, _, _, cov_g, nd_g, ql_g, qh_g = _arm(recent, a_lo, a_hi)
            llo, lhi, lyt, lyp, cov_l, nd_l, ql_l, qh_l = _arm(late, a_lo, a_hi)
            slack = _modwide_slack(llo, lhi, lyt, lyp)
            row["arms"][name] = {
                "alpha_lo": a_lo, "alpha_hi": a_hi,
                "global_calib_coverage": cov_g, "global_distinct_widths": nd_g,
                "late_calib_coverage": cov_l, "late_distinct_widths": nd_l,
                "q_lo": ql_l, "q_hi": qh_l,
                "modwide": slack,
            }
        per_split.append(row)

    # Decision: score = mean_over_splits(slack_modwide); lower wins; tie -> S1.
    scores = {}
    for name in BUDGETS:
        vals = [r["arms"][name]["modwide"]["slack"] for r in per_split
                if r["arms"][name]["modwide"] is not None]
        scores[name] = float(np.mean(vals)) if vals else float("inf")
    winner = "S1" if scores["S1"] <= scores["S2"] else "S2"

    # Sanity rejection: a budget whose global calib coverage leaves [0.76,0.84] on any split,
    # or degenerate widths (<3), is flagged (informs whether the winner is usable).
    def _sane(name):
        return all(
            0.76 <= r["arms"][name]["global_calib_coverage"] <= 0.84
            and r["arms"][name]["global_distinct_widths"] >= 3
            for r in per_split
        )
    out = {
        "phase": 5, "track": "S_vtest", "mode": "calib_only_winner_selection",
        "budgets": {k: {"alpha_lo": v[0], "alpha_hi": v[1]} for k, v in BUDGETS.items()},
        "late_cps": list(LATE_CPS), "per_cp_window_days": per_cp_window_days,
        "splits": per_split,
        "scores_mean_slack_modwide": scores,
        "winner": winner,
        "winner_global_sane": _sane(winner),
        "sanity": {k: _sane(k) for k in BUDGETS},
        "notes": [
            "CALIB-ONLY: test split never read; no contract/wiring/one-shot here.",
            "Winner = min mean(slack_modwide) over splits at 22Z/23Z; tie -> S1.",
            "alpha_lo + alpha_hi = 0.20 for both arms (nominal 0.80 budget; c-rule unchanged).",
            "Q, sigma proxy (sqrt p50_var), windows, splits all inherited from v1.0.",
        ],
    }
    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase5_trackS_vtest.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2), encoding="ascii"
    )
    (out_dir / "phase5_trackS_vtest.md").write_text(_render_md(out), encoding="ascii")

    print("[2/2] winner selection (calib-only)")
    for r in per_split:
        for name in BUDGETS:
            m = r["arms"][name]["modwide"]
            ms = f"slack={m['slack']:.3f} cov={m['coverage_bin']:.3f} w={m['mean_width_bin']:.2f} (n={m['n']})" if m else "no-bin"
            print(f"  {r['split']} {name}: {ms} | global_cov={r['arms'][name]['global_calib_coverage']:.4f}")
    print(f"  scores (mean slack modwide): S1={scores['S1']:.4f}  S2={scores['S2']:.4f}")
    print(f"  WINNER={winner}  global_sane={out['winner_global_sane']}  (sanity {out['sanity']})")
    print(f"  see {out_dir / 'phase5_trackS_vtest.md'}")
    return 0


def _render_md(out: dict) -> str:
    L = [
        "# Phase 5 - Track S tail-budget vtest (CALIB-ONLY winner selection)",
        "",
        "_Read-only calib analysis (test split untouched). Winner = min mean(slack) in the "
        "mod-wide REQ-AUD-5 bin at 22Z/23Z; tie -> S1. No contract/wiring/one-shot here._",
        "",
        f"- S1: alpha_lo={BUDGETS['S1'][0]}, alpha_hi={BUDGETS['S1'][1]}; "
        f"S2: alpha_lo={BUDGETS['S2'][0]}, alpha_hi={BUDGETS['S2'][1]} (both sum 0.20)",
        f"- Late-CP regime: {', '.join(LATE_CPS)}; per-CP window {out['per_cp_window_days']} d",
        "",
        f"- **WINNER: `{out['winner']}`** (mean slack S1=`{out['scores_mean_slack_modwide']['S1']:.4f}` "
        f"vs S2=`{out['scores_mean_slack_modwide']['S2']:.4f}`); winner global-sane: "
        f"**{out['winner_global_sane']}**",
        "",
        "## Mod-wide bin slack at 22Z/23Z (calib-only, per split)",
        "",
        "| split | arm | slack | mean_width | needed | cov_bin | in[0.70,0.90] | n | global calib cov | distinct w |",
        "|-------|-----|-------|------------|--------|---------|---------------|---|------------------|------------|",
    ]
    for r in out["splits"]:
        for name in ("S1", "S2"):
            a = r["arms"][name]
            m = a["modwide"]
            if m is None:
                L.append(f"| {r['split']} | {name} | - | - | - | - | - | - | {a['global_calib_coverage']:.4f} | {a['global_distinct_widths']} |")
                continue
            L.append(
                f"| {r['split']} | {name} | {m['slack']:.3f} | {m['mean_width_bin']:.2f} | "
                f"{m['needed']:.2f} | {m['coverage_bin']:.3f} | {m['coverage_in_band']} | {m['n']} | "
                f"{a['global_calib_coverage']:.4f} | {a['global_distinct_widths']} |"
            )
    L += ["", "## Notes", ""]
    L += [f"- {n}" for n in out["notes"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
