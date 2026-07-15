---
type: Wiki Summary
title: parrot.observability.provider
id: mod:parrot.observability.provider
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ParrotTelemetryProvider — EventProvider bundle for parrot.observability.
relates_to:
- concept: class:parrot.observability.provider.ParrotTelemetryProvider
  rel: defines
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
- concept: mod:parrot.observability.subscribers.metrics
  rel: references
- concept: mod:parrot.observability.subscribers.trace
  rel: references
---

# `parrot.observability.provider`

ParrotTelemetryProvider — EventProvider bundle for parrot.observability.

FEAT-177 TASK-1233.

Implements FEAT-176's ``EventProvider`` Protocol. Bundles the trace and metrics
subscribers into a single object so ``setup_telemetry`` can register them with
``get_global_registry().add_provider(ParrotTelemetryProvider(...))`` via one call.

``CostCalculator`` is NOT a subscriber — it is injected into the two subscribers
at construction time; ``register()`` is never called on it.

Spec §3 Module 6, §2 Component Diagram.

## Classes

- **`ParrotTelemetryProvider`** — Bundles trace + metrics subscribers for one-call registration.
