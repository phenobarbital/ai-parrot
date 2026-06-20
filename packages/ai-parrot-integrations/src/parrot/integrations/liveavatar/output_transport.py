"""Cross-process transport for structured-output delivery (FEAT-249).

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
"""

import json
import logging
from typing import Any

__all__ = [
    "DEFAULT_OUTPUT_CHANNEL",
    "RedisBroadcastForwarder",
    "run_output_subscriber",
]

#: Redis pub/sub channel carrying structured-output envelopes worker → server.
DEFAULT_OUTPUT_CHANNEL = "liveavatar:structured-outputs"

logger = logging.getLogger(__name__)


class RedisBroadcastForwarder:
    """``UserSocketManager``-compatible sink that forwards broadcasts over Redis.

    Implements the single method :class:`OutputBridge` depends on —
    ``broadcast_to_channel(channel, message, exclude_ws=None)`` — by publishing a
    JSON envelope to a Redis pub/sub channel. The ai-parrot-server consumes it
    via :func:`run_output_subscriber` and re-broadcasts to the browser.

    Args:
        redis_client: An async Redis client (``redis.asyncio.Redis``) exposing
            ``publish(channel, data)`` and ``aclose()``.
        channel: Redis pub/sub channel to publish envelopes on.
    """

    def __init__(
        self, redis_client: Any, *, channel: str = DEFAULT_OUTPUT_CHANNEL
    ) -> None:
        self._redis = redis_client
        self._channel = channel
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_url(
        cls, redis_url: str, *, channel: str = DEFAULT_OUTPUT_CHANNEL
    ) -> "RedisBroadcastForwarder":
        """Build a forwarder from a Redis URL (lazy ``redis.asyncio`` import)."""
        import redis.asyncio as aioredis

        return cls(
            aioredis.from_url(redis_url, decode_responses=True), channel=channel
        )

    async def broadcast_to_channel(
        self, channel: str, message: Any, exclude_ws: Any = None
    ) -> None:
        """Publish a ``{"channel", "message"}`` envelope to Redis.

        Signature mirrors ``UserSocketManager.broadcast_to_channel`` so
        :class:`OutputBridge` is agnostic to which sink it holds. ``exclude_ws``
        is accepted for compatibility and ignored (no local sockets here).
        """
        envelope = json.dumps({"channel": channel, "message": message})
        await self._redis.publish(self._channel, envelope)
        self.logger.debug(
            "Forwarded output to redis channel %s (target=%s)",
            self._channel,
            channel,
        )

    async def aclose(self) -> None:
        """Close the underlying Redis client if it owns one."""
        close = getattr(self._redis, "aclose", None) or getattr(
            self._redis, "close", None
        )
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


async def run_output_subscriber(
    redis_client: Any,
    socket_manager: Any,
    *,
    channel: str = DEFAULT_OUTPUT_CHANNEL,
) -> None:
    """Consume output envelopes from Redis and re-broadcast them (server side).

    Runs in the ai-parrot-server process. For each envelope received on
    ``channel`` it calls ``socket_manager.broadcast_to_channel`` with the
    original target channel (the ``session_id``) and message, delivering the
    worker's structured output to the browser. Runs until cancelled.

    Args:
        redis_client: Async Redis client (``redis.asyncio.Redis``).
        socket_manager: The real ``UserSocketManager`` (duck-typed).
        channel: Redis pub/sub channel to subscribe to.
    """
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    logger.info("Structured-output subscriber listening on redis channel %s", channel)
    try:
        async for raw in pubsub.listen():
            if raw.get("type") != "message":
                continue
            try:
                envelope = json.loads(raw["data"])
                await socket_manager.broadcast_to_channel(
                    channel=envelope["channel"],
                    message=envelope["message"],
                )
            except Exception:  # noqa: BLE001 - one bad message must not kill the loop
                logger.exception(
                    "Failed to re-broadcast structured-output envelope: %r",
                    raw.get("data"),
                )
    finally:
        await pubsub.unsubscribe(channel)
