---
type: Wiki Entity
title: StorageMetrics
id: class:parrot.storage.metrics.StorageMetrics
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Protocol for storage-backend metric collection.
---

# StorageMetrics

Defined in [`parrot.storage.metrics`](../summaries/mod:parrot.storage.metrics.md).

```python
class StorageMetrics(Protocol)
```

Protocol for storage-backend metric collection.

Implementers plug in Prometheus / OpenTelemetry / statsd in their own code.
AI-Parrot ships a no-op default and an ``InstrumentedBackend`` wrapper that
calls these methods around every backend operation.

Example Prometheus adapter — see docs/storage-backends.md §Observability.

## Methods

- `def record_latency(self, backend_name: str, method: str, duration_ms: float) -> None` — Record the latency of a single backend method call.
- `def record_error(self, backend_name: str, method: str, error_type: str) -> None` — Record that a backend method raised an exception.
