---
type: Wiki Entity
title: TaskQueue
id: class:parrot.services.task_queue.TaskQueue
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Priority-aware async task queue.
---

# TaskQueue

Defined in [`parrot.services.task_queue`](../summaries/mod:parrot.services.task_queue.md).

```python
class TaskQueue
```

Priority-aware async task queue.

Uses ``asyncio.PriorityQueue`` for in-memory hot path with optional
Redis sorted-set persistence for crash recovery.

## Methods

- `async def put(self, task: AgentTask) -> None` — Enqueue a task with priority ordering.
- `async def get(self) -> AgentTask` — Dequeue the highest-priority task (blocking).
- `def get_nowait(self) -> Optional[AgentTask]` — Non-blocking dequeue, returns None if empty.
- `def qsize(self) -> int` — Current number of tasks in the queue.
- `def empty(self) -> bool` — True if queue has no pending tasks.
- `async def recover(self) -> int` — Recover tasks from Redis on startup.
- `async def clear_persisted(self) -> None` — Remove all persisted tasks from Redis.
- `def task_done(self) -> None` — Mark the last dequeued task as done.
