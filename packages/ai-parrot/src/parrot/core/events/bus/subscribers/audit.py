"""AuditSubscriber — append-only audit trail of bus traffic (FEAT-310).

Module 10 (spec §3, Phase 3). Subscribes to configurable topic patterns
(default ``*`` minus ``bus.*`` internals) and persists every matching
envelope append-only via asyncdb (``pg`` driver, table
``navigator.evb_audit`` — naming aligned with ``navigator.evb_dlq`` from
TASK-1788; same DDL/``ensure_table()`` pattern).

Writes are batched (size N or T seconds, whichever first) through an
internal bounded queue so audit keeps up under load. The subscriber NEVER
applies backpressure to the bus: on overload the oldest buffered rows are
dropped and counted (``dropped`` in :meth:`stats`, plus a warning log).
Persistence failures are logged only (model B). No TTL — audit rows are
permanent (consistent with the resolved DLQ decision).
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any, Optional

from asyncdb import AsyncDB
from navconfig.logging import logging

from parrot.core.events.bus.core import BusCore
from parrot.core.events.bus.envelope import EventEnvelope

#: Fully-qualified audit table (aligned with navigator.evb_dlq).
AUDIT_TABLE = "navigator.evb_audit"

#: Append-only DDL — no TTL/expires_at, rows are permanent.
AUDIT_DDL = f"""
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
    id             BIGSERIAL PRIMARY KEY,
    event_id       TEXT NOT NULL,
    topic          TEXT NOT NULL,
    payload        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    severity       INTEGER NOT NULL,
    priority       INTEGER NOT NULL,
    source         TEXT,
    correlation_id TEXT,
    trace_context  JSONB,
    metadata       JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    event_ts       TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_INSERT_SQL = f"""
INSERT INTO {AUDIT_TABLE}
    (event_id, topic, payload, severity, priority, source, correlation_id,
     trace_context, metadata, event_ts)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
"""


class AuditSubscriber:
    """Append-only bus audit trail persisted via asyncdb.

    Args:
        dsn: Postgres DSN; falls back to ``parrot.conf.default_dsn``. A
            missing DSN disables auditing with a loud warning (same
            degrade rule as the DLQ) — never crashes the bus.
        driver: asyncdb driver name (default ``pg``).
        pattern: Topic glob to audit (default ``*``).
        include_bus_internal: Audit internal ``bus.*`` topics too
            (default ``False`` — avoids self-amplification).
        batch_size: Rows per flush (flush fires at this size).
        flush_interval: Max seconds between flushes.
        queue_size: Bound of the internal buffer; overflow drops oldest.
    """

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        driver: str = "pg",
        pattern: str = "*",
        include_bus_internal: bool = False,
        batch_size: int = 100,
        flush_interval: float = 1.0,
        queue_size: int = 10_000,
    ) -> None:
        self.logger = logging.getLogger("parrot.core.events.bus.subscribers.audit")
        if dsn is None:
            try:
                from parrot.conf import default_dsn
                dsn = default_dsn
            except Exception:  # noqa: BLE001 — conf may be unavailable
                dsn = None
        self._dsn = dsn
        self._driver = driver
        self._pattern = pattern
        self._include_bus_internal = include_bus_internal
        self._batch_size = max(1, batch_size)
        self._flush_interval = flush_interval
        self._queue_size = queue_size

        self._buffer: deque[tuple[Any, ...]] = deque()
        self._flush_wakeup = asyncio.Event()
        self._flush_task: Optional[asyncio.Task[None]] = None
        self._db: Optional[AsyncDB] = None
        self._table_ready = False
        self._ddl_lock = asyncio.Lock()
        self._running = False
        self._subscription_id: Optional[str] = None
        self._dropped = 0
        self._persisted = 0
        if not self._dsn:
            self.logger.warning(
                "Audit persistence DISABLED: no Postgres DSN configured "
                "(bus traffic will not be audited)."
            )

    # ------------------------------------------------------------------
    # Bus wiring / lifecycle
    # ------------------------------------------------------------------

    def attach(self, bus: BusCore) -> Optional[str]:
        """Subscribe on *bus* and start the flush task.

        Args:
            bus: The BusCore to audit — or the ``EventBus`` facade
                (resolved via its ``.core`` property).

        Returns:
            The subscriber id, or ``None`` when auditing is disabled.
        """
        core: BusCore = getattr(bus, "core", bus)
        if not self._dsn:
            return None
        self._running = True
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(
                self._run_flusher(), name="bus-audit-flusher"
            )
        self._subscription_id = core.subscribe(self._pattern, self._on_envelope)
        return self._subscription_id

    def detach(self, bus: BusCore) -> bool:
        """Remove the subscription (flush task keeps draining until close)."""
        core: BusCore = getattr(bus, "core", bus)
        if self._subscription_id is None:
            return False
        removed = core.unsubscribe(self._subscription_id)
        self._subscription_id = None
        return removed

    async def close(self) -> None:
        """Stop the flusher and flush every remaining buffered row."""
        self._running = False
        self._flush_wakeup.set()
        if self._flush_task is not None:
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self._flush()  # final drain

    @property
    def stats(self) -> dict[str, int]:
        """Return audit throughput counters."""
        return {
            "persisted": self._persisted,
            "dropped": self._dropped,
            "buffered": len(self._buffer),
        }

    # ------------------------------------------------------------------
    # Envelope handling
    # ------------------------------------------------------------------

    async def _on_envelope(self, envelope: EventEnvelope) -> None:
        """Buffer one envelope (never blocks, never raises)."""
        try:
            if (
                envelope.topic.startswith("bus.")
                and not self._include_bus_internal
            ):
                return
            if len(self._buffer) >= self._queue_size:
                self._buffer.popleft()  # drop-oldest — never backpressure
                self._dropped += 1
                if self._dropped % 100 == 1:
                    self.logger.warning(
                        "Audit buffer overloaded — %d rows dropped so far",
                        self._dropped,
                    )
            self._buffer.append(self._row_for(envelope))
            if len(self._buffer) >= self._batch_size:
                self._flush_wakeup.set()
        except Exception:  # noqa: BLE001 — model B
            self.logger.exception("Audit buffering failed for %s", envelope.topic)

    @staticmethod
    def _row_for(envelope: EventEnvelope) -> tuple[Any, ...]:
        """Build the INSERT parameter tuple for one envelope."""
        return (
            envelope.event_id,
            envelope.topic,
            json.dumps(envelope.payload),
            envelope.severity.value,
            envelope.priority.value,
            envelope.source,
            envelope.correlation_id,
            json.dumps(envelope.trace_context)
            if envelope.trace_context is not None
            else None,
            json.dumps(envelope.metadata),
            envelope.timestamp,
        )

    # ------------------------------------------------------------------
    # Flushing
    # ------------------------------------------------------------------

    async def _run_flusher(self) -> None:
        """Flush on size (wakeup event) or interval, whichever first."""
        while self._running:
            try:
                await asyncio.wait_for(
                    self._flush_wakeup.wait(), timeout=self._flush_interval
                )
            except (asyncio.TimeoutError, TimeoutError):
                pass
            self._flush_wakeup.clear()
            await self._flush()

    async def _flush(self) -> None:
        """Persist the current buffer in one connection round (batched)."""
        if not self._buffer or not self._dsn:
            return
        rows: list[tuple[Any, ...]] = []
        while self._buffer and len(rows) < self._batch_size:
            rows.append(self._buffer.popleft())
        try:
            await self._ensure_table()
            db = self._get_db()
            async with await db.connection() as conn:
                for row in rows:
                    await conn.execute(_INSERT_SQL, *row)
            self._persisted += len(rows)
        except Exception:  # noqa: BLE001 — model B, audit never raises
            self.logger.exception(
                "Audit flush failed — %d rows lost", len(rows)
            )
        # More than one batch buffered? Keep draining promptly.
        if len(self._buffer) >= self._batch_size:
            self._flush_wakeup.set()

    # ------------------------------------------------------------------
    # Storage plumbing (mirrors dlq.py)
    # ------------------------------------------------------------------

    async def _ensure_table(self) -> None:
        """Idempotently create ``navigator.evb_audit``."""
        if self._table_ready:
            return
        async with self._ddl_lock:
            if self._table_ready:
                return
            db = self._get_db()
            async with await db.connection() as conn:
                await conn.execute(AUDIT_DDL)
            self._table_ready = True

    def _get_db(self) -> AsyncDB:
        """Return the (lazily created) asyncdb handle."""
        if self._db is None:
            self._db = AsyncDB(self._driver, dsn=self._dsn)
        return self._db
