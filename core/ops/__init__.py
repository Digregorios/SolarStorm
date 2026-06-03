"""Shadow Ops Platform (Phase 5.1).

Runs the forecast pipeline daily in shadow mode (no real trading) and logs
structured telemetry for readiness evaluation.
"""

from core.ops.schemas import (
    REQUIRED_FORECAST_FIELDS,
    ShadowForecastRecord,
    validate_record,
)
from core.ops.shadow_runner import (
    ShadowRunner,
    ShadowRunnerConfig,
    ShadowRunResult,
)

__all__ = [
    "REQUIRED_FORECAST_FIELDS",
    "ShadowForecastRecord",
    "validate_record",
    "ShadowRunner",
    "ShadowRunnerConfig",
    "ShadowRunResult",
]
