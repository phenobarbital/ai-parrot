"""parrot.observability — OpenTelemetry + Cost Observability for AI-Parrot.

FEAT-177. Provides a one-call boot helper ``setup_telemetry(ObservabilityConfig)``
that wires GenAI SemConv-compliant spans, OTel metrics (counters/histograms),
and USD cost tracking against FEAT-176's lifecycle events.

Public surface:
  * ``ObservabilityConfig`` — Pydantic v2 config model (TASK-1228).
  * ``setup_telemetry`` / ``shutdown_telemetry`` — boot helpers (TASK-1235).
  * ``ParrotTelemetryProvider`` — EventProvider bundle (TASK-1233).
  * ``ConfigurationError`` — raised on bad/conflicting config (TASK-1235).
  * ``GenAIOpenTelemetrySubscriber`` — rich span subscriber (TASK-1230).
  * ``MetricsSubscriber`` — counters + histograms subscriber (TASK-1231).
  * ``CostCalculator`` — USD cost calculator (TASK-1232).

Pluggable usage-logging layer (no OpenTelemetry SDK required for the logging
path):
  * ``AbstractLogger`` — the pluggable recorder interface.
  * ``UsageRecord`` — normalized, PII-free per-call record.
  * ``LoggingUsageRecorder`` — zero-infra structured-log backend.
  * ``UsageRecordingSubscriber`` — builds records + fans out to recorders.
  * ``ensure_observability_bootstrapped`` / ``shutdown_usage_recording`` —
    env-driven auto-boot helpers.
  * ``shutdown_observability`` — aggregate flush/teardown for any active backend
    (registered automatically via ``atexit`` on first boot).
"""

from parrot.observability.bootstrap import (
    ensure_observability_bootstrapped,
    shutdown_observability,
    shutdown_usage_recording,
)
from parrot.observability.config import ObservabilityConfig
from parrot.observability.cost.calculator import CostCalculator
from parrot.observability.errors import ConfigurationError
from parrot.observability.provider import ParrotTelemetryProvider
from parrot.observability.recorders import (
    AbstractLogger,
    LoggingUsageRecorder,
    UsageRecord,
    UsageRecordingSubscriber,
)
from parrot.observability.setup import setup_telemetry, shutdown_telemetry
from parrot.observability.subscribers.metrics import MetricsSubscriber
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber

__all__: list[str] = [
    "ObservabilityConfig",
    "ConfigurationError",
    "ParrotTelemetryProvider",
    "setup_telemetry",
    "shutdown_telemetry",
    "GenAIOpenTelemetrySubscriber",
    "MetricsSubscriber",
    "CostCalculator",
    "AbstractLogger",
    "UsageRecord",
    "LoggingUsageRecorder",
    "UsageRecordingSubscriber",
    "ensure_observability_bootstrapped",
    "shutdown_usage_recording",
    "shutdown_observability",
]
