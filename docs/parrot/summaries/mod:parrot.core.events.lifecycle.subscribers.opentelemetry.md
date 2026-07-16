---
type: Wiki Summary
title: parrot.core.events.lifecycle.subscribers.opentelemetry
id: mod:parrot.core.events.lifecycle.subscribers.opentelemetry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OpenTelemetrySubscriber — maps LifecycleEvents to OTel spans.
relates_to:
- concept: class:parrot.core.events.lifecycle.subscribers.opentelemetry.OpenTelemetrySubscriber
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
---

# `parrot.core.events.lifecycle.subscribers.opentelemetry`

OpenTelemetrySubscriber — maps LifecycleEvents to OTel spans.

FEAT-176 — Lifecycle Events System.

Maps ``Before*`` / ``After*`` / ``*Failed`` lifecycle events to OpenTelemetry
spans using the W3C ``TraceContext`` carried on every event.  Requires the
``otel`` extra::

    pip install 'ai-parrot[otel]'

The subscriber is lazy about OTel imports: ``import`` at module top-level is
safe; the OTel SDK is only loaded inside the constructor and callbacks.  If
the extra is not installed, constructing the subscriber raises ``ImportError``
with a clear action message.

## Classes

- **`OpenTelemetrySubscriber`** — EventProvider that maps lifecycle events to OpenTelemetry spans.
