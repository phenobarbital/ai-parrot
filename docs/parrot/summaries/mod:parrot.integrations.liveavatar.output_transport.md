---
type: Wiki Summary
title: parrot.integrations.liveavatar.output_transport
id: mod:parrot.integrations.liveavatar.output_transport
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cross-process transport for structured-output delivery (FEAT-249).
relates_to:
- concept: class:parrot.integrations.liveavatar.output_transport.RedisBroadcastForwarder
  rel: defines
- concept: func:parrot.integrations.liveavatar.output_transport.run_output_subscriber
  rel: defines
---

# `parrot.integrations.liveavatar.output_transport`

Cross-process transport for structured-output delivery (FEAT-249).

ai-parrot-server is multi-process (gunicorn); ``UserSocketManager.broadcast_to_channel``
is in-process only. Structured outputs from any ai-parrot worker process must
cross the process boundary to reach the browser's WebSocket connection, which
may be held by a different gunicorn worker. This module bridges that gap over
Redis pub/sub:

- :class:`RedisBroadcastForwarder` is a duck-typed stand-in for
  ``UserSocketManager`` that :class:`OutputBridge` can use unchanged: its
  ``broadcast_to_channel`` publishes a JSON envelope to a Redis channel.
- :func:`run_output_subscriber` runs in the ai-parrot-server process: it
  subscribes to that Redis channel and replays each envelope through the real
  ``UserSocketManager.broadcast_to_channel`` (re-broadcast to the browser).

Envelope schema published on the Redis channel::

    {"channel": "<session_id>", "message": {<StructuredOutputMessage.model_dump()>}}

``redis.asyncio`` is imported lazily so importing this module never requires the
``redis`` dependency.

## Classes

- **`RedisBroadcastForwarder`** — ``UserSocketManager``-compatible sink that forwards broadcasts over Redis.

## Functions

- `async def run_output_subscriber(redis_client: Any, socket_manager: Any, *, channel: str=DEFAULT_OUTPUT_CHANNEL) -> None` — Consume output envelopes from Redis and re-broadcast them (server side).
