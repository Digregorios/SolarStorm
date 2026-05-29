"""Structured logging - JSONL events with run_id (REQ-OPS-3).

Schema: ``ts, level, run_id, cp_utc, cp_local, tz_name, component, event, duration_ms,
data_quality, sha256_inputs[]``. Every event is one JSON line. ASCII-only.
"""

from __future__ import annotations

import json
import os
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_DEFAULT_LOG_ROOT = Path(os.environ.get("TMAX_LOG_ROOT", "artifacts/logs"))

_run_id_var: ContextVar[str] = ContextVar("run_id", default="")
_log_path_var: ContextVar[Path | None] = ContextVar("log_path", default=None)


def new_run_id() -> str:
    """Generate a fresh run id and bind it to the contextvar."""
    rid = str(uuid.uuid4())
    _run_id_var.set(rid)
    return rid


def current_run_id() -> str:
    rid = _run_id_var.get()
    if not rid:
        rid = new_run_id()
    return rid


def set_log_path(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    _log_path_var.set(p)


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds")


def log_event(
    component: str,
    event: str,
    *,
    level: str = "INFO",
    cp_utc: datetime | None = None,
    cp_local: datetime | None = None,
    tz_name: str | None = None,
    duration_ms: float | None = None,
    data_quality: dict[str, Any] | None = None,
    sha256_inputs: Iterable[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a JSONL line to the configured log path; return the event dict."""
    payload: dict[str, Any] = {
        "ts": _utcnow_iso(),
        "level": level,
        "run_id": current_run_id(),
        "component": component,
        "event": event,
    }
    if cp_utc is not None:
        payload["cp_utc"] = cp_utc.isoformat()
    if cp_local is not None:
        payload["cp_local"] = cp_local.isoformat()
    if tz_name is not None:
        payload["tz_name"] = tz_name
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 3)
    if data_quality is not None:
        payload["data_quality"] = data_quality
    if sha256_inputs is not None:
        payload["sha256_inputs"] = list(sha256_inputs)
    if extra:
        payload.update(extra)
    path = _log_path_var.get()
    if path is None:
        path = _DEFAULT_LOG_ROOT / f"{current_run_id()}.jsonl"
        set_log_path(path)
    line = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    with open(path, "a", encoding="ascii") as fh:
        fh.write(line + "\n")
    return payload


__all__ = [
    "new_run_id",
    "current_run_id",
    "set_log_path",
    "log_event",
]
