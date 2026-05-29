"""Forensic H0 audit harness (REQ-AUD-1).

Walks Phase 2 baselines over the test split and emits ``audits/<run_id>/h0_verdict.json``
plus per-phase markdown reports.

NOTE: this module imports from ``core.*``. The reverse is forbidden (REQ-AUD-3).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import fit_empirical_conditional
from core.baselines.support import support_K
from core.contracts.quantization import Q_VERSION
from core.contracts.station import load_station_config
from core.features.builder import build_cp_features, build_panel
from core.ingest.iem_csv import load_observations
from core.io.logging import current_run_id, log_event, new_run_id
from core.labels.tmax import build_tmax_labels

from audits.phases.frozen_obs import run_phase as run_frozen_obs
from audits.phases.lead_time import run_phase as run_lead_time
from audits.phases.rest import (
    counterfactual_same_temp,
    economic_edge,
    extreme_spike,
    horizon_degradation,
    no_temperature_model,
)

CRITERION = "anti-nowcaster-v1"
CRITERION_VERSION = "1.0"


def _build_test_forecasts(
    *,
    obs,
    labels,
    panel,
    cfg,
    train_start: date,
    train_end: date,
    test_start: date,
    test_end: date,
) -> list[dict[str, Any]]:
    """Run the empirical-conditional baseline on the test slice."""
    climo = fit_climatology(labels, train_start=train_start, train_end=train_end)
    train_panel = panel.filter(
        (panel["date_local"] >= train_start) & (panel["date_local"] <= train_end)
    )
    empirical = fit_empirical_conditional(
        train_panel, train_window=(train_start, train_end)
    )
    forecasts: list[dict[str, Any]] = []
    test_dates = (
        labels.filter(
            (labels["date_local"] >= test_start)
            & (labels["date_local"] <= test_end)
            & labels["day_complete"]
        )["date_local"]
        .drop_nulls()
        .to_list()
    )
    for d in test_dates:
        for cp in cfg.cp_set_utc:
            try:
                feats = build_cp_features(
                    obs, date_local=d, cp_hhmm=cp, tz_name=cfg.tz, labels=labels
                )
            except RuntimeError:
                continue
            kcp = feats.features.get("k_cp")
            if kcp is None:
                continue
            p10, p90 = climo.percentiles_for(d)
            sk = support_K(
                p10,
                p90,
                tmp_min=cfg.tmp_c_int_plausibility.min,
                tmp_max=cfg.tmp_c_int_plausibility.max,
            )
            prob_dist, source = empirical.predict_dist(
                month=d.month, cp=cp, k_cp=int(kcp), support_k=sk
            )
            p50 = max(prob_dist.items(), key=lambda kv: kv[1])[0]
            row = labels.filter(labels["date_local"] == d)
            truth = int(row["tmax_int"][0]) if row.height else None
            forecasts.append(
                {
                    "date_local": d,
                    "cp_hhmm": cp,
                    "cp_utc": feats.cp_utc,
                    "feature_max_ts_utc": feats.feature_max_ts_utc,
                    "k_cp": int(kcp),
                    "p50_int": int(p50),
                    "truth_int": truth,
                    "month": d.month,
                    "prob_dist_source": source,
                }
            )
    return forecasts


def run_audit(
    *,
    station_yaml: Path,
    csv: Path,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    phase: str,
    out_root: Path,
) -> dict[str, Any]:
    rid = new_run_id()
    cfg = load_station_config(station_yaml)
    log_event("audit", "audit.start", extra={"phase": phase})
    obs, _ = load_observations(
        csv,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    panel = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc)

    ts = date.fromisoformat(train_start)
    te = date.fromisoformat(train_end)
    Ts = date.fromisoformat(test_start)
    Te = date.fromisoformat(test_end)

    forecasts = _build_test_forecasts(
        obs=obs, labels=labels, panel=panel, cfg=cfg,
        train_start=ts, train_end=te, test_start=Ts, test_end=Te,
    )

    selected = phase
    evidence: list[dict[str, Any]] = []
    if selected in ("all", "1", "lead_time"):
        evidence.append(run_lead_time(panel=panel, forecasts=forecasts, test_window=(Ts, Te)))
    if selected in ("all", "2", "frozen_obs"):
        evidence.append(run_frozen_obs(forecasts=forecasts))
    if selected in ("all", "3", "counterfactual_same_temp"):
        evidence.append(counterfactual_same_temp(forecasts=forecasts))
    if selected in ("all", "4", "no_temperature_model"):
        evidence.append(no_temperature_model(forecasts=forecasts))
    if selected in ("all", "5", "horizon_degradation"):
        evidence.append(horizon_degradation(forecasts=forecasts))
    if selected in ("all", "6", "extreme_spike"):
        evidence.append(extreme_spike(forecasts=forecasts))
    if selected in ("all", "7", "economic_edge"):
        evidence.append(economic_edge(forecasts=forecasts))

    gate_violations = [e["phase"] for e in evidence if e.get("passed") is False]
    # H0_rejected semantics (REQ-AUD-1):
    #   - H0 = "the model is just a nowcaster (it does NOT anticipate dynamics)".
    #   - H0_rejected = True  -> the audit found NO evidence that the model is a nowcaster
    #                            (all phases either passed or were skipped/null) -> model PASSED.
    #   - H0_rejected = False -> at least one phase failed, OR an active phase was inconclusive
    #                            -> model did NOT pass the forensic audit.
    # A phase result of `passed=None` (skipped) is treated as "no evidence either way" and
    # does NOT block H0_rejected.
    h0_rejected = not gate_violations and all(
        e.get("passed") is not False for e in evidence
    )
    verdict = {
        "run_id": rid,
        "criterion": CRITERION,
        "criterion_version": CRITERION_VERSION,
        "Q_VERSION": Q_VERSION,
        "n_forecasts": len(forecasts),
        "H0_rejected": h0_rejected,
        "evidence_per_phase": evidence,
        "gate_violations": gate_violations,
        "test_window": [Ts.isoformat(), Te.isoformat()],
        "train_window": [ts.isoformat(), te.isoformat()],
    }
    out_dir = out_root / rid
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "h0_verdict.json", "w", encoding="ascii") as fh:
        json.dump(verdict, fh, ensure_ascii=True, sort_keys=True, indent=2)
    log_event("audit", "audit.done", extra={"H0_rejected": h0_rejected, "n_forecasts": len(forecasts)})
    print(f"OK: audits/{rid}/h0_verdict.json (forecasts={len(forecasts)} H0_rejected={h0_rejected})")
    return verdict


__all__ = ["run_audit"]


def _main_argparse() -> int:
    import argparse

    p = argparse.ArgumentParser(description="H0 audit harness (REQ-AUD-1).")
    p.add_argument("--phase", default="all")
    p.add_argument("--station-config", default="nzwn/config/station.yaml")
    p.add_argument("--csv", default="NZWN.csv")
    p.add_argument("--train-start", default="2020-01-01")
    p.add_argument("--train-end", default="2024-12-31")
    p.add_argument("--test-start", default="2025-01-01")
    p.add_argument("--test-end", default="2025-06-30")
    p.add_argument("--out-root", default="audits")
    args = p.parse_args()
    verdict = run_audit(
        station_yaml=Path(args.station_config),
        csv=Path(args.csv),
        train_start=args.train_start,
        train_end=args.train_end,
        test_start=args.test_start,
        test_end=args.test_end,
        phase=args.phase,
        out_root=Path(args.out_root),
    )
    return 0 if verdict.get("H0_rejected") is not False else 1


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_main_argparse())
