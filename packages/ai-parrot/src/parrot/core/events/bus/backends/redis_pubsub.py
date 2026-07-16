"""RedisPubSubBackend — legacy Redis pub/sub port (FEAT-310, Module 3).

Absorbs the duplicated dispatch path of the legacy
``EventBus.start_redis_listener()`` (evb.py): the consumer loop now feeds
envelopes to a single callback instead of re-implementing subscription
matching inline.

Semantics (documented, by design): **fan-out only, at-most-once,
unpersisted** — crashed consumers lose events. Durable at-least-once
delivery is the Redis Streams backend (TASK-1789).

Wire format: ``EventEnvelope.to_dict()`` JSON on channels prefixed with
``parrot:events:`` (kept for interop with legacy processes during rollout).
"""
import asyncio
import json
from typing import Any, Optional

import redis.asyncio as aioredis
from navconfig.logging import logging

from parrot.core.events.bus.backends.base import OnEnvelope
from parrot.core.events.bus.envelope import EventEnvelope


class RedisPubSubBackend:
    """Redis pub/sub transport (fan-out only, at-most-once).

    Consumer-task lifecycle mirrors ``BaseBrokerHook``
    (hooks/brokers/base.py): ``start_consumer`` spawns a background task,
    ``close`` cancels and awaits it. Connection failures trigger a
    reconnect loop with exponential backoff; the bus keeps dispatching
    locally in the meantime (spec §7 "Redis down").

    Args:
        redis_url: Redis connection URL (ignored when *client* is given).
        client: Optional pre-built redis client (dependency injection for
            tests); when provided, this backend does not own/close it.
        reconnect_base_delay: Initial backoff delay in seconds.
        reconnect_max_delay: Backoff ceiling in seconds.
    """

    CHANNEL_PREFIX = "parrot:events:"  # keep legacy wire compat

    def __init__(
        self,
        redis_url: Optional[str] = None,
        *,
        client: Optional[Any] = None,
        reconnect_base_delay: float = 0.5,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        if redis_url is None and client is None:
            raise ValueError(
                "RedisPubSubBackend requires a redis_url or an injected client"
            )
        self.redis_url = redis_url
        self._client = client  # injected — not owned
        self._redis: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._on_envelope: Optional[OnEnvelope] = None
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._reconnect_base_delay = reconnect_base_delay
        self._reconnect_max_delay = reconnect_max_delay
        self.logger = logging.getLogger("parrot.core.events.bus.redis_pubsub")

    # ------------------------------------------------------------------
    # TransportBackend protocol
    # ------------------------------------------------------------------

    async def publish(self, envelope: EventEnvelope) -> None:
        """PUBLISH *envelope* as JSON on ``parrot:events:<topic>``.

        Args:
            envelope: The envelope to fan out.
        """
        await self._ensure_connection()
        await self._redis.publish(
            f"{self.CHANNEL_PREFIX}{envelope.topic}",
            json.dumps(envelope.to_dict()),
        )

    async def start_consumer(self, on_envelope: OnEnvelope) -> None:
        """Spawn the background pattern-subscribe consumer loop.

        Args:
            on_envelope: Awaited for each envelope received off the wire.
        """
        self._on_envelope = on_envelope
        self._running = True
        self._consumer_task = asyncio.create_task(
            self._run_consumer(), name="bus-redis-pubsub-consumer"
        )

    async def close(self) -> None:
        """Stop the consumer, punsubscribe, and release connections."""
        self._running = False
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
        if self._pubsub is not None:
            try:
                # psubscribe() patterns need punsubscribe() (evb.py fix).
                await self._pubsub.punsubscribe()
                await self._pubsub.close()
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("pubsub close error: %s", exc)
            self._pubsub = None
        if self._redis is not None and self._client is None:
            # Only close connections we own (not injected test clients).
            try:
                await self._redis.close()
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("redis close error: %s", exc)
        self._redis = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _ensure_connection(self) -> None:
        """(Re)build the redis client if needed."""
        if self._redis is not None:
            return
        if self._client is not None:
            self._redis = self._client
            return
        self._redis = await aioredis.from_url(
            self.redis_url, decode_responses=True
        )

    async def _run_consumer(self) -> None:
        """Consume ``pmessage``s forever, reconnecting with backoff."""
        delay = self._reconnect_base_delay
        while self._running:
            try:
                await self._ensure_connection()
                self._pubsub = self._redis.pubsub()
                await self._pubsub.psubscribe(f"{self.CHANNEL_PREFIX}*")
                self.logger.info("Redis pub/sub consumer subscribed")
                delay = self._reconnect_base_delay  # reset after success
                async for message in self._pubsub.listen():
                    if not self._running:
                        return
                    if message.get("type") != "pmessage":
                        continue
                    await self._handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — degraded mode
                if not self._running:
                    return
                self.logger.warning(
                    "Redis pub/sub consumer error (%s: %s) — reconnecting "
                    "in %.1fs; local dispatch continues",
                    type(exc).__name__, exc, delay,
                )
                self._redis = None if self._client is None else self._redis
                self._pubsub = None
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max_delay)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Decode one wire message and hand it to the consumer callback."""
        try:
            envelope = EventEnvelope.from_dict(json.loads(message["data"]))
        except Exception as exc:  # noqa: BLE001 — poison messages isolated
            self.logger.error("Undecodable pub/sub message dropped: %s", exc)
            return
        try:
            await self._on_envelope(envelope)
        except Exception:  # noqa: BLE001 — consumer errors isolated
            self.logger.exception(
                "Consumer callback failed for %s", envelope.topic
            )
