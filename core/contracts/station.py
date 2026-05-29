"""Station config loader (REQ-CON-6).

Validates ``nzwn/config/station.yaml`` and rejects CPs that are not at integer UTC hours.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TmpcIntPlausibility(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: int
    max: int

    @field_validator("max")
    @classmethod
    def _max_gt_min(cls, v: int, info: object) -> int:  # type: ignore[override]
        # info.data has min already
        data = getattr(info, "data", {})
        if "min" in data and v <= data["min"]:
            raise ValueError("max must be > min")
        return v


class DayCompleteRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_obs: int = Field(ge=1)
    max_gap_minutes: int = Field(ge=1)
    min_quartile_coverage: int = Field(ge=1, le=4)


class StationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    icao: str
    name: str
    country: str
    lat: float
    lon: float
    elevation_m: float
    tz: str
    cp_set_utc: List[str]
    cp_operational_utc: str
    tmp_c_int_plausibility: TmpcIntPlausibility
    day_complete: DayCompleteRule

    @field_validator("cp_set_utc")
    @classmethod
    def _validate_cp_set(cls, v: List[str]) -> List[str]:
        for cp in v:
            _validate_hh_mm_zero(cp)
        if len(v) != len(set(v)):
            raise ValueError("cp_set_utc contains duplicates")
        return v

    @field_validator("cp_operational_utc")
    @classmethod
    def _validate_cp_op(cls, v: str) -> str:
        _validate_hh_mm_zero(v)
        return v


def _validate_hh_mm_zero(cp: str) -> None:
    if len(cp) != 5 or cp[2] != ":":
        raise ValueError(f"CP '{cp}' must be 'HH:MM' (REQ-CON-6).")
    hh = int(cp[:2])
    mm = int(cp[3:])
    if mm != 0:
        raise ValueError(f"CP '{cp}' must be on integer hour (REQ-CON-6).")
    if not 0 <= hh <= 23:
        raise ValueError(f"CP '{cp}' hour out of range.")


def load_station_config(path: str | Path = "nzwn/config/station.yaml") -> StationConfig:
    """Load and validate the station YAML."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Station config not found: {p}")
    with open(p, encoding="ascii") as fh:
        raw = yaml.safe_load(fh)
    return StationConfig.model_validate(raw)


__all__ = ["StationConfig", "load_station_config"]
