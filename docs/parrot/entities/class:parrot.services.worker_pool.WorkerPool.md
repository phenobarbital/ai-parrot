---
type: Wiki Entity
title: WorkerPool
id: class:parrot.services.worker_pool.WorkerPool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Limits concurrent agent executions using an asyncio semaphore.
---

# WorkerPool

Defined in [`parrot.services.worker_pool`](../summaries/mod:parrot.services.worker_pool.md).

```python
class WorkerPool
```

Limits concurrent agent executions using an asyncio semaphore.

## Methods

- `def active_count(self) -> int` — Number of currently executing tasks.
- `def available_slots(self) -> int` — Number of available worker slots.
- `async def submit(self, coro: Coroutine[Any, Any, Any], name: Optional[str]=None) -> asyncio.Task` — Submit a coroutine for execution within the bounded pool.
- `async def shutdown(self, timeout: float=30.0) -> None` — Gracefully shut down the worker pool.
