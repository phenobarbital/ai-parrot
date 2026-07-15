---
type: Wiki Summary
title: parrot.core.events.lifecycle.subscribers
id: mod:parrot.core.events.lifecycle.subscribers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Built-in lifecycle event subscribers.
relates_to:
- concept: mod:parrot.core.events.lifecycle.subscribers.logging
  rel: references
- concept: mod:parrot.core.events.lifecycle.subscribers.webhook
  rel: references
---

# `parrot.core.events.lifecycle.subscribers`

Built-in lifecycle event subscribers.

FEAT-176 — Lifecycle Events System.

Available subscribers:

- :class:`~parrot.core.events.lifecycle.subscribers.logging.LoggingSubscriber`
  — logs every lifecycle event via the standard logging framework.
- :class:`~parrot.core.events.lifecycle.subscribers.otel.OpenTelemetrySubscriber`
  — maps lifecycle events to OpenTelemetry spans (requires ``otel`` extra).
- :class:`~parrot.core.events.lifecycle.subscribers.webhook.WebhookSubscriber`
  — HTTP POSTs event payloads to a configured endpoint.
