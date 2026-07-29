---
type: Wiki Entity
title: RedisTaskListener
id: class:parrot.services.redis_listener.RedisTaskListener
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Listens for incoming tasks on a Redis Stream using consumer groups.
---

# RedisTaskListener

Defined in [`parrot.services.redis_listener`](../summaries/mod:parrot.services.redis_listener.md).

```python
class RedisTaskListener
```

Listens for incoming tasks on a Redis Stream using consumer groups.

Uses ``XREADGROUP`` for reliable delivery and ``XACK`` for acknowledgement.
Also publishes results back on a response stream.

## Methods

- `async def connect(self) -> None` — Connect to Redis and ensure consumer group exists.
- `async def disconnect(self) -> None` — Disconnect from Redis.
- `async def listen(self) -> AsyncIterator[AgentTask]` — Yield AgentTask instances from the Redis Stream.
- `async def ack(self, message_id: str) -> None` — Acknowledge a processed message.
- `async def publish_result(self, result: TaskResult) -> str` — Publish a task result to the response stream.
- `def stop(self) -> None` — Signal the listener to stop.
