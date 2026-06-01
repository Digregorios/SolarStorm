"""Conservative serving router (Phase 3, T-11-9).

Locks the frozen routing table from the serving candidate matrix:
  CP20-22 -> ecmwf_residual (causal NWP) | gfs_residual | ridge
  CP23    -> ridge always (gfs wins MAE but degrades calm; never promoted)
and the invariant that the |GFS-ECMWF| spread is never a routing input.
"""

from __future__ import annotations

import inspect

import pytest

from core.cli.routing import (
    MATRIX_CPS,
    RouteDecision,
    recommend_route,
    resolve_servable,
)


@pytest.mark.parametrize("cp", [20, 21, 22])
def test_cp20_22_picks_ecmwf_when_available(cp):
    d = recommend_route(cp, ecmwf_available=True, gfs_available=True)
    assert d.model_route == "ecmwf_residual"
    assert d.fallback_used is False
    assert d.fallback_reason is None


@pytest.mark.parametrize("cp", [20, 21, 22])
def test_cp20_22_falls_back_to_gfs_without_ecmwf(cp):
    d = recommend_route(cp, ecmwf_available=False, gfs_available=True)
    assert d.model_route == "gfs_residual"
    assert d.fallback_used is True
    assert "ecmwf" in d.fallback_reason


@pytest.mark.parametrize("cp", [20, 21, 22])
def test_cp20_22_falls_back_to_ridge_without_any_nwp(cp):
    d = recommend_route(cp, ecmwf_available=False, gfs_available=False)
    assert d.model_route == "ridge"
    assert d.fallback_used is True
    assert "ridge" in d.fallback_reason


def test_cp23_is_ridge_even_with_gfs_available():
    # GFS has the lower pooled MAE at CP23 but degrades calm (calm_ok=false);
    # the conservative rule must NOT promote it.
    d = recommend_route(23, ecmwf_available=False, gfs_available=True)
    assert d.model_route == "ridge"
    assert d.fallback_used is False


def test_cp23_is_ridge_even_with_ecmwf_and_gfs():
    d = recommend_route(23, ecmwf_available=True, gfs_available=True)
    assert d.model_route == "ridge"


def test_unknown_cp_raises():
    with pytest.raises(ValueError):
        recommend_route(19, ecmwf_available=True, gfs_available=True)
    with pytest.raises(ValueError):
        recommend_route(0, ecmwf_available=False, gfs_available=False)


def test_spread_is_never_a_routing_input():
    # The function must not accept a spread argument...
    params = set(inspect.signature(recommend_route).parameters)
    assert not any("spread" in p for p in params)
    # ...and every decision must record spread_used == False.
    for cp in sorted(MATRIX_CPS):
        for ec in (True, False):
            for gf in (True, False):
                d = recommend_route(cp, ecmwf_available=ec, gfs_available=gf)
                assert d.spread_used is False


def test_nwp_run_time_is_passed_through():
    d = recommend_route(
        20, ecmwf_available=True, gfs_available=True,
        nwp_run_time_utc="2025-07-15T19:00:00Z",
    )
    assert d.nwp_run_time_utc == "2025-07-15T19:00:00Z"
    assert "nwp_run_time_utc" in d.as_dict()


def test_resolve_servable_keeps_servable_models():
    assert resolve_servable("ridge") == ("ridge", None)
    assert resolve_servable("empirical") == ("empirical", None)


@pytest.mark.parametrize("residual", ["ecmwf_residual", "gfs_residual"])
def test_resolve_servable_degrades_residuals_to_ridge(residual):
    served, reason = resolve_servable(residual)
    assert served == "ridge"
    assert reason is not None and "not_servable" in reason


def test_route_decision_is_frozen():
    d = recommend_route(23, ecmwf_available=False, gfs_available=False)
    assert isinstance(d, RouteDecision)
    with pytest.raises(Exception):
        d.model_route = "empirical"  # type: ignore[misc]
