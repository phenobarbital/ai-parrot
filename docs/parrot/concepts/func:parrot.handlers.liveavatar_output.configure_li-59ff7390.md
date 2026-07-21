---
type: Concept
title: configure_liveavatar_output_subscriber()
id: func:parrot.handlers.liveavatar_output.configure_liveavatar_output_subscriber
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register the LiveAvatar output subscriber on the aiohttp application.
---

# configure_liveavatar_output_subscriber

```python
def configure_liveavatar_output_subscriber(app: web.Application, *, redis_url: Optional[str]=None, channel: Optional[str]=None) -> web.Application
```

Register the LiveAvatar output subscriber on the aiohttp application.

On startup it builds a Redis client, looks up ``app['user_socket_manager']``
and launches a long-lived background task running
``run_output_subscriber``. On cleanup the task is cancelled and the Redis
client closed.

Args:
    app: The aiohttp Application.
    redis_url: Redis URL to subscribe on. Must match the worker's forwarder.
        Defaults to ``parrot.conf.REDIS_URL``.
    channel: Redis pub/sub channel. Defaults to the transport's
        ``DEFAULT_OUTPUT_CHANNEL``.

Returns:
    The same ``app`` (for chaining).
