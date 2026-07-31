"""ParrotTelemetryProvider — EventProvider bundle for parrot.observability.

FEAT-177 TASK-1233.

Implements FEAT-176's ``EventProvider`` Protocol. Bundles the trace and metrics
subscribers into a single object so ``setup_telemetry`` can register them with
``get_global_registry().add_provider(ParrotTelemetryProvider(...))`` via one call.

``CostCalculator`` is NOT a subscriber — it is injected into the two subscribers
at construction time; ``register()`` is never called on it.

Spec §3 Module 6, §2 Component Diagram.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from parrot.observability.subscribers.metrics import MetricsSubscriber
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber

if TYPE_CHECKING:
    from parrot.core.events.lifecycle import EventRegistry


class ParrotTelemetryProvider:
    """Bundles trace + metrics subscribers for one-call registration.

    Either subscriber may be ``None`` (e.g., trace-only or metrics-only
    deployments). If both are ``None``, ``register`` is a no-op.

    Implements the ``EventProvider`` Protocol (``provider.py:45``): the
    ``register`` method is synchronous.

    Args:
        trace_subscriber: Optional ``GenAIOpenTelemetrySubscriber``.
        metrics_subscriber: Optional ``MetricsSubscriber``.
    """

    def __init__(
        self,
        *,
        trace_subscriber: Optional[GenAIOpenTelemetrySubscriber] = None,
        metrics_subscriber: Optional[MetricsSubscriber] = None,
    ) -> None:
        self._trace = trace_subscriber
        self._metrics = metrics_subscriber

    def register(self, registry: "EventRegistry") -> None:
        """Register all non-None subscribers with *registry*.

        Args:
            registry: The ``EventRegistry`` to subscribe to. Call must be
                synchronous per ``EventProvider`` Protocol (provider.py:45).
        """
        if self._trace is not None:
            self._trace.register(registry)
        if self._metrics is not None:
            self._metrics.register(registry)
