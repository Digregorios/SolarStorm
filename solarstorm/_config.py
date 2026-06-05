"""Centralised constants: contractual checkpoints, station identity, seed."""
from __future__ import annotations

# --- Contractual (exception to P2: zero hardcoded meteorological) ---
ICAO = "NZWN"
TZ_NAME = "Pacific/Auckland"
CP_SET_UTC: tuple[str, ...] = ("20:00", "21:00", "22:00", "23:00")
CP_OPERATIONAL: str = "23:00"

# --- Settlement ---
TMP_C_INT_PLAUSIBILITY: tuple[int, int] = (-10, 40)
DWP_C_INT_PLAUSIBILITY: tuple[int, int] = (-50, 35)

# --- Reproducibility ---
SEED: int = 42
