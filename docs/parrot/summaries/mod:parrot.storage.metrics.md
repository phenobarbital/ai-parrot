---
type: Wiki Summary
title: parrot.storage.metrics
id: mod:parrot.storage.metrics
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: StorageMetrics protocol and no-op default implementation.
relates_to:
- concept: class:parrot.storage.metrics.NoopStorageMetrics
  rel: defines
- concept: class:parrot.storage.metrics.StorageMetrics
  rel: defines
---

# `parrot.storage.metrics`

StorageMetrics protocol and no-op default implementation.

Defines the two-method observability seam used by ``InstrumentedBackend``.
Production callers plug in their own adapter (Prometheus, OpenTelemetry,
statsd) by implementing this protocol and pointing ``PARROT_STORAGE_METRICS``
at a module-level instance.

FEAT-116: dynamodb-fallback-redis — Module 8 (observability hooks).

## Classes

- **`StorageMetrics(Protocol)`** — Protocol for storage-backend metric collection.
- **`NoopStorageMetrics`** — Default metrics implementation — records nothing.
