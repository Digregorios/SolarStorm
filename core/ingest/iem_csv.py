"""IEM ASOS CSV parser (REQ-CON-3, REQ-CON-8, design 4.1.2).

The IEM CSV exposes:

- ``valid``: tz-naive UTC string (treated as UTC).
- ``tmpf`` decimal Fahrenheit (informative only - never feeds ``T_obs_int``).
- ``metar`` raw text - source of integer degC truth via regex.

This module produces the canonical observations frame plus parsing telemetry
required by REQ-CON-8 (fallback rate, plausibility filter).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import polars as pl

from core.io.timeutil import utc_naive_to_aware  # noqa: F401  (kept for reference)

# Regex: " TT/DD " surrounded by whitespace; M-prefix means negative; 1-2 digits each.
_METAR_TT_DD = re.compile(r"\s(M?\d{1,2})/(M?\d{1,2})\s")

# Plausibility window (NZWN); REQ-CON-8 + station.yaml. Hard-coded here as defaults; the
# dataset builder may pass custom bounds via ``parse_observations``.
_DEFAULT_TMP_MIN_C = -10
_DEFAULT_TMP_MAX_C = 40

# IEM missing marker.
_MISSING = {"M", "", "MM"}


@dataclass(frozen=True)
class ParseStats:
    """Telemetry from the parser used by REQ-CON-8 reports."""

    n_total: int
    n_metar_present: int
    n_metar_blank: int
    n_parsed_ok: int
    n_parsed_imputed: int       # fallback from tmpf (REQ-CON-8)
    n_parsed_missing: int        # regex failed or implausible
    n_implausible: int           # parsed but outside [min, max]

    @property
    def fallback_rate(self) -> float:
        return 0.0 if self.n_total == 0 else self.n_parsed_imputed / self.n_total

    @property
    def missing_rate(self) -> float:
        return 0.0 if self.n_total == 0 else self.n_parsed_missing / self.n_total

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n_total": self.n_total,
            "n_metar_present": self.n_metar_present,
            "n_metar_blank": self.n_metar_blank,
            "n_parsed_ok": self.n_parsed_ok,
            "n_parsed_imputed": self.n_parsed_imputed,
            "n_parsed_missing": self.n_parsed_missing,
            "n_implausible": self.n_implausible,
            "fallback_rate": self.fallback_rate,
            "missing_rate": self.missing_rate,
        }


def _parse_signed(token: str) -> int | None:
    """Parse a METAR temperature token: ``'19'`` -> 19, ``'M02'`` -> -2."""
    if token is None:
        return None
    sign = -1 if token.startswith("M") else 1
    digits = token.lstrip("M")
    if not digits.isdigit() or len(digits) > 2:
        return None
    return sign * int(digits)


def parse_tmp_c_int_from_row(
    metar_raw: str | None,
    tmpf: float | None,
    *,
    tmp_min_c: int = _DEFAULT_TMP_MIN_C,
    tmp_max_c: int = _DEFAULT_TMP_MAX_C,
) -> tuple[int | None, int | None, str, bool]:
    """Return ``(tmp_c_int, dwp_c_int, data_quality, implausible)`` per design 4.1.2.

    Quality flags: ``'ok'`` | ``'imputed'`` | ``'missing'``.
    ``implausible`` is True iff the regex matched but the value fell outside the
    plausibility window ``[tmp_min_c, tmp_max_c]`` (review #11 - avoids running the
    regex a second time downstream).
    """
    if metar_raw is None or str(metar_raw).strip() == "" or str(metar_raw).strip() in _MISSING:
        if tmpf is not None and not (isinstance(tmpf, float) and math.isnan(tmpf)):
            tmp_c = round((tmpf - 32.0) * 5.0 / 9.0)
            if tmp_min_c <= tmp_c <= tmp_max_c:
                return int(tmp_c), None, "imputed", False
        return None, None, "missing", False

    m = _METAR_TT_DD.search(metar_raw)
    if not m:
        return None, None, "missing", False

    tt = _parse_signed(m.group(1))
    dd = _parse_signed(m.group(2))
    if tt is None:
        return None, None, "missing", False
    if not (tmp_min_c <= tt <= tmp_max_c):
        return None, None, "missing", True
    return tt, dd, "ok", False


def read_iem_csv(path: str | Path) -> pl.DataFrame:
    """Load the raw IEM CSV with the documented schema. ``valid`` becomes UTC-aware."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    df = pl.read_csv(
        p,
        null_values=list(_MISSING),
        try_parse_dates=False,
        infer_schema_length=10_000,
    )
    if "valid" not in df.columns:
        raise ValueError("Expected 'valid' column in IEM CSV.")
    df = df.with_columns(
        pl.col("valid")
        .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M", strict=True)
        .dt.replace_time_zone("UTC")
        .alias("ts_utc"),
    )
    return df


def parse_observations(
    df: pl.DataFrame,
    *,
    tmp_min_c: int = _DEFAULT_TMP_MIN_C,
    tmp_max_c: int = _DEFAULT_TMP_MAX_C,
) -> tuple[pl.DataFrame, ParseStats]:
    """Compute ``tmp_c_int``, ``dwp_c_int`` and ``data_quality`` (REQ-CON-3/8).

    Returns a tuple of the augmented frame and parsing telemetry.
    """
    if "metar" not in df.columns:
        raise ValueError("Expected 'metar' column.")
    metar = df.get_column("metar").to_list()
    tmpf = df.get_column("tmpf").to_list() if "tmpf" in df.columns else [None] * df.height

    tmp_int: list[int | None] = []
    dwp_int: list[int | None] = []
    quality: list[str] = []

    n_metar_present = 0
    n_metar_blank = 0
    n_ok = n_imp = n_miss = n_impl = 0

    for raw_metar, raw_tmpf in zip(metar, tmpf, strict=True):
        if raw_metar is None or str(raw_metar).strip() == "":
            n_metar_blank += 1
        else:
            n_metar_present += 1
        t, d, q, implausible = parse_tmp_c_int_from_row(
            raw_metar, raw_tmpf, tmp_min_c=tmp_min_c, tmp_max_c=tmp_max_c
        )
        if implausible:
            n_impl += 1
        if q == "ok":
            n_ok += 1
        elif q == "imputed":
            n_imp += 1
        else:
            n_miss += 1
        tmp_int.append(t)
        dwp_int.append(d)
        quality.append(q)

    out = df.with_columns(
        [
            pl.Series("tmp_c_int", tmp_int, dtype=pl.Int32),
            pl.Series("dwp_c_int", dwp_int, dtype=pl.Int32),
            pl.Series("dq_tmp_c_int", quality, dtype=pl.Utf8),
        ]
    )
    stats = ParseStats(
        n_total=df.height,
        n_metar_present=n_metar_present,
        n_metar_blank=n_metar_blank,
        n_parsed_ok=n_ok,
        n_parsed_imputed=n_imp,
        n_parsed_missing=n_miss,
        n_implausible=n_impl,
    )
    return out, stats


def load_observations(
    path: str | Path,
    *,
    tmp_min_c: int = _DEFAULT_TMP_MIN_C,
    tmp_max_c: int = _DEFAULT_TMP_MAX_C,
) -> tuple[pl.DataFrame, ParseStats]:
    """One-shot helper combining ``read_iem_csv`` and ``parse_observations``."""
    raw = read_iem_csv(path)
    return parse_observations(raw, tmp_min_c=tmp_min_c, tmp_max_c=tmp_max_c)


__all__ = [
    "ParseStats",
    "parse_tmp_c_int_from_row",
    "read_iem_csv",
    "parse_observations",
    "load_observations",
]
