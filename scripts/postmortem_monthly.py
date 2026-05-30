"""Monthly postmortem summary (T-X-3, REQ-OPS-4 extension).

Reads forecast JSONs from artifacts/forecasts/, pairs with truth labels,
and emits reports/postmortem/<YYYY-MM>.md + .json summarizing the last 30 days.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

import numpy as np

from core.eval.metrics import bracket_match_at_p50

REPO = Path(__file__).resolve().parents[1]


def summarize(forecast_rows: list[dict], labels: Sequence[dict]) -> dict:
    """Summarize last-30-day forecast performance.

    Parameters
    ----------
    forecast_rows : list[dict]
        Each dict must have at minimum ``date`` (ISO str or date), ``p50_int`` (int).
        Optional: ``confidence`` (float in [0,1]).
    labels : sequence of dict
        Each dict must have ``date`` and ``tmax_int``.

    Returns
    -------
    dict with keys: bracket_match, ece, ece_reason, drift_mean_30d,
    drift_mean_prior_30d, drift_delta, ev.
    """
    # Build truth lookup
    truth_map: dict[str, int] = {}
    for lb in labels:
        d = lb["date"] if isinstance(lb["date"], str) else lb["date"].isoformat()
        if lb.get("tmax_int") is not None:
            truth_map[d] = int(lb["tmax_int"])

    # Pair forecasts with truth
    pairs: list[dict] = []
    for row in forecast_rows:
        d = row["date"] if isinstance(row["date"], str) else row["date"].isoformat()
        if d in truth_map:
            pairs.append({
                "date": d,
                "p50_int": int(row["p50_int"]),
                "truth_int": truth_map[d],
                "confidence": row.get("confidence"),
            })

    # Sort by date descending, take last 30
    pairs.sort(key=lambda r: r["date"], reverse=True)
    last30 = pairs[:30]

    if not last30:
        return {
            "bracket_match": None,
            "n_pairs": 0,
            "ece": None,
            "ece_reason": "no forecast-truth pairs available",
            "drift_mean_30d": None,
            "drift_mean_prior_30d": None,
            "drift_delta": None,
            "ev": "n/a (live-only, no historical odds)",
        }

    pred = np.array([r["p50_int"] for r in last30], dtype=int)
    truth = np.array([r["truth_int"] for r in last30], dtype=int)
    bm = bracket_match_at_p50(pred, truth)

    # ECE: only if confidence column present on all rows
    confs = [r["confidence"] for r in last30]
    if all(c is not None for c in confs):
        from core.confidence.score import ece as compute_ece
        correct = (pred == truth).astype(int)
        ece_val = compute_ece(confs, correct.tolist())
        ece_reason = None
    else:
        ece_val = None
        ece_reason = "confidence column missing or incomplete"

    # Drift: mean truth last 30d vs prior 30d (from all labels)
    all_truth_dates = sorted(truth_map.keys(), reverse=True)
    last30_dates = set(r["date"] for r in last30)
    prior_truths = [
        truth_map[d] for d in all_truth_dates
        if d not in last30_dates
    ][:30]

    mean_30d = float(np.mean(truth))
    mean_prior = float(np.mean(prior_truths)) if prior_truths else None
    drift_delta = (mean_30d - mean_prior) if mean_prior is not None else None

    return {
        "bracket_match": float(bm),
        "n_pairs": len(last30),
        "ece": ece_val,
        "ece_reason": ece_reason,
        "drift_mean_30d": round(mean_30d, 2),
        "drift_mean_prior_30d": round(mean_prior, 2) if mean_prior is not None else None,
        "drift_delta": round(drift_delta, 2) if drift_delta is not None else None,
        "ev": "n/a (live-only, no historical odds)",
    }


def _load_forecast_jsons(root: Path) -> list[dict]:
    """Load all forecast JSONs from artifacts/forecasts/."""
    rows: list[dict] = []
    if not root.exists():
        return rows
    for fp in sorted(root.glob("*.json")):
        try:
            with open(fp, encoding="ascii") as fh:
                data = json.load(fh)
            if "p50_int" in data and "date" in data:
                rows.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return rows


def _build_labels_from_csv() -> list[dict]:
    """Load truth labels via the standard pipeline."""
    from core.contracts.station import load_station_config
    from core.ingest.iem_csv import load_observations
    from core.labels.tmax import build_tmax_labels

    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    csv_path = REPO / "NZWN.csv"
    if not csv_path.exists():
        return []
    obs, _ = load_observations(
        csv_path,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels_df = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    return [
        {"date": r["date_local"].isoformat(), "tmax_int": r["tmax_int"]}
        for r in labels_df.select(["date_local", "tmax_int"]).unique("date_local").iter_rows(named=True)
        if r["tmax_int"] is not None
    ]


def main() -> None:
    """Entry point: read forecasts, summarize, emit reports."""
    forecast_root = REPO / "artifacts" / "forecasts"
    forecast_rows = _load_forecast_jsons(forecast_root)

    today = date.today()
    month_str = today.strftime("%Y-%m")
    out_dir = REPO / "reports" / "postmortem"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not forecast_rows:
        # Graceful: no data
        report = {
            "month": month_str,
            "status": "no forecast data found in artifacts/forecasts/",
            "bracket_match": None,
            "n_pairs": 0,
            "ece": None,
            "ece_reason": "no data",
            "drift_mean_30d": None,
            "drift_mean_prior_30d": None,
            "drift_delta": None,
            "ev": "n/a (live-only, no historical odds)",
        }
        md = (
            f"# Monthly Postmortem {month_str}\n\n"
            "No forecast data found in `artifacts/forecasts/`.\n"
            "EV: n/a (live-only, no historical odds)\n"
        )
    else:
        labels = _build_labels_from_csv()
        report = summarize(forecast_rows, labels)
        report["month"] = month_str

        md_lines = [
            f"# Monthly Postmortem {month_str}",
            "",
            f"- n_pairs: {report['n_pairs']}",
            f"- bracket_match: {report['bracket_match']}",
            f"- ECE: {report['ece'] if report['ece'] is not None else report['ece_reason']}",
            f"- drift_mean_30d: {report['drift_mean_30d']}",
            f"- drift_mean_prior_30d: {report['drift_mean_prior_30d']}",
            f"- drift_delta: {report['drift_delta']}",
            f"- EV: {report['ev']}",
            "",
        ]
        md = "\n".join(md_lines)

    (out_dir / f"{month_str}.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2), encoding="ascii"
    )
    (out_dir / f"{month_str}.md").write_text(md, encoding="ascii")
    print(f"OK: reports/postmortem/{month_str}.md + .json")


if __name__ == "__main__":
    main()
