---
type: Wiki Entity
title: InstrumentedBackend
id: class:parrot.storage.instrumented.InstrumentedBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wraps any ConversationBackend and records per-method latency + errors.
relates_to:
- concept: class:parrot.storage.backends.base.ConversationBackend
  rel: extends
---

# InstrumentedBackend

Defined in [`parrot.storage.instrumented`](../summaries/mod:parrot.storage.instrumented.md).

```python
class InstrumentedBackend(ConversationBackend)
```

Wraps any ConversationBackend and records per-method latency + errors.

The wrapper delegates every abstract method to the inner backend while
timing the call and reporting to the configured ``StorageMetrics`` instance.

``is_connected`` and ``build_overflow_prefix`` pass through without timing
since they are synchronous and zero-cost.

Args:
    inner: Any ``ConversationBackend`` implementation.
    metrics: Optional ``StorageMetrics`` instance. Defaults to no-op.

## Methods

- `async def initialize(self) -> None`
- `async def close(self) -> None`
- `def is_connected(self) -> bool`
- `def build_overflow_prefix(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> str`
- `async def put_thread(self, *a, **kw) -> None`
- `async def update_thread(self, *a, **kw) -> None`
- `async def query_threads(self, *a, **kw) -> List[dict]`
- `async def put_turn(self, *a, **kw) -> None`
- `async def query_turns(self, *a, **kw) -> List[dict]`
- `async def delete_turn(self, *a, **kw) -> bool`
- `async def delete_thread_cascade(self, *a, **kw) -> int`
- `async def put_artifact(self, *a, **kw) -> None`
- `async def get_artifact(self, *a, **kw) -> Optional[dict]`
- `async def query_artifacts(self, *a, **kw) -> List[dict]`
- `async def delete_artifact(self, *a, **kw) -> None`
- `async def delete_session_artifacts(self, *a, **kw) -> int`
