---
type: Wiki Summary
title: parrot.observability.subscribers.trace
id: mod:parrot.observability.subscribers.trace
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: GenAIOpenTelemetrySubscriber — rich GenAI SemConv span subscriber.
relates_to:
- concept: class:parrot.observability.subscribers.trace.GenAIOpenTelemetrySubscriber
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
- concept: mod:parrot.observability.attributes
  rel: references
- concept: mod:parrot.observability.cost.calculator
  rel: references
---

# `parrot.observability.subscribers.trace`

GenAIOpenTelemetrySubscriber — rich GenAI SemConv span subscriber.

FEAT-177 TASK-1230. Maps 12 of FEAT-176's lifecycle events to OTel spans with
full GenAI Semantic Conventions attributes. Coexists with FEAT-176's stub
``OpenTelemetrySubscriber`` via a distinct class name.

Design points:
- Each span is keyed by ``event.trace_context.span_id`` in ``_active_spans``.
- ``asyncio.Lock`` guards concurrent access to ``_active_spans``.
- ``MessageAddedEvent`` and ``AgentStatusChangedEvent`` attach *span events*
  (not spans) to the currently-active span.
- ``ClientStreamChunkEvent`` is a no-op unless ``capture_completions=True``.
- Never import ``opentelemetry`` at module top-level — lazy import on
  construction so users without the SDK are not forced to install it.

## Classes

- **`GenAIOpenTelemetrySubscriber`** — Rich OTel span subscriber implementing GenAI Semantic Conventions.
