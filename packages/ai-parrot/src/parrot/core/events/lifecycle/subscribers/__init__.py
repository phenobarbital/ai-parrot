"""Built-in lifecycle event subscribers.

FEAT-176 — Lifecycle Events System.

FEAT-317: ``LoggingSubscriber`` and ``WebhookSubscriber`` moved to
``navigator_eventbus.lifecycle.subscribers`` (FEAT-313).
``OpenTelemetrySubscriber`` stays local — it depends on ai-parrot's typed
lifecycle events.

Available subscribers:

- :class:`~navigator_eventbus.lifecycle.subscribers.logging.LoggingSubscriber`
  — logs every lifecycle event via the standard logging framework.
- :class:`~parrot.core.events.lifecycle.subscribers.opentelemetry.OpenTelemetrySubscriber`
  — maps lifecycle events to OpenTelemetry spans (requires ``otel`` extra).
- :class:`~navigator_eventbus.lifecycle.subscribers.webhook.WebhookSubscriber`
  — HTTP POSTs event payloads to a configured endpoint.
"""

from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber
from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber

__all__ = [
    "LoggingSubscriber",
    "WebhookSubscriber",
]
