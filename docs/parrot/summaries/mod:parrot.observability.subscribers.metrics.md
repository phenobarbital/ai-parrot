---
type: Wiki Summary
title: parrot.observability.subscribers.metrics
id: mod:parrot.observability.subscribers.metrics
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MetricsSubscriber — OTel counters and histograms for LLM calls.
relates_to:
- concept: class:parrot.observability.subscribers.metrics.MetricsSubscriber
  rel: defines
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
- concept: mod:parrot.observability.attributes
  rel: references
- concept: mod:parrot.observability.cost.calculator
  rel: references
---

# `parrot.observability.subscribers.metrics`

MetricsSubscriber — OTel counters and histograms for LLM calls.

FEAT-177 TASK-1231. Separate subscriber from ``GenAIOpenTelemetrySubscriber``
so Prometheus-only deployments can receive metrics without span overhead.

Spec §2 Event → Metric mapping and §3 Module 4.

Cardinality whitelist: ONLY the attributes documented per metric may appear in
metric labels. ``user_id``, ``session_id``, prompt/completion content NEVER
appear in metric labels.

Default histogram bucket boundaries (D6): ``[0.01, 0.05, 0.1, 0.5, 1.0,
5.0, 30.0, 60.0]`` seconds — LLM-tuned. Overridable via constructor.

## Classes

- **`MetricsSubscriber`** — OTel counter and histogram subscriber for LLM / tool / invoke events.
