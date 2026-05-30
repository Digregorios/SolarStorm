"""Unit tests for scripts/phase5_panel.py::build_phase5_rows (workstream A).

Pure, deterministic, NO real data and NO network. A tiny synthetic Phase-4 frame
(a few dates x CPs) is fed through ``build_phase5_rows`` with an injected
``predict_fn`` so the latent forecast is fully controlled - which lets us nail the
causal ``p50_var`` assertion (a later CP must NOT change an earlier CP's variance).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import polars as pl

from core.contracts.phase5 import (
    RAW_PANEL_COLUMNS,
    RAW_PANEL_SCHEMA,
    ROLE_TEST,
)
from core.contracts.quantization import Q
from scripts.phase5_panel import build_phase5_rows


CP_HOURS = {"20:00": 20, "21:00": 21, "22:00": 22, "23:00": 23}
FEATURE_COLUMNS = ("feat_a", "feat_b")


class _FakeLgbm:
    """Minimal stand-in: just carries the feature_columns the builder reads."""

    feature_columns = FEATURE_COLUMNS


def _cp_utc(d: date, cp: str) -> datetime:
    return datetime(d.year, d.month, d.day, CP_HOURS[cp], 0, 0, tzinfo=timezone.utc)


def _make_panel(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date_local": pl.Series([r["date_local"] for r in rows], dtype=pl.Date),
            "cp": pl.Series([r["cp"] for r in rows], dtype=pl.Utf8),
            "cp_utc": pl.Series(
                [r["cp_utc"] for r in rows], dtype=pl.Datetime("us", time_zone="UTC")
            ),
            "nwp_run_time_utc": pl.Series(
                [r["nwp_run_time_utc"] for r in rows],
                dtype=pl.Datetime("us", time_zone="UTC"),
            ),
            "target_tmax_int": pl.Series(
                [r["target_tmax_int"] for r in rows], dtype=pl.Int32
            ),
            "nwp_t2m_maxtraj_c": pl.Series(
                [r["nwp_t2m_maxtraj_c"] for r in rows], dtype=pl.Float64
            ),
            "nwp_t2m_maxtraj_spread_c": pl.Series(
                [r["nwp_t2m_maxtraj_spread_c"] for r in rows], dtype=pl.Float64
            ),
            "feat_a": pl.Series([r["feat_a"] for r in rows], dtype=pl.Float64),
            "feat_b": pl.Series([r["feat_b"] for r in rows], dtype=pl.Float64),
        }
    )


def _fixture():
    """Two days. Day1 has 3 CPs (20/21/22), Day2 has 2 CPs (20/21).

    We inject predict_fn -> a fixed y_pred per row keyed by (date, cp), so p50_var is
    exactly computable and the "later CP must not leak" property is testable.

    Day1 latent y_pred by CP: 20:00 -> 10.0, 21:00 -> 12.0, 22:00 -> 100.0
      - CP 20:00: first CP   -> p50_var NULL
      - CP 21:00: 1 earlier  -> p50_var NULL (needs >= 2 earlier CPs)
      - CP 22:00: 2 earlier (10, 12) -> var([10,12]) = 1.0; the 100.0 at 22:00 is the
        CURRENT row and must be EXCLUDED. If a wrong impl included it the value changes.
    Day2 latent y_pred by CP: 20:00 -> 5.0, 21:00 -> 5.0
      - CP 20:00: first CP -> NULL ; CP 21:00: 1 earlier -> NULL.
    """
    d1, d2 = date(2024, 3, 1), date(2024, 3, 2)
    pred_map = {
        (d1, "20:00"): 10.0,
        (d1, "21:00"): 12.0,
        (d1, "22:00"): 100.0,
        (d2, "20:00"): 5.0,
        (d2, "21:00"): 5.0,
    }
    spec = [
        (d1, "20:00", 10, 9.6, 1.2),
        (d1, "21:00", 12, 11.4, 0.8),
        (d1, "22:00", 12, 11.9, None),  # null spread allowed
        (d2, "20:00", 5, 4.7, 2.0),
        (d2, "21:00", 5, 4.9, 1.5),
    ]
    rows = []
    for d, cp, ytrue, anchor, spread in spec:
        rows.append(
            {
                "date_local": d,
                "cp": cp,
                "cp_utc": _cp_utc(d, cp),
                "nwp_run_time_utc": _cp_utc(d, cp),
                "target_tmax_int": ytrue,
                "nwp_t2m_maxtraj_c": anchor,
                "nwp_t2m_maxtraj_spread_c": spread,
                "feat_a": float(ytrue),
                "feat_b": anchor,
            }
        )
    panel = _make_panel(rows)
    anchor = panel["nwp_t2m_maxtraj_c"].to_numpy().astype(float)

    def predict_fn(_lgbm, _X, _anchor):
        return np.array(
            [pred_map[(rows[i]["date_local"], rows[i]["cp"])] for i in range(len(rows))],
            dtype=float,
        )

    # Support per date: a broad integer range covering all the y_pred / truth values.
    support_by_date = {d1: list(range(0, 105)), d2: list(range(0, 105))}
    return panel, anchor, predict_fn, support_by_date, pred_map, rows


def _build():
    panel, anchor, predict_fn, support_by_date, pred_map, rows = _fixture()
    out, dists = build_phase5_rows(
        panel,
        role=ROLE_TEST,
        split_name="2024_split",
        lgbm=_FakeLgbm(),
        nwp_anchor=anchor,
        tau=0.5,
        mode="linear",
        support_by_date=support_by_date,
        predict_fn=predict_fn,
    )
    return out, dists, pred_map, rows


def test_schema_columns_and_dtypes_match_contract():
    out, dists, _, rows = _build()
    assert tuple(out.columns) == RAW_PANEL_COLUMNS
    assert dict(out.schema) == dict(RAW_PANEL_SCHEMA)
    assert out.height == len(rows)
    assert len(dists) == out.height


def test_prob_dists_are_normalised_dicts():
    _, dists, _, _ = _build()
    for d in dists:
        assert isinstance(d, dict)
        assert all(isinstance(k, int) for k in d)
        assert abs(sum(d.values()) - 1.0) < 1e-9


def test_bracket_correct_matches_Q_of_pred():
    out, _, pred_map, rows = _build()
    bc = out["bracket_correct"].to_list()
    yt = out["y_true_int"].to_list()
    yp = out["y_pred_dec"].to_list()
    for i in range(len(rows)):
        assert bc[i] in (0, 1)
        assert bc[i] == int(Q(float(yp[i])) == int(yt[i]))
    # Day1 22:00 predicts 100.0 but truth is 12 -> must be incorrect.
    assert bc[2] == 0
    # Day1 20:00 predicts 10.0, truth 10 -> correct.
    assert bc[0] == 1


def test_p50_var_is_causal_and_excludes_later_cps():
    out, _, _, _ = _build()
    p50 = out["p50_var"].to_list()
    # row0 Day1 20:00: first CP -> NULL
    assert p50[0] is None
    # row1 Day1 21:00: only 1 earlier CP -> NULL
    assert p50[1] is None
    # row2 Day1 22:00: earlier CPs are 10.0 and 12.0 -> var = 1.0.
    # The CURRENT row's 100.0 is excluded; if wrongly included var would explode.
    assert p50[2] is not None
    assert p50[2] >= 0.0
    assert abs(p50[2] - float(np.var([10.0, 12.0]))) < 1e-9
    assert abs(p50[2] - 1.0) < 1e-9
    # row3 Day2 20:00: first CP -> NULL ; row4 Day2 21:00: 1 earlier -> NULL
    assert p50[3] is None
    assert p50[4] is None


def test_regime_is_all_null():
    out, _, _, _ = _build()
    assert out["regime"].null_count() == out.height


def test_nwp_spread_passthrough_with_null():
    out, _, _, _ = _build()
    spread = out["nwp_spread"].to_list()
    assert spread[0] == 1.2
    assert spread[2] is None  # null spread preserved


def test_month_and_static_columns():
    out, _, _, _ = _build()
    assert out["month"].to_list() == [3, 3, 3, 3, 3]
    assert out["split"].unique().to_list() == ["2024_split"]
    assert out["role"].unique().to_list() == [ROLE_TEST]
