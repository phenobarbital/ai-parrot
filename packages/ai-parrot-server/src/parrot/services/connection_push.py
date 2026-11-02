"""Per-principal Redis fan-out of connection events (FEAT-777 M1)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Optional

import redis.asyncio as aioredis

from parrot.auth.oauth2.events import ConnectionEvent

CHANNEL_TEMPLATE = "parrot:connections:user:{user_id}"


class RedisConnectionPush:
    """``ConnectionEventSink`` that publishes every event on the principal's Redis channel.

    Any gunicorn worker may publish; any worker may serve the subscriber (``subscribe``).
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: Optional[Any] = None
        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """Create the Redis client (aiohttp ``on_startup``)."""
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)

    async def close(self) -> None:
        """Close the Redis client (aiohttp ``on_cleanup``); safe to call twice."""
        redis, self._redis = self._redis, None
        if redis is not None:
            close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    async def deliver(self, event: ConnectionEvent) -> None:
        """PUBLISH ``event.model_dump_json()`` on ``CHANNEL_TEMPLATE.format(user_id=event.user_id)``."""
        if self._redis is None:
            self.logger.warning(
                "RedisConnectionPush.deliver before start(); event for provider %s dropped", event.provider
            )
            return
        await self._redis.publish(CHANNEL_TEMPLATE.format(user_id=event.user_id), event.model_dump_json())

    async def subscribe(self, user_id: str, *, ready: Optional[asyncio.Event] = None) -> AsyncIterator[ConnectionEvent]:
        """Yield the principal's events; own pubsub per call; unsubscribes and closes on exit/cancellation.

        Args:
            user_id: Principal whose channel is subscribed.
            ready: Set once Redis acknowledged the SUBSCRIBE, so a caller can wait for it before
                announcing the stream (events published earlier are never delivered).
        """
        if self._redis is None:
            raise RuntimeError("RedisConnectionPush.subscribe before start()")
        channel = CHANNEL_TEMPLATE.format(user_id=user_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        if ready is not None:
            ready.set()
        try:
            async for raw in pubsub.listen():
                if raw.get("type") != "message":
                    continue
                try:
                    yield ConnectionEvent.model_validate_json(raw["data"])
                except Exception:  # noqa: BLE001 - malformed Redis payloads must not end an SSE stream
                    self.logger.warning("Skipping malformed connection event: %r", raw.get("data"), exc_info=True)
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:  # noqa: BLE001 - cleanup must not hide cancellation or stream failures
                self.logger.exception("Failed to unsubscribe from connection event channel %s", channel)

            close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if close is not None:
                try:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:  # noqa: BLE001 - cleanup must not hide cancellation or stream failures
                    self.logger.exception("Failed to close connection event pubsub for channel %s", channel)
