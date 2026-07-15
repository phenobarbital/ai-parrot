---
type: Wiki Entity
title: NoopStorageMetrics
id: class:parrot.storage.metrics.NoopStorageMetrics
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Default metrics implementation — records nothing.
---

# NoopStorageMetrics

Defined in [`parrot.storage.metrics`](../summaries/mod:parrot.storage.metrics.md).

```python
class NoopStorageMetrics
```

Default metrics implementation — records nothing.

Used when ``PARROT_STORAGE_METRICS`` is unset (the common case).
Zero overhead: every method is a Python ``...`` no-op.

## Methods

- `def record_latency(self, backend_name: str, method: str, duration_ms: float) -> None`
- `def record_error(self, backend_name: str, method: str, error_type: str) -> None`
