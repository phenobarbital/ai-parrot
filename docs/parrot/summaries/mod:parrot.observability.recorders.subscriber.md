---
type: Wiki Summary
title: parrot.observability.recorders.subscriber
id: mod:parrot.observability.recorders.subscriber
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: UsageRecordingSubscriber — turns LLM-call events into UsageRecords + fan-out.
relates_to:
- concept: class:parrot.observability.recorders.subscriber.UsageRecordingSubscriber
  rel: defines
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
- concept: mod:parrot.observability.attributes
  rel: references
- concept: mod:parrot.observability.cost.calculator
  rel: references
- concept: mod:parrot.observability.recorders.base
  rel: references
- concept: mod:parrot.observability.recorders.models
  rel: references
---

# `parrot.observability.recorders.subscriber`

UsageRecordingSubscriber — turns LLM-call events into UsageRecords + fan-out.

This is the bridge between the FEAT-176 lifecycle event system and the pluggable
recorder backends. It subscribes to ``AfterClientCallEvent`` on the global
registry (the same surface the OTel ``MetricsSubscriber`` uses), computes cost
via the shared ``CostCalculator``, builds a normalized ``UsageRecord``, and
fans it out to every configured ``AbstractLogger``.

It implements the ``EventProvider`` protocol (synchronous ``register``).

## Classes

- **`UsageRecordingSubscriber`** — Build ``UsageRecord``s from LLM-call events and fan out to recorders.
