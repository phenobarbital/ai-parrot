"""MetricsSubscriber — in-process bus counters + latency buckets (FEAT-310).

Module 10 (spec §3, Phase 3). Counts delivered envelopes per topic-class
and per severity, counts handler failures (observed via
``bus.subscriber_error`` meta-events), and records dispatch latency
(envelope creation/enqueue → handler start, wall clock) in fixed histogram
buckets.

The contract is :meth:`snapshot` returning a plain dict — no Prometheus/
OTel exporter exists for the bus yet (the observability package's
``MetricsSubscriber`` is lifecycle-registry-specific); exporting is future
work by design (task contract).

Histogram bucket boundaries (fixed, documented):
``[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]`` seconds, plus a
``+Inf`` overflow bucket. Bus dispatch is queue-bound, so buckets are
tighter than the LLM-tuned observability defaults.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from navconfig.logging import logging

from parrot.core.events.bus.core import BusCore
from parrot.core.events.bus.envelope import EventEnvelope

#: Fixed latency bucket upper bounds in seconds (+Inf implicit).
LATENCY_BUCKETS: tuple[float, ...] = (
    0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0,
)


class MetricsSubscriber:
    """In-process bus metrics: counters + dispatch-latency histogram.

    Attach with :meth:`attach`; read with :meth:`snapshot`. All state is
    in-process and monotonic-increasing until :meth:`reset`.
    """

    def __init__(self) -> None:
        self._delivered_by_class: Counter[str] = Counter()
        self._delivered_by_severity: Counter[str] = Counter()
        self._failed_by_class: Counter[str] = Counter()
        self._latency_buckets: Counter[str] = Counter()
        self._latency_count = 0
        self._latency_sum = 0.0
        self._latency_max = 0.0
        self._subscription_ids: list[str] = []
        self.logger = logging.getLogger(
            "parrot.core.events.bus.subscribers.metrics"
        )

    # ------------------------------------------------------------------
    # Bus wiring
    # ------------------------------------------------------------------

    def attach(self, bus: BusCore) -> list[str]:
        """Subscribe the metric handlers on *bus*.

        Registers a wildcard delivery observer plus a
        ``bus.subscriber_error`` failure observer.

        Args:
            bus: The BusCore to instrument.

        Returns:
            The subscriber ids created.
        """
        self._subscription_ids = [
            bus.subscribe("*", self._on_envelope),
            bus.subscribe("bus.subscriber_error", self._on_subscriber_error),
        ]
        return list(self._subscription_ids)

    def detach(self, bus: BusCore) -> int:
        """Remove this subscriber's registrations from *bus*."""
        removed = sum(
            1 for sid in self._subscription_ids if bus.unsubscribe(sid)
        )
        self._subscription_ids = []
        return removed

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _on_envelope(self, envelope: EventEnvelope) -> None:
        """Count one delivery and record its dispatch latency."""
        try:
            if envelope.topic == "bus.subscriber_error":
                return  # counted by the failure observer instead
            topic_class = envelope.topic.split(".", 1)[0]
            self._delivered_by_class[topic_class] += 1
            self._delivered_by_severity[envelope.severity.name] += 1
            self._observe_latency(envelope)
        except Exception:  # noqa: BLE001 — metrics must never disturb dispatch
            self.logger.exception("Metrics update failed for %s", envelope.topic)

    async def _on_subscriber_error(self, envelope: EventEnvelope) -> None:
        """Count one handler failure (from the bus meta-event)."""
        try:
            original = envelope.payload.get("original_topic", "unknown")
            self._failed_by_class[original.split(".", 1)[0]] += 1
        except Exception:  # noqa: BLE001
            self.logger.exception("Failure-metric update failed")

    def _observe_latency(self, envelope: EventEnvelope) -> None:
        """Record enqueue→handler-start latency into the fixed buckets.

        Latency is measured as wall-clock ``now - envelope.timestamp``
        (envelope creation happens at enqueue time on the emitter side).
        """
        now = datetime.now(timezone.utc)
        latency = max((now - envelope.timestamp).total_seconds(), 0.0)
        self._latency_count += 1
        self._latency_sum += latency
        self._latency_max = max(self._latency_max, latency)
        for bound in LATENCY_BUCKETS:
            if latency <= bound:
                self._latency_buckets[f"le_{bound}"] += 1
                return
        self._latency_buckets["le_inf"] += 1

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a point-in-time metrics report.

        Returns:
            Dict with ``delivered`` (per topic-class), ``by_severity``,
            ``failed`` (per topic-class) and ``latency``
            (buckets/count/sum/avg/max in seconds).
        """
        avg = (
            self._latency_sum / self._latency_count
            if self._latency_count
            else 0.0
        )
        return {
            "delivered": dict(self._delivered_by_class),
            "by_severity": dict(self._delivered_by_severity),
            "failed": dict(self._failed_by_class),
            "latency": {
                "buckets": dict(self._latency_buckets),
                "bucket_bounds_seconds": list(LATENCY_BUCKETS),
                "count": self._latency_count,
                "sum_seconds": self._latency_sum,
                "avg_seconds": avg,
                "max_seconds": self._latency_max,
            },
        }

    def reset(self) -> None:
        """Zero every counter and histogram."""
        self._delivered_by_class.clear()
        self._delivered_by_severity.clear()
        self._failed_by_class.clear()
        self._latency_buckets.clear()
        self._latency_count = 0
        self._latency_sum = 0.0
        self._latency_max = 0.0


__all__ = ("LATENCY_BUCKETS", "MetricsSubscriber")
