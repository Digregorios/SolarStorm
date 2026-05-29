"""METAR parser tests (REQ-CON-3, REQ-CON-8, review #11)."""

from __future__ import annotations

from core.ingest.iem_csv import parse_tmp_c_int_from_row


def test_positive_two_digit():
    t, d, q, impl = parse_tmp_c_int_from_row(
        "NZWN 010000Z AUTO 01023KT 9999 BKN018/// 19/14 Q1015 NOSIG", 66.2
    )
    assert t == 19
    assert d == 14
    assert q == "ok"
    assert impl is False


def test_negative_temperature_M02():
    t, _, q, impl = parse_tmp_c_int_from_row("NZAA 010000Z M02/M05 Q1020", None)
    assert t == -2
    assert q == "ok"
    assert impl is False


def test_metar_blank_uses_tmpf_fallback():
    t, d, q, impl = parse_tmp_c_int_from_row("", 64.4)
    assert t == 18
    assert d is None
    assert q == "imputed"
    assert impl is False


def test_metar_missing_marker_uses_fallback():
    t, _, q, impl = parse_tmp_c_int_from_row("M", 50.0)
    assert q == "imputed"
    assert t == round((50.0 - 32) * 5 / 9)
    assert impl is False


def test_metar_legible_no_group_returns_missing():
    t, d, q, impl = parse_tmp_c_int_from_row("NZWN 010000Z AUTO 01023KT NOSIG", 66.2)
    assert t is None and d is None and q == "missing"
    assert impl is False


def test_implausible_value_marked_missing_and_implausible():
    """Review #11: regex matched but value out of [tmp_min, tmp_max] -> implausible=True."""
    t, _, q, impl = parse_tmp_c_int_from_row("NZAA 010000Z 99/14 Q1010", None)
    assert t is None
    assert q == "missing"
    assert impl is True


def test_nan_tmpf_with_missing_metar():
    t, _, q, impl = parse_tmp_c_int_from_row("", float("nan"))
    assert t is None and q == "missing"
    assert impl is False
