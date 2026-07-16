"""RedisStreamsBackend — durable at-least-once transport (FEAT-310, Module 7).

Brings goal G4: consumer groups, explicit ACKs, ``XAUTOCLAIM`` pending
recovery, and ``event_id`` dedup — at-least-once delivery across Cloud Run
instances with zero app-code change (it is just another
:class:`~parrot.core.events.bus.backends.base.TransportBackend`).

Design (spec §2 layer 3):

- **Stream per topic-class** (first topic segment):
  ``XADD parrot:stream:<topic-class>`` with the ``EventEnvelope.to_dict()``
  JSON wire format in a single ``envelope`` field.
- **Consumer group** ``parrot-bus`` (configurable) with a per-instance
  consumer name (``<hostname>-<pid>``) for XAUTOCLAIM bookkeeping.
- **Dedup**: TTL'd Redis key ``parrot:events:dedup:<event_id>``
  (default 24 h) — checked before dispatch, set only AFTER successful
  dispatch (crash-safe: a crash mid-dispatch leaves the entry un-ACKed
  and unmarked, so it is reclaimed and reprocessed).

⚠️ **At-least-once, NOT exactly-once** (spec §7 "Duplicate delivery"): the
dedup set *mitigates* duplicates but cannot eliminate them (TTL expiry,
Redis eviction, crash between dispatch and ACK). Consumers MUST be
idempotent in distributed mode.

**Retention decision** (spec §7, resolved during implementation):
``XADD ... MAXLEN ~ <n>`` (approximate trim, default 100 000 entries per
stream). Rationale: ``MAXLEN ~`` is O(1) amortized (radix-node granular),
requires no external trimming job and bounds Memorystore/Upstash memory
predictably; ``MINID`` would need a time-based id bookkeeping/trimmer
process for little benefit at our volumes.

Deployment note: requires reachable Memorystore/Upstash from every Cloud
Run instance — configuration only, no code assumptions.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
from typing import Any, Optional

import redis.asyncio as aioredis
from navconfig.logging import logging

from parrot.core.events.bus.backends.base import OnEnvelope
from parrot.core.events.bus.envelope import EventEnvelope


def _default_consumer_name() -> str:
    """Stable per-instance consumer name for XAUTOCLAIM bookkeeping."""
    return f"{socket.gethostname()}-{os.getpid()}"


class RedisStreamsBackend:
    """Redis Streams transport: durable, replayable, at-least-once.

    Args:
        redis_url: Redis connection URL (ignored when *client* is given).
        client: Optional pre-built redis client (dependency injection for
            tests); when provided, this backend does not own/close it.
        group: Consumer-group name.
        consumer_name: Per-instance consumer name
            (default ``<hostname>-<pid>``).
        dedup_ttl: TTL in seconds for the ``event_id`` dedup keys
            (default 24 h).
        block_ms: ``XREADGROUP`` blocking timeout in milliseconds — keeps
            the loop cancellable on ``close()``.
        batch_count: Max messages fetched per ``XREADGROUP``/``XAUTOCLAIM``.
        min_idle_time_ms: Pending-entry idle time before the sweeper
            reclaims it (crashed-consumer recovery).
        autoclaim_interval: Seconds between sweeper passes.
        maxlen: Approximate per-stream retention (``MAXLEN ~`` — see the
            module docstring for the decision rationale).
        stream_refresh_interval: Seconds between ``SCAN``-based discovery
            of new ``parrot:stream:*`` streams.
        reconnect_base_delay: Initial reconnect backoff in seconds.
        reconnect_max_delay: Reconnect backoff ceiling in seconds.
    """

    STREAM_PREFIX = "parrot:stream:"
    DEDUP_PREFIX = "parrot:events:dedup:"

    def __init__(
        self,
        redis_url: Optional[str] = None,
        *,
        client: Optional[Any] = None,
        group: str = "parrot-bus",
        consumer_name: Optional[str] = None,
        dedup_ttl: int = 86_400,
        block_ms: int = 1_000,
        batch_count: int = 32,
        min_idle_time_ms: int = 60_000,
        autoclaim_interval: float = 30.0,
        maxlen: int = 100_000,
        stream_refresh_interval: float = 10.0,
        reconnect_base_delay: float = 0.5,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        if redis_url is None and client is None:
            raise ValueError(
                "RedisStreamsBackend requires a redis_url or an injected client"
            )
        self.redis_url = redis_url
        self._client = client  # injected — not owned
        self._redis: Optional[Any] = None
        self._group = group
        self._consumer = consumer_name or _default_consumer_name()
        self._dedup_ttl = dedup_ttl
        self._block_ms = block_ms
        self._batch_count = batch_count
        self._min_idle_time_ms = min_idle_time_ms
        self._autoclaim_interval = autoclaim_interval
        self._maxlen = maxlen
        self._stream_refresh_interval = stream_refresh_interval
        self._reconnect_base_delay = reconnect_base_delay
        self._reconnect_max_delay = reconnect_max_delay

        self._on_envelope: Optional[OnEnvelope] = None
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._sweeper_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._streams: set[str] = set()
        self._groups_ready: set[str] = set()
        self.logger = logging.getLogger("parrot.core.events.bus.redis_streams")

    # ------------------------------------------------------------------
    # TransportBackend protocol
    # ------------------------------------------------------------------

    async def publish(self, envelope: EventEnvelope) -> None:
        """``XADD`` *envelope* to its topic-class stream (MAXLEN ~ trim).

        Args:
            envelope: The envelope to persist on the stream.
        """
        await self._ensure_connection()
        stream = self._stream_for(envelope.topic)
        await self._ensure_group(stream)
        await self._redis.xadd(
            stream,
            {"envelope": json.dumps(envelope.to_dict())},
            maxlen=self._maxlen,
            approximate=True,
        )

    async def start_consumer(self, on_envelope: OnEnvelope) -> None:
        """Spawn the XREADGROUP consumer loop and the XAUTOCLAIM sweeper.

        Args:
            on_envelope: Awaited for each (deduped) envelope.
        """
        self._on_envelope = on_envelope
        self._running = True
        self._consumer_task = asyncio.create_task(
            self._run_consumer(), name="bus-redis-streams-consumer"
        )
        self._sweeper_task = asyncio.create_task(
            self._run_sweeper(), name="bus-redis-streams-sweeper"
        )

    async def close(self) -> None:
        """Stop consumer + sweeper and release owned connections."""
        self._running = False
        for task in (self._consumer_task, self._sweeper_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._consumer_task = None
        self._sweeper_task = None
        if self._redis is not None and self._client is None:
            try:
                await self._redis.close()
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("redis close error: %s", exc)
        self._redis = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _stream_for(self, topic: str) -> str:
        """Stream key for *topic* (per topic-class — spec-fixed sharding)."""
        return f"{self.STREAM_PREFIX}{topic.split('.', 1)[0]}"

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

    async def _ensure_group(self, stream: str) -> None:
        """Idempotently create the consumer group (MKSTREAM) for *stream*."""
        if stream in self._groups_ready:
            return
        try:
            await self._redis.xgroup_create(
                stream, self._group, id="0", mkstream=True
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._groups_ready.add(stream)
        self._streams.add(stream)

    async def _refresh_streams(self) -> None:
        """Discover ``parrot:stream:*`` streams and join their groups."""
        async for key in self._redis.scan_iter(match=f"{self.STREAM_PREFIX}*"):
            name = key.decode() if isinstance(key, bytes) else key
            if name not in self._streams:
                await self._ensure_group(name)

    async def _run_consumer(self) -> None:
        """XREADGROUP loop with reconnect-and-backoff (degraded mode)."""
        delay = self._reconnect_base_delay
        last_refresh = 0.0
        while self._running:
            try:
                await self._ensure_connection()
                loop_now = asyncio.get_running_loop().time()
                if (
                    not self._streams
                    or loop_now - last_refresh >= self._stream_refresh_interval
                ):
                    await self._refresh_streams()
                    last_refresh = loop_now
                if not self._streams:
                    await asyncio.sleep(self._block_ms / 1000)
                    continue
                results = await self._redis.xreadgroup(
                    self._group,
                    self._consumer,
                    {stream: ">" for stream in self._streams},
                    count=self._batch_count,
                    block=self._block_ms,
                )
                delay = self._reconnect_base_delay  # healthy — reset backoff
                for stream, messages in results or []:
                    stream_name = (
                        stream.decode() if isinstance(stream, bytes) else stream
                    )
                    for msg_id, fields in messages:
                        await self._handle_message(stream_name, msg_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — degraded mode
                if not self._running:
                    return
                self.logger.warning(
                    "Streams consumer error (%s: %s) — reconnecting in "
                    "%.1fs; local dispatch continues",
                    type(exc).__name__, exc, delay,
                )
                if self._client is None:
                    self._redis = None
                self._groups_ready.clear()
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max_delay)

    async def _run_sweeper(self) -> None:
        """Periodic XAUTOCLAIM pass reclaiming stale pending entries."""
        while self._running:
            try:
                await asyncio.sleep(self._autoclaim_interval)
                await self._ensure_connection()
                for stream in list(self._streams):
                    result = await self._redis.xautoclaim(
                        stream,
                        self._group,
                        self._consumer,
                        min_idle_time=self._min_idle_time_ms,
                        start_id="0-0",
                        count=self._batch_count,
                    )
                    # redis-py returns [next_start, messages(, deleted_ids)]
                    messages = result[1] if result and len(result) > 1 else []
                    for msg_id, fields in messages:
                        self.logger.info(
                            "XAUTOCLAIM reclaimed %s from %s", msg_id, stream
                        )
                        await self._handle_message(stream, msg_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — degraded mode
                if not self._running:
                    return
                self.logger.warning("Streams sweeper error: %s", exc)

    async def _handle_message(
        self, stream: str, msg_id: Any, fields: dict[str, Any]
    ) -> None:
        """Dedup-check, dispatch, and ACK one stream entry.

        Ordering is crash-safe (at-least-once):

        1. ``event_id`` already in the dedup set → skip dispatch, ``XACK``.
        2. Dispatch via ``on_envelope`` — with ``BusCore`` this runs the
           subscribers INLINE (handler failures are isolated inside the
           core: retry → DLQ, so they count as processed).
        3. ONLY on successful return: mark the dedup key, then ``XACK``.

        A crash anywhere before step 3 leaves the entry un-ACKed and the
        dedup key unset, so ``XAUTOCLAIM`` redelivers it for reprocessing.
        The check→set window means a reclaimed entry can occasionally be
        processed twice across consumers — that IS at-least-once;
        consumers must be idempotent (spec §7).
        """
        raw = fields.get("envelope") or fields.get(b"envelope")
        try:
            data = raw.decode() if isinstance(raw, bytes) else raw
            envelope = EventEnvelope.from_dict(json.loads(data))
        except Exception as exc:  # noqa: BLE001 — poison entries isolated
            self.logger.error(
                "Undecodable stream entry %s on %s dropped: %s",
                msg_id, stream, exc,
            )
            await self._ack(stream, msg_id)
            return

        dedup_key = f"{self.DEDUP_PREFIX}{envelope.event_id}"
        seen = await self._redis.get(dedup_key)
        if seen:
            self.logger.debug(
                "Duplicate event %s skipped (dedup set)", envelope.event_id
            )
            await self._ack(stream, msg_id)
            return
        try:
            await self._on_envelope(envelope)
        except Exception:  # noqa: BLE001 — leave pending for redelivery
            self.logger.exception(
                "Consumer callback failed for %s — entry stays pending "
                "(un-ACKed) for reclaim", envelope.topic,
            )
            return
        # Success: mark seen FIRST, then ACK — a crash between the two
        # redelivers a message the dedup check will skip (and re-ACK).
        try:
            await self._redis.set(dedup_key, "1", ex=self._dedup_ttl)
        except Exception:  # noqa: BLE001 — dedup is best-effort
            self.logger.warning(
                "Dedup mark failed for %s (duplicates possible)",
                envelope.event_id,
            )
        await self._ack(stream, msg_id)

    async def _ack(self, stream: str, msg_id: Any) -> None:
        """Best-effort XACK."""
        try:
            await self._redis.xack(stream, self._group, msg_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("XACK failed for %s on %s: %s", msg_id, stream, exc)
