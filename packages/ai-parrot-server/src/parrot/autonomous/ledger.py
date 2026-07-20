"""Typed Event Ledger for the autonomous harness.

FEAT-212 — Typed Event Ledger & Crash Resume.

Provides:
- ``LedgerEvent``: Pydantic wrapper for a persisted lifecycle event.
- ``LedgerConfig``: Configuration for the recorder and backend.
- ``AgentLedgerState``: Read projection for /health and /status.
- ``IncompleteExecution``: Read projection for crash-resume detection.
- ``LEDGER_DDL``: Idempotent DDL for the ``harness_ledger`` Postgres table.
- ``EventLedger`` (ABC): Abstract interface for the ledger store.
- ``PostgresLedgerBackend``: Postgres append-only implementation.
- ``InMemoryLedgerBackend``: In-memory backend for testing (no DB required).
- ``LedgerRecorder``: Subscribes to the global lifecycle registry and
  persists all events (except filtered ones) via batched async writes.

Usage::

    # Wire up at app startup:
    db = app["database"]
    backend = PostgresLedgerBackend(db)
    await backend.ensure_schema()
    recorder = LedgerRecorder(backend)
    recorder.start()
    # At orchestrator start (opt-in):
    await orchestrator.resume(backend)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from parrot.core.events.lifecycle import LifecycleEvent, get_global_registry

# ---------------------------------------------------------------------------
# DDL — idempotent Postgres schema for the ledger
# ---------------------------------------------------------------------------

LEDGER_DDL: str = """
CREATE TABLE IF NOT EXISTS harness_ledger (
    seq          BIGSERIAL PRIMARY KEY,
    event_id     UUID NOT NULL,
    event_class  TEXT NOT NULL,
    trace_id     TEXT,
    source_type  TEXT,
    source_name  TEXT,
    agent_id     TEXT,
    ts           TIMESTAMPTZ NOT NULL,
    event_data   JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_agent_ts  ON harness_ledger (agent_id, ts);
CREATE INDEX IF NOT EXISTS ix_ledger_trace     ON harness_ledger (trace_id);
CREATE INDEX IF NOT EXISTS ix_ledger_class     ON harness_ledger (event_class);
"""

# Individual DDL statement templates (parameterised by table name at __init__ time).
# Split into separate statements so asyncpg can execute them individually.
_LEDGER_DDL_TEMPLATES: list[str] = [
    (
        "CREATE TABLE IF NOT EXISTS {table} ("
        "seq          BIGSERIAL PRIMARY KEY,"
        " event_id     UUID NOT NULL,"
        " event_class  TEXT NOT NULL,"
        " trace_id     TEXT,"
        " source_type  TEXT,"
        " source_name  TEXT,"
        " agent_id     TEXT,"
        " ts           TIMESTAMPTZ NOT NULL,"
        " event_data   JSONB NOT NULL"
        ")"
    ),
    "CREATE INDEX IF NOT EXISTS ix_{table}_agent_ts ON {table} (agent_id, ts)",
    "CREATE INDEX IF NOT EXISTS ix_{table}_trace    ON {table} (trace_id)",
    "CREATE INDEX IF NOT EXISTS ix_{table}_class    ON {table} (event_class)",
]

# ---------------------------------------------------------------------------
# Opening / closing event classes used to detect incomplete executions
# ---------------------------------------------------------------------------

_OPENING_CLASSES = frozenset({"BeforeInvokeEvent", "BeforeToolCallEvent"})
_CLOSING_CLASSES = frozenset(
    {"AfterInvokeEvent", "InvokeFailedEvent", "AfterToolCallEvent", "ToolCallFailedEvent"}
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class LedgerEvent(BaseModel):
    """Pydantic wrapper for a single persisted lifecycle event.

    Attributes:
        seq: Monotonic sequence number assigned by the store. ``None``
            before the event has been persisted.
        event_id: UUID4 string from ``LifecycleEvent.event_id``.
        event_class: ``type(evt).__name__`` of the original lifecycle event.
        trace_id: ``evt.trace_context.trace_id`` for distributed correlation.
        source_type: Emitter category (``"agent"`` | ``"client"`` | ``"tool"``).
        source_name: Name of the specific emitter.
        agent_id: Agent identifier resolved from ``source_name``.
        timestamp: UTC datetime of the original event.
        event_data: Full JSON-safe dict from ``evt.to_dict()``.
    """

    seq: Optional[int] = None
    event_id: str
    event_class: str
    trace_id: Optional[str] = None
    source_type: str = ""
    source_name: str = ""
    agent_id: Optional[str] = None
    timestamp: datetime
    event_data: dict

    @classmethod
    def from_lifecycle(cls, evt: LifecycleEvent) -> "LedgerEvent":
        """Construct a ``LedgerEvent`` from any ``LifecycleEvent``.

        Uses ``LifecycleEvent.to_dict()`` for JSON-safe serialization.
        ``agent_id`` is resolved from ``source_name`` (simple; can be
        refined later with metadata/trace correlation per spec §8).

        Args:
            evt: A concrete ``LifecycleEvent`` instance (frozen dataclass).

        Returns:
            A new ``LedgerEvent`` ready for persistence (seq is None).
        """
        d = evt.to_dict()
        trace_id: Optional[str] = None
        if evt.trace_context is not None:
            trace_id = evt.trace_context.trace_id
        return cls(
            event_id=evt.event_id,
            event_class=type(evt).__name__,
            trace_id=trace_id,
            source_type=evt.source_type,
            source_name=evt.source_name,
            agent_id=evt.source_name or None,
            timestamp=evt.timestamp,
            event_data=d,
        )


class LedgerConfig(BaseModel):
    """Configuration for the ledger recorder and backend.

    Attributes:
        enabled: Whether the recorder is active.
        exclude_event_classes: Set of ``__name__`` strings to filter out.
            ``ClientStreamChunkEvent`` is excluded by default to avoid
            flooding the ledger with high-frequency stream events.
        batch_size: Maximum number of events to flush per batch iteration.
        table_name: Postgres table name (must match DDL).
    """

    enabled: bool = True
    exclude_event_classes: set[str] = Field(
        default_factory=lambda: {"ClientStreamChunkEvent"}
    )
    batch_size: int = Field(50, ge=1)
    table_name: str = "harness_ledger"

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, v: str) -> str:
        """Ensure table_name is a safe SQL identifier (alphanumeric + underscore).

        Args:
            v: The proposed table name.

        Returns:
            The validated table name, unchanged.

        Raises:
            ValueError: If the table name contains characters that would make
                it unsafe to interpolate into a SQL statement.
        """
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", v):
            raise ValueError(
                f"table_name must be a valid SQL identifier, got: {v!r}"
            )
        return v


class AgentLedgerState(BaseModel):
    """Read projection of an agent's recent ledger activity.

    Consumed by ``/health`` and ``/status`` endpoints (FEAT-210).

    Attributes:
        agent_id: The agent whose state this describes.
        last_activity: Timestamp of the most recent ledger entry for this agent.
        open_executions: Count of traces with an opening event but no closing event.
        closed_executions: Count of traces with both opening and closing events.
        total_events: Total number of ledger rows for this agent.
    """

    agent_id: str
    last_activity: Optional[datetime] = None
    open_executions: int = 0
    closed_executions: int = 0
    total_events: int = 0


class IncompleteExecution(BaseModel):
    """An execution that was opened (Before*) but never closed (After*/Failed*).

    Populated by ``EventLedger.find_incomplete()`` and consumed by
    ``AutonomousOrchestrator.resume()`` to re-enqueue stalled work.

    Attributes:
        trace_id: Distributed trace ID that identifies this execution.
        agent_id: Agent that started the execution (may be None).
        event_class: Class name of the opening event.
        event_data: ``event_data`` dict from the opening event.
        timestamp: When the opening event was recorded.
        last_seq: Sequence number of the most recent event in this trace.
    """

    trace_id: str
    agent_id: Optional[str] = None
    event_class: str = ""
    event_data: dict = Field(default_factory=dict)
    timestamp: datetime
    last_seq: int = 0


# ---------------------------------------------------------------------------
# EventLedger ABC
# ---------------------------------------------------------------------------


class EventLedger(ABC):
    """Abstract interface for the persistent event ledger.

    All writes are append-only. Implementations MUST guarantee a
    monotonically increasing ``seq`` on every ``append`` call.
    """

    @abstractmethod
    async def append(self, event: LedgerEvent) -> int:
        """Persist a ledger event and return its assigned ``seq``.

        Args:
            event: A ``LedgerEvent`` (``seq`` may be None before this call).

        Returns:
            The monotonic sequence number assigned to the persisted row.
        """
        ...

    @abstractmethod
    async def read(
        self,
        *,
        agent_id: Optional[str] = None,
        since_seq: Optional[int] = None,
        event_class: Optional[str] = None,
        limit: int = 100,
    ) -> list[LedgerEvent]:
        """Return ledger events matching the given filters.

        Args:
            agent_id: Filter to events from this agent (None = all agents).
            since_seq: Only return events with ``seq > since_seq``.
            event_class: Filter to events with this ``event_class`` name.
            limit: Maximum number of results (ordered by seq ascending).

        Returns:
            List of ``LedgerEvent`` objects ordered by ``seq`` ascending.
        """
        ...

    @abstractmethod
    async def last_state(self, agent_id: str) -> AgentLedgerState:
        """Return the latest activity projection for an agent.

        Args:
            agent_id: The agent to query.

        Returns:
            An ``AgentLedgerState`` with last_activity, open/closed counts.
        """
        ...

    @abstractmethod
    async def find_incomplete(self) -> list[IncompleteExecution]:
        """Detect executions with an opening event but no matching closing event.

        An "opening" event is one of: ``BeforeInvokeEvent``, ``BeforeToolCallEvent``.
        A "closing" event is one of: ``AfterInvokeEvent``, ``InvokeFailedEvent``,
        ``AfterToolCallEvent``, ``ToolCallFailedEvent``.

        Correlation is by ``trace_id``: a trace is incomplete if it has at least
        one opening class and no closing class in the ledger.

        Returns:
            List of ``IncompleteExecution`` objects, one per open trace.
        """
        ...


# ---------------------------------------------------------------------------
# PostgresLedgerBackend
# ---------------------------------------------------------------------------


class PostgresLedgerBackend(EventLedger):
    """Postgres append-only implementation of ``EventLedger``.

    Uses the ``asyncdb`` pattern (``app["database"]`` / ``db.acquire()``)
    consistent with the rest of the server layer.

    Args:
        db: An asyncdb database instance (``app["database"]``).
        config: Optional ``LedgerConfig``; defaults are used if not provided.
    """

    def __init__(self, db: Any, *, config: Optional[LedgerConfig] = None) -> None:
        """Initialise the Postgres ledger backend.

        Args:
            db: asyncdb database instance obtained from ``app["database"]``.
            config: Optional ``LedgerConfig`` with table name and batch size.
        """
        self._db = db
        self._config = config or LedgerConfig()
        # Validated identifier — safe to interpolate into SQL f-strings.
        self._table: str = self._config.table_name
        # Build DDL statements parameterised with the configured table name.
        self._ddl_statements: list[str] = [
            stmt.format(table=self._table) for stmt in _LEDGER_DDL_TEMPLATES
        ]
        self.logger = logging.getLogger(__name__)

    async def ensure_schema(self) -> None:
        """Execute the idempotent DDL statements against the database.

        Each statement is executed individually so that asyncpg (which does
        not support multi-statement strings) can handle them correctly.
        Safe to call multiple times (``CREATE TABLE / INDEX IF NOT EXISTS``).
        """
        async with await self._db.acquire() as conn:
            for stmt in self._ddl_statements:
                await conn.execute(stmt)
        self.logger.info("Ledger schema ensured (table: %s)", self._table)

    async def append(self, event: LedgerEvent) -> int:
        """Insert an event row and return the assigned ``BIGSERIAL`` seq.

        Args:
            event: The ``LedgerEvent`` to persist.

        Returns:
            The monotonically increasing sequence number from Postgres.
        """
        sql = f"""
            INSERT INTO {self._table}
                (event_id, event_class, trace_id, source_type, source_name,
                 agent_id, ts, event_data)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING seq
        """
        event_data_json = json.dumps(event.event_data)
        async with await self._db.acquire() as conn:
            seq = await conn.fetchval(
                sql,
                event.event_id,
                event.event_class,
                event.trace_id,
                event.source_type,
                event.source_name,
                event.agent_id,
                event.timestamp,
                event_data_json,
            )
        return seq

    async def read(
        self,
        *,
        agent_id: Optional[str] = None,
        since_seq: Optional[int] = None,
        event_class: Optional[str] = None,
        limit: int = 100,
    ) -> list[LedgerEvent]:
        """Return filtered ledger events ordered by seq.

        Args:
            agent_id: Filter rows to this agent_id.
            since_seq: Return only rows with seq > since_seq.
            event_class: Filter rows to this event_class.
            limit: Maximum number of rows to return.

        Returns:
            A list of ``LedgerEvent`` objects ordered by seq ascending.
        """
        conditions: list[str] = []
        args: list[Any] = []
        idx = 1

        if agent_id is not None:
            conditions.append(f"agent_id = ${idx}")
            args.append(agent_id)
            idx += 1
        if since_seq is not None:
            conditions.append(f"seq > ${idx}")
            args.append(since_seq)
            idx += 1
        if event_class is not None:
            conditions.append(f"event_class = ${idx}")
            args.append(event_class)
            idx += 1

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT seq, event_id, event_class, trace_id, source_type,
                   source_name, agent_id, ts, event_data
            FROM {self._table}
            {where}
            ORDER BY seq ASC
            LIMIT ${idx}
        """
        args.append(limit)

        async with await self._db.acquire() as conn:
            rows = await conn.fetch(sql, *args)

        result: list[LedgerEvent] = []
        for row in rows:
            result.append(
                LedgerEvent(
                    seq=row["seq"],
                    event_id=str(row["event_id"]),
                    event_class=row["event_class"],
                    trace_id=row["trace_id"],
                    source_type=row["source_type"] or "",
                    source_name=row["source_name"] or "",
                    agent_id=row["agent_id"],
                    timestamp=row["ts"],
                    event_data=row["event_data"] if isinstance(row["event_data"], dict) else json.loads(row["event_data"]),
                )
            )
        return result

    async def last_state(self, agent_id: str) -> AgentLedgerState:
        """Return the latest activity projection for an agent.

        Args:
            agent_id: The agent to query.

        Returns:
            ``AgentLedgerState`` with last_activity and execution counts.
        """
        sql_total = f"SELECT COUNT(*), MAX(ts) FROM {self._table} WHERE agent_id = $1"
        sql_traces = f"""
            SELECT trace_id,
                   bool_or(event_class = ANY($2::text[])) AS has_open,
                   bool_or(event_class = ANY($3::text[])) AS has_close
            FROM {self._table}
            WHERE agent_id = $1 AND trace_id IS NOT NULL
            GROUP BY trace_id
        """
        opening = list(_OPENING_CLASSES)
        closing = list(_CLOSING_CLASSES)

        async with await self._db.acquire() as conn:
            total_row = await conn.fetchrow(sql_total, agent_id)
            trace_rows = await conn.fetch(sql_traces, agent_id, opening, closing)

        total = total_row[0] if total_row else 0
        last_activity = total_row[1] if total_row else None

        open_count = 0
        closed_count = 0
        for tr in trace_rows:
            if tr["has_open"] and not tr["has_close"]:
                open_count += 1
            elif tr["has_open"] and tr["has_close"]:
                closed_count += 1

        return AgentLedgerState(
            agent_id=agent_id,
            last_activity=last_activity,
            open_executions=open_count,
            closed_executions=closed_count,
            total_events=total,
        )

    async def find_incomplete(self) -> list[IncompleteExecution]:
        """Find traces with an opening event but no closing event.

        Returns:
            ``IncompleteExecution`` objects for each open trace.
        """
        sql = f"""
            SELECT
                trace_id,
                MAX(seq)          AS last_seq,
                MAX(agent_id)     AS agent_id,
                bool_or(event_class = ANY($1::text[])) AS has_open,
                bool_or(event_class = ANY($2::text[])) AS has_close,
                MIN(ts)           AS first_ts,
                (array_agg(event_class ORDER BY seq ASC))[1] AS open_class,
                (array_agg(event_data ORDER BY seq ASC))[1]  AS open_data
            FROM {self._table}
            WHERE trace_id IS NOT NULL
            GROUP BY trace_id
            HAVING
                bool_or(event_class = ANY($1::text[])) = true
                AND bool_or(event_class = ANY($2::text[])) = false
        """
        opening = list(_OPENING_CLASSES)
        closing = list(_CLOSING_CLASSES)

        async with await self._db.acquire() as conn:
            rows = await conn.fetch(sql, opening, closing)

        result: list[IncompleteExecution] = []
        for row in rows:
            raw = row["open_data"]
            event_data = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
            result.append(
                IncompleteExecution(
                    trace_id=row["trace_id"],
                    agent_id=row["agent_id"],
                    event_class=row["open_class"] or "",
                    event_data=event_data,
                    timestamp=row["first_ts"],
                    last_seq=row["last_seq"] or 0,
                )
            )
        return result


# ---------------------------------------------------------------------------
# InMemoryLedgerBackend (for CI / tests — no Postgres required)
# ---------------------------------------------------------------------------


class InMemoryLedgerBackend(EventLedger):
    """In-memory ``EventLedger`` implementation for use in tests and CI.

    Replicates the exact semantics of ``PostgresLedgerBackend``:
    monotonic ``seq``, correct filtering, ``find_incomplete`` logic.

    No external dependencies required.
    """

    def __init__(self) -> None:
        """Initialise the in-memory backend with an empty store."""
        self._events: list[LedgerEvent] = []
        self._next_seq: int = 1
        self.logger = logging.getLogger(__name__)

    async def append(self, event: LedgerEvent) -> int:
        """Assign a monotonic seq and store the event in memory.

        Args:
            event: The ``LedgerEvent`` to persist.

        Returns:
            The assigned sequence number.
        """
        seq = self._next_seq
        self._next_seq += 1
        stored = event.model_copy(update={"seq": seq})
        self._events.append(stored)
        return seq

    async def read(
        self,
        *,
        agent_id: Optional[str] = None,
        since_seq: Optional[int] = None,
        event_class: Optional[str] = None,
        limit: int = 100,
    ) -> list[LedgerEvent]:
        """Return filtered events ordered by seq ascending.

        Args:
            agent_id: Filter to this agent_id (None = all).
            since_seq: Return only events with seq > since_seq.
            event_class: Filter to this event_class.
            limit: Maximum number of results.

        Returns:
            Filtered and limited list of ``LedgerEvent`` objects.
        """
        result = self._events
        if agent_id is not None:
            result = [e for e in result if e.agent_id == agent_id]
        if since_seq is not None:
            result = [e for e in result if (e.seq or 0) > since_seq]
        if event_class is not None:
            result = [e for e in result if e.event_class == event_class]
        return list(result[:limit])

    async def last_state(self, agent_id: str) -> AgentLedgerState:
        """Compute the activity projection from in-memory events.

        Args:
            agent_id: The agent to query.

        Returns:
            ``AgentLedgerState`` with counts derived from stored events.
        """
        agent_events = [e for e in self._events if e.agent_id == agent_id]
        if not agent_events:
            return AgentLedgerState(agent_id=agent_id)

        last_activity = max(e.timestamp for e in agent_events)
        total = len(agent_events)

        # Group by trace_id to count open/closed executions
        trace_opens: dict[str, bool] = {}
        trace_closes: dict[str, bool] = {}
        for evt in agent_events:
            if evt.trace_id is None:
                continue
            if evt.event_class in _OPENING_CLASSES:
                trace_opens[evt.trace_id] = True
            if evt.event_class in _CLOSING_CLASSES:
                trace_closes[evt.trace_id] = True

        open_count = sum(
            1 for tid in trace_opens if tid not in trace_closes
        )
        closed_count = sum(
            1 for tid in trace_opens if tid in trace_closes
        )

        return AgentLedgerState(
            agent_id=agent_id,
            last_activity=last_activity,
            open_executions=open_count,
            closed_executions=closed_count,
            total_events=total,
        )

    async def find_incomplete(self) -> list[IncompleteExecution]:
        """Find traces with an opening event but no closing event.

        Returns:
            ``IncompleteExecution`` objects for each unclosed trace.
        """
        # Build per-trace sets
        trace_opens: dict[str, LedgerEvent] = {}   # first opening event per trace
        trace_closes: set[str] = set()
        trace_last_seq: dict[str, int] = {}

        for evt in self._events:
            if evt.trace_id is None:
                continue
            if evt.event_class in _OPENING_CLASSES:
                # Only record first opening
                if evt.trace_id not in trace_opens:
                    trace_opens[evt.trace_id] = evt
            if evt.event_class in _CLOSING_CLASSES:
                trace_closes.add(evt.trace_id)
            # Track last seq per trace
            seq = evt.seq or 0
            if seq > trace_last_seq.get(evt.trace_id, 0):
                trace_last_seq[evt.trace_id] = seq

        result: list[IncompleteExecution] = []
        for trace_id, opening_evt in trace_opens.items():
            if trace_id not in trace_closes:
                result.append(
                    IncompleteExecution(
                        trace_id=trace_id,
                        agent_id=opening_evt.agent_id,
                        event_class=opening_evt.event_class,
                        event_data=opening_evt.event_data,
                        timestamp=opening_evt.timestamp,
                        last_seq=trace_last_seq.get(trace_id, 0),
                    )
                )
        return result


# ---------------------------------------------------------------------------
# LedgerRecorder — global lifecycle event subscriber
# ---------------------------------------------------------------------------


class LedgerRecorder:
    """Subscribe to the global lifecycle registry and persist all events.

    Uses an internal ``asyncio.Queue`` and a background flush task to avoid
    blocking the agent hot-path. Events filtered by ``where`` are never
    enqueued, so ``ClientStreamChunkEvent`` incurs zero overhead.

    One ``LedgerRecorder`` per process — duplicate instances cause duplicate
    ledger rows.

    Args:
        ledger: An ``EventLedger`` backend instance.
        config: Optional ``LedgerConfig``; defaults are used if not provided.
    """

    def __init__(
        self,
        ledger: EventLedger,
        *,
        config: Optional[LedgerConfig] = None,
    ) -> None:
        """Initialise the recorder.

        Args:
            ledger: The ``EventLedger`` to append events to.
            config: Optional ``LedgerConfig`` for filtering and batch size.
        """
        self._ledger = ledger
        self._config = config or LedgerConfig()
        self._subscription_id: Optional[str] = None
        self._queue: asyncio.Queue[LedgerEvent] = asyncio.Queue()
        self._flush_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self.logger = logging.getLogger(__name__)

    def start(self) -> None:
        """Subscribe to the global registry and start the background flush task.

        Must be called from within a running asyncio event loop.

        Raises a ``RuntimeWarning`` (via :func:`warnings.warn`) if called on
        an already-started instance to prevent duplicate ledger rows.
        """
        if self._subscription_id is not None:
            import warnings
            warnings.warn(
                "LedgerRecorder.start() called on an already-started instance. "
                "Duplicate instances cause duplicate ledger rows. "
                "Call stop() first.",
                RuntimeWarning,
                stacklevel=2,
            )
            return
        exclude = self._config.exclude_event_classes
        registry = get_global_registry()
        self._subscription_id = registry.subscribe(
            LifecycleEvent,
            self.on_event,
            where=lambda e: type(e).__name__ not in exclude,
        )
        self._flush_task = asyncio.create_task(self._flush_loop())
        self.logger.info(
            "LedgerRecorder started (sub_id=%s, excludes=%s)",
            self._subscription_id,
            exclude,
        )

    async def stop(self) -> None:
        """Unsubscribe from the global registry and await the flush task.

        Making ``stop`` async allows the flush loop's shutdown drain (which
        calls ``await self._ledger.append(...)`` for each remaining event) to
        complete before this method returns — guaranteeing no events are lost
        on graceful shutdown.
        """
        if self._subscription_id:
            get_global_registry().unsubscribe(self._subscription_id)
            self.logger.info("LedgerRecorder unsubscribed (sub_id=%s)", self._subscription_id)
            self._subscription_id = None
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

    async def on_event(self, evt: LifecycleEvent) -> None:
        """Convert a lifecycle event to a ``LedgerEvent`` and enqueue it.

        This is the async callback registered with ``EventRegistry.subscribe``.
        It returns immediately after putting the event on the queue — the
        actual persistence happens in the background ``_flush_loop``.

        Args:
            evt: Any ``LifecycleEvent`` that passed the ``where`` filter.
        """
        le = LedgerEvent.from_lifecycle(evt)
        await self._queue.put(le)

    async def _flush_loop(self) -> None:
        """Background task: drain the queue in batches and persist to the ledger.

        Waits for at least one event, then greedily drains up to
        ``config.batch_size`` additional events without blocking, and
        calls ``ledger.append`` for each. Exceptions per-event are logged
        and do not interrupt the loop.
        """
        while True:
            try:
                batch: list[LedgerEvent] = []
                # Block until at least one event is available
                batch.append(await self._queue.get())
                # Greedily drain up to batch_size - 1 more without blocking
                while len(batch) < self._config.batch_size:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                # Persist the batch
                for event in batch:
                    try:
                        await self._ledger.append(event)
                    except Exception:
                        self.logger.exception(
                            "LedgerRecorder: failed to append event (class=%s)",
                            event.event_class,
                        )
            except asyncio.CancelledError:
                # Drain remaining events before shutdown to avoid data loss.
                remaining: list[LedgerEvent] = []
                while True:
                    try:
                        remaining.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                for event in remaining:
                    try:
                        await self._ledger.append(event)
                    except Exception:
                        self.logger.exception(
                            "LedgerRecorder: failed to flush event on shutdown (class=%s)",
                            event.event_class,
                        )
                self.logger.debug(
                    "LedgerRecorder flush loop cancelled; drained %d events",
                    len(remaining),
                )
                break
            except Exception:
                self.logger.exception("LedgerRecorder flush loop unexpected error")
