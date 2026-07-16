"""DLQ — ``bus.dlq`` terminal topic persisted via asyncdb (FEAT-310, Module 6).

Envelopes that exhaust their retries are handed to
:meth:`DLQHandler.on_dlq` (BusCore's ``on_dlq`` callback), which:

1. republishes the failed envelope on the terminal topic ``bus.dlq``
   (with failure metadata: attempts, last error, failed handler id), and
2. persists it append-only via asyncdb — **`pg` driver, table
   `navigator.evb_dlq`** (spec §8, resolved 2026-07-16) — identically in
   memory and Streams modes (no backend-conditional logic here).

Persistence failures degrade gracefully: log + ``bus.dlq_error``
meta-event, never a raise into the dispatch path (model B). Duplicate
``event_id`` inserts are no-ops (``ON CONFLICT (event_id) DO NOTHING``) —
at-least-once delivery may hand the same envelope twice.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from asyncdb import AsyncDB
from navconfig.logging import logging

from parrot.core.events.bus.core import BusCore
from parrot.core.events.bus.envelope import EventEnvelope, Severity
from parrot.core.events.evb import EventPriority

#: Fully-qualified, schema-qualified DLQ table (FIXED by spec §8).
DLQ_TABLE = "navigator.evb_dlq"

#: Append-only DDL. No TTL column — rows are permanent until replayed or
#: cleaned manually (consistent with append-only audit semantics).
DLQ_DDL = f"""
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS {DLQ_TABLE} (
    event_id       TEXT PRIMARY KEY,
    topic          TEXT NOT NULL,
    payload        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    severity       INTEGER NOT NULL,
    priority       INTEGER NOT NULL,
    source         TEXT,
    correlation_id TEXT,
    trace_context  JSONB,
    metadata       JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    failure_reason TEXT,
    attempts       INTEGER NOT NULL DEFAULT 0,
    replayed_at    TIMESTAMPTZ,
    failed_at      TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_INSERT_SQL = f"""
INSERT INTO {DLQ_TABLE}
    (event_id, topic, payload, severity, priority, source, correlation_id,
     trace_context, metadata, failure_reason, attempts, failed_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
ON CONFLICT (event_id) DO NOTHING
"""

_SELECT_BY_ID_SQL = f"""
SELECT * FROM {DLQ_TABLE}
WHERE event_id = $1 AND replayed_at IS NULL
"""

_SELECT_SINCE_SQL = f"""
SELECT * FROM {DLQ_TABLE}
WHERE failed_at >= $1 AND replayed_at IS NULL
ORDER BY failed_at ASC
"""

_MARK_REPLAYED_SQL = f"""
UPDATE {DLQ_TABLE} SET replayed_at = now() WHERE event_id = $1
"""


class DLQHandler:
    """Terminal handler for retry-exhausted envelopes.

    Plug :meth:`on_dlq` into ``BusCore(on_dlq=handler.on_dlq)``.

    Args:
        bus: The BusCore used to republish on ``bus.dlq`` (and for
            :meth:`replay`).
        dsn: Postgres DSN; when ``None``, falls back to
            ``parrot.conf.default_dsn``. A missing DSN disables
            persistence with a loud warning meta-event — it never crashes
            the bus.
        driver: asyncdb driver name (spec-fixed default ``pg``).
    """

    def __init__(
        self,
        bus: BusCore,
        *,
        dsn: Optional[str] = None,
        driver: str = "pg",
    ) -> None:
        self._bus = bus
        self.logger = logging.getLogger("parrot.core.events.bus.dlq")
        if dsn is None:
            # Lazy import — parrot.conf is heavy and env-dependent.
            try:
                from parrot.conf import default_dsn
                dsn = default_dsn
            except Exception:  # noqa: BLE001 — conf may be unavailable
                dsn = None
        self._dsn = dsn
        self._driver = driver
        self._db: Optional[AsyncDB] = None
        self._table_ready = False
        self._ddl_lock = asyncio.Lock()
        if not self._dsn:
            self.logger.warning(
                "DLQ persistence DISABLED: no Postgres DSN configured "
                "(bus.dlq events will not be stored)."
            )

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def ensure_table(self) -> None:
        """Idempotently create ``navigator.evb_dlq`` (once per handler)."""
        if self._table_ready or not self._dsn:
            return
        async with self._ddl_lock:
            if self._table_ready:
                return
            db = self._get_db()
            async with await db.connection() as conn:
                await conn.execute(DLQ_DDL)
            self._table_ready = True

    def _get_db(self) -> AsyncDB:
        """Return the (lazily created) asyncdb handle."""
        if self._db is None:
            self._db = AsyncDB(self._driver, dsn=self._dsn)
        return self._db

    # ------------------------------------------------------------------
    # BusCore DLQ callback
    # ------------------------------------------------------------------

    async def on_dlq(
        self,
        envelope: EventEnvelope,
        *,
        attempts: int,
        error: BaseException,
        subscriber_id: str,
    ) -> None:
        """Handle one retry-exhausted envelope (BusCore ``on_dlq`` hook).

        Republishes on ``bus.dlq`` and persists fire-and-forget. Never
        raises (model B).
        """
        failure = {
            "attempts": attempts,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "failed_subscriber": subscriber_id,
            "original_topic": envelope.topic,
        }
        # 1) Terminal topic republication — severity capped below the
        #    default alert threshold (loop guard, spec §7).
        try:
            dlq_envelope = EventEnvelope(
                topic="bus.dlq",
                payload={"envelope": envelope.to_dict(), "failure": failure},
                source="bus-dlq",
                severity=Severity.WARNING,
                priority=EventPriority.HIGH,
                correlation_id=envelope.correlation_id,
            )
            await self._bus.publish(dlq_envelope)
        except Exception:  # noqa: BLE001 — never raise into dispatch
            self.logger.exception("bus.dlq republication failed")

        # 2) Fire-and-forget persistence (dispatch path never waits on pg).
        if self._dsn:
            asyncio.create_task(
                self._persist(envelope, failure),
                name=f"bus-dlq-persist.{envelope.event_id}",
            )

    async def _persist(
        self, envelope: EventEnvelope, failure: dict[str, Any]
    ) -> None:
        """Write one DLQ row; failures log + emit a meta-event only."""
        try:
            await self.ensure_table()
            db = self._get_db()
            async with await db.connection() as conn:
                await conn.execute(
                    _INSERT_SQL,
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
                    f"{failure['error_type']}: {failure['error_message']}",
                    failure["attempts"],
                    datetime.now(timezone.utc),
                )
        except Exception as exc:  # noqa: BLE001 — model B
            self.logger.exception(
                "DLQ persistence failed for %s", envelope.event_id
            )
            try:
                await self._bus.publish(
                    EventEnvelope(
                        topic="bus.dlq_error",
                        payload={
                            "event_id": envelope.event_id,
                            "error": str(exc),
                        },
                        source="bus-dlq",
                        severity=Severity.WARNING,
                    )
                )
            except Exception:  # noqa: BLE001
                self.logger.debug("bus.dlq_error meta-event dropped")

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    async def replay(
        self,
        event_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> int:
        """Re-publish stored envelopes to their ORIGINAL topics.

        Args:
            event_id: Replay a single stored envelope.
            since: Replay every un-replayed envelope with
                ``failed_at >= since``.

        Returns:
            Number of envelopes re-published (each marked replayed).

        Raises:
            ValueError: If neither/both selectors are provided, or no DSN
                is configured.
        """
        if (event_id is None) == (since is None):
            raise ValueError("replay() needs exactly one of event_id/since")
        if not self._dsn:
            raise ValueError("DLQ persistence is disabled (no DSN)")

        await self.ensure_table()
        db = self._get_db()
        async with await db.connection() as conn:
            if event_id is not None:
                result, error = await conn.query(_SELECT_BY_ID_SQL, event_id)
            else:
                result, error = await conn.query(_SELECT_SINCE_SQL, since)
            if error:
                raise RuntimeError(f"DLQ replay query failed: {error}")
            rows = result or []
            replayed = 0
            for row in rows:
                envelope = self._row_to_envelope(dict(row))
                await self._bus.publish(envelope)
                await conn.execute(_MARK_REPLAYED_SQL, envelope.event_id)
                replayed += 1
        return replayed

    @staticmethod
    def _row_to_envelope(row: dict[str, Any]) -> EventEnvelope:
        """Rebuild an :class:`EventEnvelope` from a DLQ row."""
        def _json(value: Any) -> Any:
            return json.loads(value) if isinstance(value, str) else value

        failed_at = row["failed_at"]
        if isinstance(failed_at, str):
            failed_at = datetime.fromisoformat(failed_at)
        if failed_at.tzinfo is None:
            failed_at = failed_at.replace(tzinfo=timezone.utc)
        return EventEnvelope(
            topic=row["topic"],
            payload=_json(row.get("payload")) or {},
            event_id=row["event_id"],
            timestamp=failed_at,
            source=row.get("source"),
            severity=Severity(row.get("severity", Severity.INFO.value)),
            priority=EventPriority(
                row.get("priority", EventPriority.NORMAL.value)
            ),
            correlation_id=row.get("correlation_id"),
            trace_context=_json(row.get("trace_context")),
            metadata=_json(row.get("metadata")) or {},
        )
