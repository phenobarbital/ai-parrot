"""Pluggable usage/token/cost recording backends.

A single ``AbstractLogger`` interface fronts every backend (logging, Prometheus,
…). ``UsageRecordingSubscriber`` builds one ``UsageRecord`` per LLM call from the
FEAT-176 lifecycle events (reusing the shared ``CostCalculator``) and fans it out
to the configured recorders. Backend selection is driven by
``ObservabilityConfig.usage_backend``.

The logging path imports NO OpenTelemetry SDK and adds no third-party
dependency. ``PrometheusUsageRecorder`` lazily imports ``prometheus_client``.
"""

from __future__ import annotations

from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.factory import build_recorders_from_config
from parrot.observability.recorders.logging_recorder import LoggingUsageRecorder
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber

__all__ = [
    "AbstractLogger",
    "UsageRecord",
    "LoggingUsageRecorder",
    "UsageRecordingSubscriber",
    "build_recorders_from_config",
]
