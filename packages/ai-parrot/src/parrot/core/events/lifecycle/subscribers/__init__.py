"""Built-in lifecycle event subscribers.

FEAT-176 — Lifecycle Events System.

Available subscribers:

- :class:`~parrot.core.events.lifecycle.subscribers.logging.LoggingSubscriber`
  — logs every lifecycle event via the standard logging framework.
- :class:`~parrot.core.events.lifecycle.subscribers.otel.OpenTelemetrySubscriber`
  — maps lifecycle events to OpenTelemetry spans (requires ``otel`` extra).
- :class:`~parrot.core.events.lifecycle.subscribers.webhook.WebhookSubscriber`
  — HTTP POSTs event payloads to a configured endpoint.
"""

from parrot.core.events.lifecycle.subscribers.logging import LoggingSubscriber

__all__ = [
    "LoggingSubscriber",
]
