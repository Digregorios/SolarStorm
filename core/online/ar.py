"""AR(7) online residual corrector (Phase 6, REQ-MOD-5 + REQ-OPS-5).

Strictly-past correction of the model's per-CP residual ``r = truth - pred``. The
corrector keeps a rolling buffer of the last ``order`` settled residuals and predicts
the next correction as their mean (AR(7) with equal weights -- a deliberately simple,
leakage-proof default; DM-test in T-6-3 decides if it ships).

CAUSALITY (REQ-MOD-5): a residual is only ever appended AFTER ``truth(date,cp)`` is
known (post-mortem). ``predict_correction`` uses only residuals already in the buffer,
so the correction applied to day D depends solely on residuals from days < D.

PERSISTENCE (REQ-OPS-5): state lives in ``artifacts/state/ar/<date>.json``. Before each
update a backup ``<date>.bak.json`` is written, and a duplicate ``(date_local, cp_utc)``
update is rejected (idempotent, no double-counting).
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


class DuplicateUpdateError(RuntimeError):
    """Raised when an update repeats an already-applied ``(date_local, cp_utc)``."""


@dataclass
class AROnlineCorrector:
    """Equal-weight AR(``order``) corrector over settled residuals."""

    order: int = 7
    enabled: bool = False
    _buffer: deque[float] = field(default_factory=lambda: deque(maxlen=7))
    _applied: set[tuple[str, str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.order < 1:
            raise ValueError(f"order must be >= 1; got {self.order}")
        # Rebind the buffer to the configured maxlen (default_factory fixed it at 7).
        self._buffer = deque(self._buffer, maxlen=self.order)

    def predict_correction(self) -> float:
        """Mean of buffered residuals (0.0 if empty or disabled). Uses only the past."""
        if not self.enabled or not self._buffer:
            return 0.0
        return sum(self._buffer) / len(self._buffer)

    def update(self, *, date_local: str, cp_utc: str, residual: float) -> None:
        """Append a SETTLED residual after post-mortem. Rejects duplicate (date, cp)."""
        key = (date_local, cp_utc)
        if key in self._applied:
            raise DuplicateUpdateError(
                f"duplicate AR update for (date_local={date_local}, cp_utc={cp_utc})"
            )
        self._applied.add(key)
        self._buffer.append(float(residual))

    # --- persistence (REQ-OPS-5) ------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "enabled": self.enabled,
            "buffer": list(self._buffer),
            "applied": sorted([list(k) for k in self._applied]),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AROnlineCorrector":
        c = cls(order=int(d.get("order", 7)), enabled=bool(d.get("enabled", False)))
        c._buffer = deque((float(x) for x in d.get("buffer", [])), maxlen=c.order)
        c._applied = {(k[0], k[1]) for k in d.get("applied", [])}
        return c

    @staticmethod
    def _state_path(state_dir: Path | str, date_local: str) -> Path:
        return Path(state_dir) / f"{date_local}.json"

    @classmethod
    def load(cls, state_dir: Path | str, date_local: str) -> "AROnlineCorrector":
        p = cls._state_path(state_dir, date_local)
        if not p.exists():
            return cls()
        return cls.from_dict(json.loads(p.read_text(encoding="ascii")))

    def save(self, state_dir: Path | str, date_local: str) -> Path:
        """Write state, backing up any existing file to ``<date>.bak.json`` first."""
        p = self._state_path(state_dir, date_local)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            p.with_suffix(".bak.json").write_text(p.read_text(encoding="ascii"), encoding="ascii")
        p.write_text(
            json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, indent=2),
            encoding="ascii",
        )
        return p


__all__ = ["AROnlineCorrector", "DuplicateUpdateError"]
