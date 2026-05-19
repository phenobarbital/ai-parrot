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
"""

from parrot.observability.config import ObservabilityConfig
from parrot.observability.errors import ConfigurationError
from parrot.observability.provider import ParrotTelemetryProvider
from parrot.observability.setup import setup_telemetry, shutdown_telemetry

__all__: list[str] = [
    "ObservabilityConfig",
    "ConfigurationError",
    "ParrotTelemetryProvider",
    "setup_telemetry",
    "shutdown_telemetry",
]
