"""Conservative per-CP serving router (Phase 3, T-11-9).

Encodes the FROZEN routing table from the serving candidate matrix
(reports/serving/candidate_matrix_v0.{md,json}; prereg
contracts/serving_candidate_matrix_v0_prereg.md, review PASS 10/10):

    CP20/21/22 -> ecmwf_residual when causal NWP is available; else gfs_residual
                  if only GFS is present; else ridge.
    CP23       -> ridge always.

Two invariants this module must never break:
  * The |GFS-ECMWF| spread is never a routing input (T-11-6 spread study was
    only FEASIBLE-CONDITIONAL; routing must not depend on it).
  * CP23 is decided independently and is never promoted to gfs_residual: GFS has
    the lower pooled MAE there but degrades the calm stratum (calm_ok=false).

Pure decision logic -- no NWP fetch, no model fitting. Phase 3 serving has no NWP
wired in (Live NWP is Phase 5), so callers pass ecmwf_available/gfs_available
False and the table degrades to ridge with a recorded reason. Phase 5 only flips
the availability flags; this logic does not change.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

NWP_LEAD_CPS = frozenset({20, 21, 22})
CONSERVATIVE_RIDGE_CPS = frozenset({23})
MATRIX_CPS = NWP_LEAD_CPS | CONSERVATIVE_RIDGE_CPS

# Models the Phase 3 CLI can execute today; residual models need NWP (Phase 5).
SERVABLE_NOW = frozenset({"ridge", "empirical"})


@dataclass(frozen=True)
class RouteDecision:
    cp: int
    model_route: str
    fallback_used: bool
    fallback_reason: str | None
    ecmwf_available: bool
    gfs_available: bool
    nwp_run_time_utc: str | None = None
    spread_used: bool = False  # invariant: spread is never a routing input

    def as_dict(self) -> dict:
        return asdict(self)


def recommend_route(
    cp: int,
    *,
    ecmwf_available: bool,
    gfs_available: bool,
    nwp_run_time_utc: str | None = None,
) -> RouteDecision:
    """Conservative routing decision for control-point hour ``cp`` (20-23)."""
    if cp not in MATRIX_CPS:
        raise ValueError(
            f"router has no rule for CP {cp}; the serving matrix covers "
            f"{sorted(MATRIX_CPS)} only"
        )

    if cp in CONSERVATIVE_RIDGE_CPS:
        # Ridge always at CP23: GFS wins pooled MAE but degrades calm, so it is
        # intentionally not promoted here.
        reason = (
            "cp23_conservative_ridge_gfs_not_promoted_calm_degraded"
            if gfs_available
            else None
        )
        return RouteDecision(
            cp=cp,
            model_route="ridge",
            fallback_used=False,
            fallback_reason=reason,
            ecmwf_available=ecmwf_available,
            gfs_available=gfs_available,
            nwp_run_time_utc=nwp_run_time_utc,
        )

    if ecmwf_available:
        return RouteDecision(
            cp=cp,
            model_route="ecmwf_residual",
            fallback_used=False,
            fallback_reason=None,
            ecmwf_available=ecmwf_available,
            gfs_available=gfs_available,
            nwp_run_time_utc=nwp_run_time_utc,
        )
    if gfs_available:
        return RouteDecision(
            cp=cp,
            model_route="gfs_residual",
            fallback_used=True,
            fallback_reason="ecmwf_unavailable_fallback_gfs_residual",
            ecmwf_available=ecmwf_available,
            gfs_available=gfs_available,
            nwp_run_time_utc=nwp_run_time_utc,
        )
    return RouteDecision(
        cp=cp,
        model_route="ridge",
        fallback_used=True,
        fallback_reason="no_causal_nwp_fallback_ridge",
        ecmwf_available=ecmwf_available,
        gfs_available=gfs_available,
        nwp_run_time_utc=nwp_run_time_utc,
    )


def resolve_servable(model_route: str) -> tuple[str, str | None]:
    """Map a routed model to one the CLI can serve now.

    Returns ``(served_model, degraded_reason)``; ``degraded_reason`` is None when
    the routed model is already servable, else the residual model degrades to
    ridge (Phase 3 has no NWP serving path).
    """
    if model_route in SERVABLE_NOW:
        return model_route, None
    return "ridge", f"{model_route}_not_servable_phase3_fallback_ridge"


__all__ = [
    "RouteDecision",
    "recommend_route",
    "resolve_servable",
    "SERVABLE_NOW",
    "NWP_LEAD_CPS",
    "CONSERVATIVE_RIDGE_CPS",
    "MATRIX_CPS",
]
