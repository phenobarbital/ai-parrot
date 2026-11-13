"""Application-level turn bus: Redis Streams + durable outbox + dead letters (FEAT-886 M10).

Builds the dedicated bus that carries ``conversation.turn.completed`` to ``ChatStorage``,
subscribes the storage handlers and tears everything down. Mirrors ``observability/fanout.py``
but is a SEPARATE bus and is not publish-only: it consumes.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from navconfig.logging import logging
from navigator_eventbus import DLQHandler, EventBus, EventEnvelope
from navigator_eventbus.backends.redis_streams import RedisStreamsBackend

from parrot import conf
from parrot.memory.persistence import CONVERSATION_DELETED_TOPIC, TURN_COMPLETED_TOPIC, BusTurnPublisher
from parrot.storage.chat import ChatStorage

logger = logging.getLogger("parrot.storage.turn_bus")


@dataclass
class TurnPersistence:
    """Handle returned by :func:`setup_turn_persistence`.

    Attributes:
        bus: The turn ``EventBus``.
        publisher: The ``BusTurnPublisher`` bots publish through.
        subscription_ids: ``bus.core`` subscription ids (turn + deletion handlers).
        dlq: A ``DLQHandler`` (Postgres) or a ``SqliteDeadLetterStore``; ``None`` for an injected bus.
    """

    bus: Any
    publisher: BusTurnPublisher
    subscription_ids: List[str]
    dlq: Optional[Any] = None


def _setting(name: str) -> Optional[str]:
    """Read a ``parrot.conf`` setting at call time (tests monkeypatch the module attribute)."""
    value = getattr(conf, name, None)
    return str(value) if value not in (None, "") else None


def _resolve_outbox_dir() -> Path:
    """Return the validated writable outbox directory.

    Raises:
        RuntimeError: ``PARROT_TURN_BUS_OUTBOX_DIR`` is unset, not a directory or not writable.
    """
    configured = _setting("PARROT_TURN_BUS_OUTBOX_DIR")
    if not configured:
        raise RuntimeError("PARROT_TURN_BUS_OUTBOX_DIR is required when turn persistence is enabled")
    directory = Path(configured).expanduser()
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        raise RuntimeError(f"PARROT_TURN_BUS_OUTBOX_DIR is not a writable directory: {directory}")
    return directory


class SqliteDeadLetterStore:
    """Local, durable dead-letter store for retry-exhausted envelopes (spec §8 Q15).

    ``SqliteOutbox`` keeps no dead letters, and ``DLQHandler`` without a DSN persists nothing, so
    envelopes whose handler exhausted its retries are kept here until replayed. One file per host.
    """

    _DDL = (
        "CREATE TABLE IF NOT EXISTS turn_dead_letters ("
        " event_id TEXT PRIMARY KEY, topic TEXT NOT NULL, envelope TEXT NOT NULL, attempts INTEGER NOT NULL,"
        " error TEXT NOT NULL, subscriber_id TEXT, failed_at REAL NOT NULL, replayed_at REAL)"
    )

    def __init__(self, path: Path) -> None:
        self._path = path
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(self._DDL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path), timeout=10)

    def _add_sync(self, envelope: EventEnvelope, attempts: int, error: BaseException, subscriber_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO turn_dead_letters (event_id, topic, envelope, attempts, error, subscriber_id, failed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(event_id) DO UPDATE SET attempts=excluded.attempts, error=excluded.error,"
                " failed_at=excluded.failed_at, replayed_at=NULL",
                (envelope.event_id, envelope.topic, json.dumps(envelope.to_dict(), default=str), attempts,
                 f"{type(error).__name__}: {error}", subscriber_id, time.time()),
            )

    async def add(self, envelope: EventEnvelope, *, attempts: int, error: BaseException, subscriber_id: str) -> None:
        """Persist (or re-open) a dead letter; a replayed envelope that fails again becomes pending again."""
        await asyncio.to_thread(self._add_sync, envelope, attempts, error, subscriber_id)

    def _pending_sync(self, since: Optional[datetime]) -> List[EventEnvelope]:
        sql = "SELECT event_id, envelope FROM turn_dead_letters WHERE replayed_at IS NULL"
        params: tuple = ()
        if since is not None:
            sql += " AND failed_at >= ?"
            params = (since.timestamp(),)
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY failed_at", params).fetchall()
        envelopes: List[EventEnvelope] = []
        for event_id, raw in rows:
            try:
                envelopes.append(EventEnvelope.from_dict(json.loads(raw)))
            except Exception:  # noqa: BLE001 - never log the payload
                logger.error("dead letter %s could not be rebuilt; left pending", event_id)
        return envelopes

    async def pending(self, since: Optional[datetime] = None) -> List[EventEnvelope]:
        """Un-replayed envelopes (optionally ``failed_at >= since``), oldest first."""
        return await asyncio.to_thread(self._pending_sync, since)

    def _mark_sync(self, event_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE turn_dead_letters SET replayed_at=? WHERE event_id=?", (time.time(), event_id))

    async def mark_replayed(self, event_id: str) -> None:
        """Mark a dead letter as replayed (kept for audit, not deleted)."""
        await asyncio.to_thread(self._mark_sync, event_id)

    async def close(self) -> None:
        """No persistent connection is held; present for handle symmetry."""


def _make_dlq_callback(holder: Dict[str, Any]) -> Callable[..., Any]:
    """Late-bound ``on_dlq`` for ``BusCore``: the DLQ object only exists after the bus does."""

    async def _on_dlq(envelope: EventEnvelope, *, attempts: int, error: BaseException, subscriber_id: str) -> None:
        logger.error("turn bus dead letter: event_id=%s topic=%s attempts=%s", envelope.event_id, envelope.topic, attempts)
        dlq = holder.get("dlq")
        if dlq is None:
            logger.error("dead letter %s arrived before the DLQ was bound", envelope.event_id)
            return
        if isinstance(dlq, DLQHandler):
            await dlq.on_dlq(envelope, attempts=attempts, error=error, subscriber_id=subscriber_id)
        else:
            await dlq.add(envelope, attempts=attempts, error=error, subscriber_id=subscriber_id)

    return _on_dlq


def _build_bus(holder: Dict[str, Any]) -> EventBus:
    """Build the consuming Streams bus with its durable outbox (explicit backend: ``channel_prefix`` is ignored)."""
    redis_url = _setting("PARROT_TURN_BUS_REDIS_URL")
    if not redis_url:
        raise RuntimeError("PARROT_TURN_BUS_REDIS_URL is required when turn persistence is enabled")
    outbox = _resolve_outbox_dir() / f"{socket.gethostname()}-{os.getpid()}.db"
    prefix = _setting("PARROT_TURN_BUS_CHANNEL_PREFIX") or "parrot:turns:"
    backend = RedisStreamsBackend(redis_url, stream_prefix=prefix, dedup_prefix=f"{prefix}dedup:", group="parrot-turns")
    return EventBus(
        backend=backend,
        outbox=str(outbox),
        default_backpressure="block",
        on_dlq=_make_dlq_callback(holder),
    )


async def _attach_dlq(bus: Any, holder: Dict[str, Any]) -> Any:
    """Choose Postgres ``DLQHandler`` (DSN set) or the local ``SqliteDeadLetterStore`` and bind it to the callback."""
    dsn = _setting("PARROT_TURN_BUS_DLQ_DSN")
    if dsn:
        dlq: Any = DLQHandler(bus, dsn=dsn)
        await dlq.ensure_table()
    else:
        dlq = SqliteDeadLetterStore(_resolve_outbox_dir() / f"{socket.gethostname()}-dead-letters.db")
        logger.info("PARROT_TURN_BUS_DLQ_DSN is unset: exhausted envelopes are retained in a local SQLite dead-letter store")
    holder["dlq"] = dlq
    return dlq


async def setup_turn_persistence(chat_storage: ChatStorage, *, bus: Any = None) -> TurnPersistence:
    """Build (or accept) the turn bus and subscribe ``ChatStorage``.

    Args:
        chat_storage: The initialised ``ChatStorage``.
        bus: An existing ``EventBus`` (tests / hosts that own their bus); its DLQ is then the caller's.

    Returns:
        A :class:`TurnPersistence` handle.

    Raises:
        RuntimeError: Redis URL or outbox directory is unset / unusable (bus not built).
    """
    holder: Dict[str, Any] = {}
    owns_bus = bus is None
    bus = bus if bus is not None else _build_bus(holder)
    dlq = await _attach_dlq(bus, holder) if owns_bus else None
    ids = [
        bus.core.subscribe(TURN_COMPLETED_TOPIC, chat_storage.handle_turn_completed),
        bus.core.subscribe(CONVERSATION_DELETED_TOPIC, chat_storage.handle_conversation_deleted),
    ]

    async def _publish_deletion(topic: str, payload: Dict[str, Any]) -> None:
        await bus.core.publish(EventEnvelope(topic=topic, payload=payload, source="chat-storage"))

    chat_storage.attach_deletion_publisher(_publish_deletion)
    await bus.connect()
    return TurnPersistence(bus=bus, publisher=BusTurnPublisher(bus), subscription_ids=ids, dlq=dlq)


async def shutdown_turn_persistence(handle: TurnPersistence) -> None:
    """Unsubscribe and close the bus, preserving the outbox. Safe to call twice."""
    for sub_id in list(handle.subscription_ids):
        try:
            handle.bus.core.unsubscribe(sub_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("turn bus unsubscribe failed: %s", exc)
    handle.subscription_ids.clear()
    try:
        await handle.bus.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("turn bus close failed: %s", exc)
    close = getattr(handle.dlq, "close", None)
    if close is not None:
        try:
            await close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("turn bus DLQ close failed: %s", exc)


async def replay_dead_letters(handle: TurnPersistence, *, since: Optional[datetime] = None) -> int:
    """Replay dead letters through the same handlers; ``store_turn`` re-checks tombstones.

    Returns:
        Number of envelopes re-published.

    Raises:
        RuntimeError: The handle has no DLQ (an injected bus).
    """
    dlq = handle.dlq
    if dlq is None:
        raise RuntimeError("this turn bus has no dead-letter store (injected bus)")
    if isinstance(dlq, DLQHandler):
        return int(await dlq.replay(since=since or datetime.fromtimestamp(0, timezone.utc)))
    count = 0
    for envelope in await dlq.pending(since):
        await handle.bus.core.publish(envelope)
        await dlq.mark_replayed(envelope.event_id)
        count += 1
    return count
