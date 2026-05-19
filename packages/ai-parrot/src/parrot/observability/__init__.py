"""parrot.observability — OpenTelemetry + Cost Observability for AI-Parrot.

FEAT-177. Provides a one-call boot helper ``setup_telemetry(ObservabilityConfig)``
that wires GenAI SemConv-compliant spans, OTel metrics (counters/histograms),
and USD cost tracking against FEAT-176's lifecycle events.

Public surface (grows as subsequent FEAT-177 tasks land):
  * ``ObservabilityConfig`` — Pydantic v2 config model (TASK-1228).
  * ``setup_telemetry`` / ``shutdown_telemetry`` — boot helpers (TASK-1235).
  * ``GenAIOpenTelemetrySubscriber`` — rich span subscriber (TASK-1230).
  * ``MetricsSubscriber`` — counters + histograms subscriber (TASK-1231).
  * ``CostCalculator`` — USD cost calculator (TASK-1232).
  * ``ParrotTelemetryProvider`` — EventProvider bundle (TASK-1233).
"""

from parrot.observability.config import ObservabilityConfig
from parrot.observability.provider import ParrotTelemetryProvider

__all__: list[str] = [
    "ObservabilityConfig",
    "ParrotTelemetryProvider",
]

# Deferred re-exports — added as each task lands:
# from parrot.observability.setup import setup_telemetry, shutdown_telemetry
# from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber
# from parrot.observability.subscribers.metrics import MetricsSubscriber
# from parrot.observability.cost.calculator import CostCalculator
