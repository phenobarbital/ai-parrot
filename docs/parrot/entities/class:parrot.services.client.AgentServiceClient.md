---
type: Wiki Entity
title: AgentServiceClient
id: class:parrot.services.client.AgentServiceClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async client for submitting tasks to a running AgentService.
---

# AgentServiceClient

Defined in [`parrot.services.client`](../summaries/mod:parrot.services.client.md).

```python
class AgentServiceClient
```

Async client for submitting tasks to a running AgentService.

Publishes tasks to a Redis Stream and optionally waits for results
on the response stream.

Usage::

    async with AgentServiceClient("redis://localhost:6379") as client:
        task_id = await client.submit_task(
            AgentTask(agent_name="MyAgent", prompt="Hello")
        )
        result = await client.get_result(task_id, timeout=30)

## Methods

- `async def connect(self) -> None` — Connect to Redis.
- `async def disconnect(self) -> None` — Disconnect from Redis.
- `async def submit_task(self, task: AgentTask) -> str` — Publish a task to the AgentService task stream.
- `async def get_result(self, task_id: str, timeout: float=60.0) -> Optional[TaskResult]` — Wait for a task result on the response stream.
- `async def submit_and_wait(self, task: AgentTask, timeout: float=60.0) -> Optional[TaskResult]` — Submit a task and wait for its result.
