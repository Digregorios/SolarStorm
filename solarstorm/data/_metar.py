"""METAR integer-truth parser — regex on raw text, not tmpf rounding.

The regex extracts the TT/DD temperature/dewpoint group from raw METAR text.
This is critical for Polymarket settlement: the contract settles on the integer
degree reported in the METAR, not on a decimal conversion of tmpf.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_METAR_TT_DD = re.compile(r"\s(M?\d{1,2})/(M?\d{1,2})(?=\s|$)")


@dataclass
class ParseStats:
    n_total: int = 0
    n_metar_present: int = 0
    n_metar_blank: int = 0
    n_parsed_ok: int = 0
    n_parsed_imputed: int = 0
    n_parsed_missing: int = 0
    n_implausible: int = 0

    @property
    def fallback_rate(self) -> float:
        denom = self.n_parsed_ok + self.n_parsed_imputed
        return self.n_parsed_imputed / denom if denom > 0 else 0.0

    @property
    def missing_rate(self) -> float:
        return self.n_parsed_missing / self.n_total if self.n_total > 0 else 0.0


def _parse_signed(raw: str) -> int:
    """Parse 'M05' → -5, '18' → 18."""
    if raw.startswith("M"):
        return -int(raw[1:])
    return int(raw)


def parse_tmp_c_int_from_row(
    metar_raw: str | None,
    tmpf: float | None,
    *,
    tmp_min_c: int = -10,
    tmp_max_c: int = 40,
) -> tuple[int | None, int | None, str, bool]:
    """Parse integer degC temperature and dewpoint from a raw METAR string.

    Returns (tt, dwp, quality, implausible) where quality ∈ {"ok","imputed","missing"}.
    """
    if not metar_raw or metar_raw.strip() in ("", "M", "MM"):
        if tmpf is not None:
            tt = round((tmpf - 32.0) * 5.0 / 9.0)
            return tt, None, "imputed", False
        return None, None, "missing", False

    m = _METAR_TT_DD.search(metar_raw)
    if not m:
        if tmpf is not None:
            tt = round((tmpf - 32.0) * 5.0 / 9.0)
            return tt, None, "imputed", False
        return None, None, "missing", False

    tt = _parse_signed(m.group(1))
    dwp = _parse_signed(m.group(2))

    if tt < tmp_min_c or tt > tmp_max_c:
        return None, None, "missing", True

    return tt, dwp, "ok", False


def parse_dwp_c_int_from_row(
    metar_raw: str | None, dwpf: float | None = None
) -> tuple[int | None, str]:
    """Extract just the dewpoint integer from raw METAR.

    Reuses the existing TT/DD regex via ``parse_tmp_c_int_from_row``.
    The ``dwpf`` parameter is accepted for signature compatibility; dewpoint
    is always sourced from the METAR text itself.
    """
    _, dwp, dq, _ = parse_tmp_c_int_from_row(metar_raw, None)
    return dwp, dq
