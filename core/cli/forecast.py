"""CLI: tmax forecast (Phase 2 baseline)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

import typer

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import EmpiricalConditional, fit_empirical_conditional
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.intervals import discrete_ic
from core.features.builder import build_cp_features, build_panel
from core.features.training_panel import FEATURE_COLUMNS, build_training_panel
from core.ingest.iem_csv import load_observations
from core.io.logging import log_event, new_run_id
from core.io.timeutil import day_local_window
from core.labels.tmax import build_tmax_labels
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_dist as ridge_predict_dist
from core.cli.routing import recommend_route, resolve_servable

# Phase 3 serving has NO live NWP wired in (Live NWP is Phase 5). These are the single
# switch the Phase 5 work flips; until then the router degrades CP20-22 to ridge. They are
# named (not inlined) so the Phase 5 wiring point is greppable and impossible to miss.
# TODO(Phase 5): replace with a live causal-NWP availability probe (see PLAN_2026-06-01.md
# Fase 5; e.g. core/ingest/nwp_live.py) and pass the real run_time into recommend_route.
_PHASE3_ECMWF_AVAILABLE = False
_PHASE3_GFS_AVAILABLE = False


def _join_reason(existing: str | None, new: str) -> str:
    return f"{existing};{new}" if existing else new


def _emit_routing_banner(routing: dict, ic_low: int, ic_high: int) -> None:
    """Print the --model auto diagnostic to stderr (keeps stdout JSON clean)."""
    typer.echo(
        f"[forecast --model auto] CP{routing['cp']} "
        f"route={routing['model_route']} served={routing['served_model']} "
        f"fallback={routing['fallback_used']} "
        f"reason={routing['fallback_reason'] or routing['decision_reason'] or routing['degraded_reason'] or '-'}",
        err=True,
    )
    typer.echo(
        f"  nwp: ecmwf={routing['ecmwf_available']} gfs={routing['gfs_available']} "
        f"run_time={routing['nwp_run_time_utc'] or 'none'} "
        f"spread_used={routing['spread_used']}",
        err=True,
    )
    typer.echo(
        f"  train: {routing['train_start']}..{routing['train_end']}  "
        f"IC80: [{ic_low}, {ic_high}]",
        err=True,
    )


def run(
    station_yaml: Path = typer.Option(Path("nzwn/config/station.yaml"), "--station-config"),
    csv: Path = typer.Option(Path("NZWN.csv"), "--csv"),
    target_date: str = typer.Option(..., "--date"),
    cp: str = typer.Option(..., "--cp"),
    train_start: str = typer.Option("2020-01-01", "--train-start"),
    train_end: str | None = typer.Option(None, "--train-end"),
    out_root: Path = typer.Option(Path("artifacts/forecasts"), "--out-root"),
    model: str = typer.Option("empirical", "--model", help="Forecast model: 'empirical' (default baseline), 'ridge' (Phase 3 trained), or 'auto' (conservative per-CP router)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Emit a forecast row. Default model is the Phase-2 empirical baseline; ``--model ridge``
    uses the trained Phase-3 band-aware Ridge. The default is NOT changed silently - the trained
    model is opt-in via the flag until it is promoted deliberately."""
    if model not in ("empirical", "ridge", "auto"):
        raise typer.BadParameter(f"--model must be one of 'empirical', 'ridge', 'auto'; got {model!r}")
    rid = new_run_id()
    cfg = load_station_config(station_yaml)
    cp_hhmm = f"{int(cp):02d}:00"
    if cp_hhmm not in cfg.cp_set_utc:
        raise typer.BadParameter(f"CP {cp_hhmm} not in CP_SET {cfg.cp_set_utc}")
    d = date.fromisoformat(target_date)
    train_end_d = date.fromisoformat(train_end) if train_end else date.fromordinal(d.toordinal() - 1)
    train_start_d = date.fromisoformat(train_start)

    obs, stats = load_observations(
        csv,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(
        obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc
    )
    panel = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc)
    train_panel = panel.filter(
        (panel["date_local"] >= train_start_d) & (panel["date_local"] <= train_end_d)
    )
    climo = fit_climatology(labels, train_start=train_start_d, train_end=train_end_d)
    empirical = fit_empirical_conditional(
        train_panel, train_window=(train_start_d, train_end_d)
    )

    feats = build_cp_features(obs, date_local=d, cp_hhmm=cp_hhmm, tz_name=cfg.tz, labels=labels)
    p10, p90 = climo.percentiles_for(d)
    sk = support_K(
        p10, p90, tmp_min=cfg.tmp_c_int_plausibility.min, tmp_max=cfg.tmp_c_int_plausibility.max
    )
    kcp = feats.features.get("k_cp")
    if kcp is None:
        # fall back to climatology-only with no condition
        kcp_for_pred = Q(climo.tmax_dec_for(d))
    else:
        kcp_for_pred = int(kcp)

    # Resolve the effective servable model. 'auto' consults the conservative
    # per-CP router; Phase 3 serving has no NWP wired in (Live NWP is Phase 5),
    # so ECMWF/GFS are unavailable here and the router degrades to ridge. Phase 5
    # flips the availability flags and the same table routes to the residuals.
    route = None
    degraded_reason = None
    if model == "auto":
        route = recommend_route(
            int(cp),
            ecmwf_available=_PHASE3_ECMWF_AVAILABLE,
            gfs_available=_PHASE3_GFS_AVAILABLE,
            nwp_run_time_utc=None,
        )
        effective_model, degraded_reason = resolve_servable(route.model_route)
    else:
        effective_model = model

    if effective_model == "ridge":  # Phase 3 band-aware Ridge, clim anchor
        import numpy as np

        tpanel = build_training_panel(
            obs, labels, climo=climo, tz_name=cfg.tz, cp_set=cfg.cp_set_utc,
            dates=[r for r in panel["date_local"].unique().to_list()
                   if r is not None and train_start_d <= r <= train_end_d],
        ).filter(pl.col("cp") == cp_hhmm)
        if tpanel.height < 100:
            if model != "auto":
                raise typer.BadParameter(
                    f"ridge needs >=100 training rows at CP {cp_hhmm}; got {tpanel.height}"
                )
            # auto: graceful degradation to the empirical floor (do not explode).
            effective_model = "empirical"
            degraded_reason = _join_reason(
                degraded_reason,
                f"ridge_insufficient_rows_{tpanel.height}_fallback_empirical",
            )
        else:
            cfg_ridge = RidgeBandConfig(feature_columns=tuple(FEATURE_COLUMNS),
                                        tau=0.5, mode="linear", use_climatology_anchor=True)
            X_tr = np.column_stack([tpanel[c].to_numpy().astype(float) for c in FEATURE_COLUMNS])
            y_tr = tpanel["target_tmax_int"].to_numpy().astype(int)
            clim_tr = np.array([float(climo.tmax_dec_for(dd)) for dd in tpanel["date_local"].to_list()])
            fitted = fit_ridge_band(X_tr, y_tr, config=cfg_ridge, clim_train=clim_tr)
            x_row = np.array([[float(feats.features.get(c)) if feats.features.get(c) is not None
                               else float("nan") for c in FEATURE_COLUMNS]])
            clim_row = np.array([float(climo.tmax_dec_for(d))])
            prob_dist = ridge_predict_dist(fitted, x_row, [sk], clim=clim_row)[0]
            source = f"ridge_band_alpha_{fitted.alpha}"
            model_version = "phase3-ridge-band-v1.0"

    if effective_model == "empirical":
        prob_dist, source = empirical.predict_dist(
            month=d.month, cp=cp_hhmm, k_cp=kcp_for_pred, support_k=sk
        )
        model_version = "baseline-empirical-v0.1"
    p50 = max(prob_dist.items(), key=lambda kv: kv[1])[0]
    low, high = discrete_ic(prob_dist, p_low=0.10, p_high=0.90)
    forecast_row = {
        "run_id": rid,
        "date_local": d.isoformat(),
        "cp_utc": feats.cp_utc.isoformat(),
        "cp_local": feats.cp_local.isoformat(),
        "tz_name": cfg.tz,
        "station": cfg.icao,
        "p50_int": int(p50),
        "ic80_low_int": int(low),
        "ic80_high_int": int(high),
        "support_k": sk,
        "prob_dist": {str(k): v for k, v in prob_dist.items()},
        "prob_dist_source": source,
        "model_version": model_version,
        "tau": None,
        "fallback_rate": stats.fallback_rate,
    }

    if route is not None:
        forecast_row["model_requested"] = model
        forecast_row["served_model"] = effective_model
        forecast_row["routing"] = {
            "cp": route.cp,
            "model_route": route.model_route,
            "served_model": effective_model,
            "fallback_used": route.fallback_used,
            "fallback_reason": route.fallback_reason,
            "decision_reason": route.decision_reason,
            "degraded_reason": degraded_reason,
            "ecmwf_available": route.ecmwf_available,
            "gfs_available": route.gfs_available,
            "nwp_run_time_utc": route.nwp_run_time_utc,
            "spread_used": route.spread_used,
            "train_start": train_start_d.isoformat(),
            "train_end": train_end_d.isoformat(),
        }
        _emit_routing_banner(forecast_row["routing"], int(low), int(high))

    log_event(
        "forecast",
        "forecast.emit",
        cp_utc=feats.cp_utc,
        cp_local=feats.cp_local,
        tz_name=cfg.tz,
        extra={
            "p50_int": forecast_row["p50_int"],
            "support_k_n": len(sk),
            "prob_dist_source": source,
        },
    )

    if dry_run:
        typer.echo(json.dumps(forecast_row, indent=2))
        return

    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / f"{rid}.json"
    with open(out_path, "w", encoding="ascii") as fh:
        json.dump(forecast_row, fh, ensure_ascii=True, sort_keys=True, indent=2)
    typer.echo(f"OK: {out_path}")


__all__ = ["run"]
