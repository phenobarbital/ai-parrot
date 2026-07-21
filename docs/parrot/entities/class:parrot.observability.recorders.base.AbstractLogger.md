---
type: Wiki Entity
title: AbstractLogger
id: class:parrot.observability.recorders.base.AbstractLogger
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base for pluggable usage/token/cost recorders.
---

# AbstractLogger

Defined in [`parrot.observability.recorders.base`](../summaries/mod:parrot.observability.recorders.base.md).

```python
class AbstractLogger(ABC)
```

Abstract base for pluggable usage/token/cost recorders.

Implementations MUST be cheap and non-blocking on the hot path: ``record``
runs inside the event-dispatch coroutine of every LLM call. Backends that
perform network I/O should buffer and flush out-of-band, or rely on a
pull-based exposition model (e.g. Prometheus).

Attributes:
    name: Short identifier for the backend (used in logs/diagnostics).

## Methods

- `async def record(self, record: UsageRecord) -> None` — Record a single normalized usage record.
- `async def aclose(self) -> None` — Flush and release any resources. Default implementation is a no-op.
