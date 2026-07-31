---
type: Wiki Entity
title: RedisBroadcastForwarder
id: class:parrot.integrations.liveavatar.output_transport.RedisBroadcastForwarder
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: '``UserSocketManager``-compatible sink that forwards broadcasts over Redis.'
---

# RedisBroadcastForwarder

Defined in [`parrot.integrations.liveavatar.output_transport`](../summaries/mod:parrot.integrations.liveavatar.output_transport.md).

```python
class RedisBroadcastForwarder
```

``UserSocketManager``-compatible sink that forwards broadcasts over Redis.

Implements the single method :class:`OutputBridge` depends on —
``broadcast_to_channel(channel, message, exclude_ws=None)`` — by publishing a
JSON envelope to a Redis pub/sub channel. The ai-parrot-server consumes it
via :func:`run_output_subscriber` and re-broadcasts to the browser.

Args:
    redis_client: An async Redis client (``redis.asyncio.Redis``) exposing
        ``publish(channel, data)`` and ``aclose()``.
    channel: Redis pub/sub channel to publish envelopes on.

## Methods

- `def from_url(cls, redis_url: str, *, channel: str=DEFAULT_OUTPUT_CHANNEL) -> 'RedisBroadcastForwarder'` — Build a forwarder from a Redis URL (lazy ``redis.asyncio`` import).
- `async def broadcast_to_channel(self, channel: str, message: Any, exclude_ws: Any=None) -> None` — Publish a ``{"channel", "message"}`` envelope to Redis.
- `async def aclose(self) -> None` — Close the underlying Redis client if it owns one.
