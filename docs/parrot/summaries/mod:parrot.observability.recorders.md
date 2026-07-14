---
type: Wiki Summary
title: parrot.observability.recorders
id: mod:parrot.observability.recorders
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pluggable usage/token/cost recording backends.
relates_to:
- concept: mod:parrot.observability.recorders.base
  rel: references
- concept: mod:parrot.observability.recorders.factory
  rel: references
- concept: mod:parrot.observability.recorders.logging_recorder
  rel: references
- concept: mod:parrot.observability.recorders.models
  rel: references
- concept: mod:parrot.observability.recorders.subscriber
  rel: references
---

# `parrot.observability.recorders`

Pluggable usage/token/cost recording backends.

A single ``AbstractLogger`` interface fronts every backend (logging, Prometheus,
…). ``UsageRecordingSubscriber`` builds one ``UsageRecord`` per LLM call from the
FEAT-176 lifecycle events (reusing the shared ``CostCalculator``) and fans it out
to the configured recorders. Backend selection is driven by
``ObservabilityConfig.usage_backend``.

The logging path imports NO OpenTelemetry SDK and adds no third-party
dependency. ``PrometheusUsageRecorder`` lazily imports ``prometheus_client``.
