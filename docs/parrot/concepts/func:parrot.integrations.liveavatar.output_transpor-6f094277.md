---
type: Concept
title: run_output_subscriber()
id: func:parrot.integrations.liveavatar.output_transport.run_output_subscriber
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Consume output envelopes from Redis and re-broadcast them (server side).
---

# run_output_subscriber

```python
async def run_output_subscriber(redis_client: Any, socket_manager: Any, *, channel: str=DEFAULT_OUTPUT_CHANNEL) -> None
```

Consume output envelopes from Redis and re-broadcast them (server side).

Runs in the ai-parrot-server process. For each envelope received on
``channel`` it calls ``socket_manager.broadcast_to_channel`` with the
original target channel (the ``session_id``) and message, delivering the
worker's structured output to the browser. Runs until cancelled.

Args:
    redis_client: Async Redis client (``redis.asyncio.Redis``).
    socket_manager: The real ``UserSocketManager`` (duck-typed).
    channel: Redis pub/sub channel to subscribe to.
