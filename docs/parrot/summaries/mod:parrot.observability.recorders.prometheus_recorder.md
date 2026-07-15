---
type: Wiki Summary
title: parrot.observability.recorders.prometheus_recorder
id: mod:parrot.observability.recorders.prometheus_recorder
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PrometheusUsageRecorder — pull-based metrics backend (described, lazy-loaded).
relates_to:
- concept: class:parrot.observability.recorders.prometheus_recorder.PrometheusUsageRecorder
  rel: defines
- concept: mod:parrot.observability.recorders.base
  rel: references
- concept: mod:parrot.observability.recorders.models
  rel: references
---

# `parrot.observability.recorders.prometheus_recorder`

PrometheusUsageRecorder — pull-based metrics backend (described, lazy-loaded).

A lightweight, low-latency backend for usage/token/cost metrics. Uses
``prometheus_client`` directly (not the OTel→Prometheus exporter) so the
logging-first design never drags in the OTel SDK. Metrics are updated in-process
(counter ``.inc`` / histogram ``.observe`` — no network on the hot path) and
exposed on an HTTP endpoint that Prometheus scrapes, so request latency is
unaffected.

Install with: ``pip install 'ai-parrot[observability-prometheus]'``.

Cardinality contract: labels are limited to ``provider`` (bounded ~10 values)
and ``model``. NEVER ``trace_id``/``user_id``/``session_id``/prompt content.

## Classes

- **`PrometheusUsageRecorder(AbstractLogger)`** — Record usage as Prometheus counters/histograms exposed over HTTP.
