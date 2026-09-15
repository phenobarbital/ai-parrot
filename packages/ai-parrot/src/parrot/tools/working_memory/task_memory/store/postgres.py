"""PostgreSQL backing for durable task memory (FEAT-538, Delivery B).

This module owns three things, and deliberately not a fourth:

1. **The migration** — reading, parsing and explicitly applying
   ``migrations/001_task_memory.sql``, plus verifying that a database has
   the shape the code expects before anything touches it.
2. **The connection pool lifecycle** — created lazily, so importing this
   module (or running the in-memory backend) never pays for ``asyncpg``.
3. **The shared transaction coordinator** — one connection that the task
   store and the artifact store both enlist in, because durable artifact
   publication must commit the alias/version index, the evidence rows and
   the ``artifact_registered`` journal event together. Two unrelated pool
   transactions would let a crash between them publish a storage
   reference whose bytes or whose journal entry never existed.

4. **The durable journal and reducer projections** — the
   append protocol below, which must be *behaviourally identical* to
   :class:`~.memory.InMemoryTaskMemoryStore` (AC2). Where the two could
   differ, this module follows the in-memory store's decisions rather
   than inventing its own, and the shared conformance suite is run
   against both.

5. **The durable artifact store** — :class:`PostgresArtifactStore`,
   which owns aliases, versions and evidence pins. It lives here rather
   than in its own module precisely because it must share this module's
   pool and transaction coordinator: an artifact's index rows, its
   evidence rows and its ``artifact_registered`` journal event have to
   commit on ONE connection or not at all.

**The append protocol** (spec §2 Persistence and Recovery) is one
transaction, in this order:

1. ``INSERT ... ON CONFLICT DO NOTHING`` / ``SELECT ... FOR UPDATE`` the
   task row. The row lock is what serializes appends to the *same* task
   while letting different tasks proceed concurrently — PostgreSQL does
   the serialization the in-memory store gets from a per-task
   ``asyncio.Lock``.
2. Verify scope.
3. Classify by ``event_id`` — **before** the revision check, so a caller
   retrying a batch that in fact committed gets a no-op rather than a
   conflict it cannot resolve.
4. Check ``expected_revision``.
5. Check capacity.
6. Reduce into a **local** variable, allocating contiguous sequences.
7. Insert the journal rows, update the projection, and commit.

Steps 2–6 write nothing, so "a rejected command changes nothing" holds
both by construction and, for anything that escapes it, by the
transaction rolling back.

.. warning::

   ``asyncpg`` is imported **lazily**, inside the functions that need a
   connection. Importing it at module load would mean a deployment
   without the PostgreSQL extra could not even import the task-memory
   package, and the in-memory backend would pay for a driver it never
   uses. There is a test asserting this.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, FrozenSet, List, Optional, Sequence, Tuple

from parrot.interfaces.artifact_store import ArtifactPage, PayloadRefusal, PayloadResult
from parrot.interfaces.task_memory import (
    GOAL_PREVIEW_CHARS,
    AppendResult,
    EventPage,
    TaskPage,
    TaskSnapshot,
    TaskSummary,
)

from ..config import TaskMemoryConfig
from ..models import (
    Actor,
    CallOutcome,
    ArtifactAvailability,
    ArtifactDescriptor,
    ArtifactKind,
    ArtifactPayload,
    Attribution,
    CursorError,
    EventType,
    EvidenceRef,
    JournalEvent,
    LimitExceeded,
    Limits,
    ReducerError,
    RevisionConflict,
    ScopeViolation,
    TaskLifecyclePayload,
    TaskMemoryUnavailable,
    TaskScope,
    TaskState,
    TaskStatus,
    utc_now,
)
from ..reducer import REDUCER_VERSION, reduce, replay
from ..snapshots import capture_snapshot_async
from ._base import BaseTaskMemoryStore, bounded_limit, decode_cursor, encode_cursor, goal_preview

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import asyncpg

logger = logging.getLogger(__name__)

__all__ = (
    "SCHEMA_NAME",
    "MIGRATION_VERSION",
    "MIGRATION_NAME",
    "REQUIRED_TABLES",
    "migration_path",
    "read_migration",
    "split_migration",
    "PostgresTransaction",
    "PostgresTransactionCoordinator",
    "PostgresTaskMemoryStore",
    "PostgresArtifactStore",
    "TERMINAL_CALL_EVENTS",
    "UnresolvedCall",
    "ReconcileReport",
)

#: The event types that settle a call. A ``tool_started`` with none of
#: these is an *unresolved* call — which is not the same as a dead one.
TERMINAL_CALL_EVENTS: Tuple[str, ...] = (
    EventType.TOOL_SUCCEEDED.value,
    EventType.TOOL_FAILED.value,
    EventType.TOOL_CANCELLED.value,
    EventType.TOOL_OUTCOME_UNKNOWN.value,
)


@dataclass(frozen=True)
class UnresolvedCall:
    """A call the journal shows starting but never finishing.

    Being unresolved says nothing about whether the call is alive. It is
    the *question* recovery asks, not the answer.

    Attributes:
        call_id: The physical attempt.
        tool_name: The tool it dispatched, as recorded at start.
        started_at: When ``tool_started`` was persisted.
        started_seq: Its journal sequence.
        step_id: The step it was attributed to, if any.
        turn_id: The turn it belonged to.
        parent_call_id: Its parent aggregate, if any.
        attempt: The attempt number recorded at start.
        is_aggregate: Whether other calls name it as their parent. An
            aggregate is not a physical attempt and must not be counted
            as one.
    """

    call_id: str
    tool_name: str
    started_at: datetime
    started_seq: int
    step_id: Optional[str] = None
    turn_id: Optional[str] = None
    parent_call_id: Optional[str] = None
    attempt: int = 1
    is_aggregate: bool = False


@dataclass(frozen=True)
class ReconcileReport:
    """What one reconciliation pass actually did.

    Every bucket is reported separately, because "did nothing" has three
    very different meanings and collapsing them would hide the case this
    task exists to protect.

    Attributes:
        scanned: Unresolved calls considered.
        reconciled: Calls newly recorded as ``tool_outcome_unknown``.
        alive: Calls skipped because their owner still holds them.
        unknown_liveness: Calls skipped because liveness could not be
            determined. **Not** reconciled — an unreachable cache is not
            evidence of death.
        too_young: Calls skipped as inside the grace period.

    There is deliberately no ``already_resolved`` bucket. The unresolved
    set is read *inside* the task lock, so a call another reconciler has
    already settled is simply not in it — ``scanned`` drops instead. A
    field that could never be populated would imply a distinction this
    design does not make.
    """

    scanned: int = 0
    reconciled: Tuple[str, ...] = ()
    alive: Tuple[str, ...] = ()
    unknown_liveness: Tuple[str, ...] = ()
    too_young: Tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Whether this pass appended anything."""
        return bool(self.reconciled)


#: Answers "is this call's owner still live?" — tri-state on purpose.
#: ``True`` alive, ``False`` provably gone, ``None`` unknown. Only
#: ``False`` may be reconciled.
LivenessProbe = Callable[[UnresolvedCall], Awaitable[Optional[bool]]]

#: The one schema this feature owns. Everything is qualified by it, so a
#: deployment can grant/revoke task memory independently of the rest of
#: the database.
SCHEMA_NAME: str = "working_memory"

#: Version of the migration this build requires. A database recording a
#: LOWER version needs migrating; a HIGHER one was written by a newer
#: build and is refused rather than guessed at.
MIGRATION_VERSION: int = 1

#: Name recorded alongside the version.
MIGRATION_NAME: str = "001_task_memory"

#: Every table the code depends on. Verification checks all of them, so a
#: partially-applied migration is reported as such instead of failing
#: later inside an append with a confusing error.
REQUIRED_TABLES: Tuple[str, ...] = (
    "schema_migrations",
    "tasks",
    "task_journal",
    "artifacts",
    "artifact_aliases",
    "artifact_evidence",
)

#: Fences delimiting the two halves of the migration file.
_UP_START, _UP_END = "-- >>> UP", "-- <<< UP"
_DOWN_START, _DOWN_END = "-- >>> DOWN", "-- <<< DOWN"


# ---------------------------------------------------------------------------
# Migration file handling
# ---------------------------------------------------------------------------


def migration_path() -> Path:
    """Return the path of the packaged migration file.

    Returns:
        Absolute path to ``migrations/001_task_memory.sql``.
    """
    return Path(__file__).resolve().parent.parent / "migrations" / f"{MIGRATION_NAME}.sql"


def read_migration() -> str:
    """Read the packaged migration file.

    Returns:
        The file's full text.

    Raises:
        TaskMemoryUnavailable: If the migration is missing from the
            installed package. A durable deployment without its schema
            definition cannot be made durable, so this fails loudly at
            startup rather than at the first append.
    """
    path = migration_path()
    if not path.is_file():
        raise TaskMemoryUnavailable(f"task-memory migration not found at {path}; the installed package is incomplete")
    return path.read_text(encoding="utf-8")


def split_migration(sql: Optional[str] = None) -> Tuple[str, str]:
    """Split the migration into its UP and DOWN halves.

    Args:
        sql: Migration text; read from the package when ``None``.

    Returns:
        A ``(up_sql, down_sql)`` pair, each stripped.

    Raises:
        TaskMemoryUnavailable: If either fence is missing or malformed. A
            migration whose DOWN half cannot be located is, for
            operational purposes, an irreversible one — better to refuse
            it than to discover that during a rollback.
    """
    text = read_migration() if sql is None else sql

    def _between(start: str, end: str) -> str:
        try:
            head = text.index(start) + len(start)
            tail = text.index(end, head)
        except ValueError as exc:
            raise TaskMemoryUnavailable(f"task-memory migration is malformed: missing {start!r}/{end!r} fence") from exc
        return text[head:tail].strip()

    up = _between(_UP_START, _UP_END)
    down = _between(_DOWN_START, _DOWN_END)
    if not up or not down:
        raise TaskMemoryUnavailable("task-memory migration has an empty UP or DOWN section")
    return up, down


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class PostgresTransaction:
    """One unit of work, bound to exactly one pooled connection.

    Satisfies the :class:`~parrot.interfaces.task_memory.Transaction`
    protocol. The connection is exposed so that the task store and the
    artifact store write through the *same* one — that shared connection
    is the whole point of the coordinator, and the reason an artifact's
    index row, its evidence rows and its journal event become visible
    together or not at all.
    """

    __slots__ = ("_connection", "_transaction", "_active")

    def __init__(self, connection: "asyncpg.Connection", transaction: Any) -> None:
        """Bind a transaction to its connection.

        Args:
            connection: The pooled connection this unit of work runs on.
            transaction: The driver-level transaction object.
        """
        self._connection = connection
        self._transaction = transaction
        self._active = True

    @property
    def connection(self) -> "asyncpg.Connection":
        """The connection every enlisted store must use.

        Raises:
            TaskMemoryUnavailable: If the transaction has already ended.
                Continuing to write through a finished transaction would
                silently run outside it, which is the failure this
                property exists to prevent.
        """
        if not self._active:
            raise TaskMemoryUnavailable("transaction has already completed; open a new one")
        return self._connection

    @property
    def is_active(self) -> bool:
        """Whether this transaction is still open."""
        return self._active

    async def rollback(self) -> None:
        """Abandon the unit of work, discarding every change made in it.

        Idempotent: rolling back an already-finished transaction is a
        no-op, so a cleanup path never has to guess whether it ran.
        """
        if not self._active:
            return
        self._active = False
        await self._transaction.rollback()

    async def _commit(self) -> None:
        """Commit the unit of work. Called only by the coordinator."""
        if not self._active:
            return
        self._active = False
        await self._transaction.commit()

    def _mark_finished(self) -> None:
        """Mark the transaction closed without touching the driver."""
        self._active = False


class PostgresTransactionCoordinator:
    """Hands out transactions the task and artifact stores share.

    Satisfies
    :class:`~parrot.interfaces.task_memory.TransactionCoordinator`.
    """

    def __init__(self, store: "PostgresTaskMemoryStore") -> None:
        """Bind the coordinator to its store.

        Args:
            store: The store whose pool supplies connections.
        """
        self._store = store

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[PostgresTransaction]:
        """Open a transaction, committing on clean exit, rolling back on error.

        Yields:
            The :class:`PostgresTransaction`. Pass it to every store that
            must commit atomically with this unit of work.

        Raises:
            TaskMemoryUnavailable: If no pool is configured.
        """
        pool = await self._store._acquire_pool()
        async with pool.acquire() as connection:
            driver_tx = connection.transaction()
            await driver_tx.start()
            handle = PostgresTransaction(connection, driver_tx)
            try:
                yield handle
            except BaseException:
                # Rollback covers ordinary exceptions AND cancellation: a
                # cancelled append must not leave a half-written journal
                # holding a sequence number nothing will ever complete.
                await handle.rollback()
                raise
            else:
                await handle._commit()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class PostgresTaskMemoryStore(BaseTaskMemoryStore):
    """Durable task-memory storage on PostgreSQL (Delivery B).

    The schema lifecycle, the pool, the transaction coordinator and the
    journal/projection command and read paths are implemented here.

    Durable aliases, versions and evidence pins belong to
    :class:`PostgresArtifactStore`, which shares this store's pool and
    transaction coordinator.

    Args:
        dsn: PostgreSQL connection string. ``None`` defers to ``pool``.
        pool: An already-built ``asyncpg`` pool to borrow. When given,
            this store does not own it and will not close it.
        schema: Schema to operate in. Overridable only for test
            isolation; production always uses :data:`SCHEMA_NAME`.
        min_size: Minimum pool size when this store builds the pool.
        max_size: Maximum pool size when this store builds the pool.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        *,
        pool: Optional[Any] = None,
        schema: str = SCHEMA_NAME,
        min_size: int = 1,
        max_size: int = 10,
        config: Optional[TaskMemoryConfig] = None,
    ) -> None:
        """Initialize the store without connecting."""
        if dsn is None and pool is None:
            raise ValueError("PostgresTaskMemoryStore requires either a dsn or an existing pool")
        self._dsn = dsn
        #: Capacity configuration. The same object the in-memory store
        #: uses, so both backends refuse the same batches for the same
        #: reasons (AC2).
        self._config = config or TaskMemoryConfig()
        self._pool: Optional[Any] = pool
        #: A borrowed pool is not ours to close.
        self._owns_pool = pool is None
        self._schema = schema
        self._min_size = min_size
        self._max_size = max_size
        self.logger = logging.getLogger(f"{__name__}.PostgresTaskMemoryStore")

    # -- pool lifecycle ----------------------------------------------------

    async def _acquire_pool(self) -> Any:
        """Return the connection pool, building it on first use.

        The ``asyncpg`` import happens here, not at module import: a
        deployment without the PostgreSQL extra must still be able to
        import the task-memory package and run the in-memory backend.

        Returns:
            The live pool.

        Raises:
            TaskMemoryUnavailable: If ``asyncpg`` is not installed, or the
                server cannot be reached. Durable mode fails loudly
                rather than silently degrading to non-durable, which
                would be a false durability claim.
        """
        if self._pool is not None:
            return self._pool

        try:
            import asyncpg  # noqa: PLC0415 — lazy on purpose, see the docstring
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise TaskMemoryUnavailable(
                "durable task memory requires asyncpg, which is not installed. "
                "Install the PostgreSQL extra, or leave TASK_MEMORY_DURABLE unset "
                "to use the in-process backend."
            ) from exc

        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
            )
        except Exception as exc:  # noqa: BLE001 — every connect failure is one answer
            raise TaskMemoryUnavailable(f"could not connect to the task-memory database: {exc}") from exc
        return self._pool

    async def close(self) -> None:
        """Close the pool, if this store owns it."""
        if self._pool is not None and self._owns_pool:
            await self._pool.close()
        self._pool = None

    def coordinator(self) -> PostgresTransactionCoordinator:
        """Return the coordinator that hands out shareable transactions."""
        return PostgresTransactionCoordinator(self)

    def transaction(self) -> Any:
        """Open a transaction this store and an artifact store can share.

        Returns:
            An async context manager yielding a
            :class:`PostgresTransaction`.
        """
        return self.coordinator().begin()

    # -- schema lifecycle --------------------------------------------------

    async def apply_migrations(self) -> int:
        """Apply the packaged migration explicitly.

        Safe to repeat: every statement is ``IF NOT EXISTS``-guarded and
        the version row uses ``ON CONFLICT DO NOTHING``, so re-running is
        a no-op that also completes a migration interrupted part-way.

        This is **never** called from a tool path. Automatic DDL on a hot
        path would mean any agent turn could attempt a schema change.

        Returns:
            The migration version now recorded in the database.

        Raises:
            TaskMemoryUnavailable: If the database already records a
                NEWER migration than this build implements. Running old
                code against a new schema is refused rather than
                attempted.
        """
        up_sql, _ = split_migration()
        if self._schema != SCHEMA_NAME:
            up_sql = up_sql.replace(f"{SCHEMA_NAME}.", f"{self._schema}.").replace(
                f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}",
                f"CREATE SCHEMA IF NOT EXISTS {self._schema}",
            )

        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            existing = await self._read_version(connection)
            if existing is not None and existing > MIGRATION_VERSION:
                raise TaskMemoryUnavailable(
                    f"database records task-memory migration {existing}, but this build implements "
                    f"{MIGRATION_VERSION}; upgrade the application rather than downgrading the schema"
                )
            async with connection.transaction():
                await connection.execute(up_sql)
        self.logger.info("Applied task-memory migration %s to schema %s", MIGRATION_VERSION, self._schema)
        return MIGRATION_VERSION

    async def revert_migrations(self) -> None:
        """Run the DOWN migration.

        .. danger::

           Destructive and irreversible: it drops the whole schema, and
           every journal, projection and artifact index row with it. It
           also orphans every blob in external storage, which this
           migration does not touch. Read the rollback guidance at the
           top of the migration file before calling this.
        """
        _, down_sql = split_migration()
        if self._schema != SCHEMA_NAME:
            down_sql = down_sql.replace(SCHEMA_NAME, self._schema)
        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(down_sql)
        self.logger.warning("Reverted task-memory migration on schema %s (schema dropped)", self._schema)

    async def _read_version(self, connection: Any) -> Optional[int]:
        """Return the highest recorded migration version, or ``None``.

        Args:
            connection: An open connection.

        Returns:
            The version, or ``None`` when the schema or the migrations
            table does not exist yet.
        """
        row = await connection.fetchval(
            "SELECT to_regclass($1)",
            f"{self._schema}.schema_migrations",
        )
        if row is None:
            return None
        return await connection.fetchval(f"SELECT max(version) FROM {self._schema}.schema_migrations")

    async def verify_schema(self) -> None:
        """Check the database has the shape this build expects.

        Called at enabled-backend startup, not per operation. A missing
        table is reported by name, so an operator sees "you did not run
        the migration" rather than a confusing error inside the first
        append.

        Raises:
            TaskMemoryUnavailable: If the schema is absent, incomplete,
                or records a newer migration than this build implements.
        """
        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            version = await self._read_version(connection)
            if version is None:
                raise TaskMemoryUnavailable(
                    f"schema {self._schema!r} has no task-memory migration applied; "
                    "run apply_migrations() at deployment before enabling durable task memory"
                )
            if version > MIGRATION_VERSION:
                raise TaskMemoryUnavailable(
                    f"database records task-memory migration {version}, but this build implements "
                    f"{MIGRATION_VERSION}; upgrade the application"
                )
            missing = [name for name in REQUIRED_TABLES if not await self._table_exists(connection, name)]
            if missing:
                raise TaskMemoryUnavailable(
                    f"schema {self._schema!r} is missing task-memory tables: {sorted(missing)}; "
                    "the migration is incomplete — re-run apply_migrations()"
                )

    async def _table_exists(self, connection: Any, table: str) -> bool:
        """Whether one table exists in this store's schema.

        Args:
            connection: An open connection.
            table: Unqualified table name.

        Returns:
            ``True`` when present.
        """
        return await connection.fetchval("SELECT to_regclass($1)", f"{self._schema}.{table}") is not None

    # ── serialization helpers ────────────────────────────────────────

    def _t(self, name: str) -> str:
        """Return a schema-qualified table name.

        Args:
            name: Unqualified table name.

        Returns:
            ``"<schema>.<name>"``.
        """
        return f"{self._schema}.{name}"

    @staticmethod
    def _dump(value: Any) -> str:
        """Serialize a model or mapping to JSON text for a JSONB column.

        Args:
            value: A Pydantic model or plain mapping.

        Returns:
            Canonical JSON text.
        """
        import json

        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _row_to_event(row: Any) -> JournalEvent:
        """Rebuild a :class:`JournalEvent` from a ``task_journal`` row.

        Args:
            row: An ``asyncpg`` record.

        Returns:
            The event, with its stored sequence.
        """
        import json

        payload = row["payload"]
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)
        return JournalEvent.model_validate(
            {
                "event_id": row["event_id"],
                "task_id": row["task_id"],
                "seq": row["seq"],
                "occurred_at": row["occurred_at"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "turn_id": row["turn_id"],
                "plan_revision": row["plan_revision"],
                "step_id": row["step_id"],
                "call_id": row["call_id"],
                "parent_call_id": row["parent_call_id"],
                "attribution": row["attribution"],
                "payload": payload,
            }
        )

    @staticmethod
    def _row_to_state(row: Any) -> TaskState:
        """Rebuild a :class:`TaskState` from a ``tasks`` row's projection.

        The projection column is the whole authority for the returned
        state; the scalar columns beside it exist for indexing and for
        SQL-side constraints, not as a second source of truth.

        Args:
            row: An ``asyncpg`` record.

        Returns:
            The projection.
        """
        import json

        projection = row["projection"]
        if isinstance(projection, (str, bytes)):
            projection = json.loads(projection)
        return TaskState.model_validate(projection)

    @staticmethod
    def _scope_of(row: Any) -> TaskScope:
        """Return the scope stored on a task row.

        Args:
            row: An ``asyncpg`` record with the scope columns.

        Returns:
            The stored scope.
        """
        return TaskScope(
            chatbot_id=row["chatbot_id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
        )

    # ── locked append protocol ───────────────────────────────────────

    async def _lock_task(self, connection: Any, task_id: str) -> Optional[Any]:
        """Take the task row's write lock.

        ``SELECT ... FOR UPDATE`` is what makes same-task appends
        serialize while different tasks proceed concurrently: PostgreSQL
        provides here exactly what the in-memory store gets from a
        per-task ``asyncio.Lock``.

        Args:
            connection: The connection inside the open transaction.
            task_id: The task to lock.

        Returns:
            The locked row, or ``None`` when the task does not exist.
        """
        return await connection.fetchrow(
            f"SELECT * FROM {self._t('tasks')} WHERE task_id = $1 FOR UPDATE",
            task_id,
        )

    async def _committed_events(self, connection: Any, task_id: str) -> dict:
        """Return a task's committed events indexed by ``event_id``.

        Read inside the transaction, after the row lock, so the
        classification cannot race a concurrent append.

        Args:
            connection: The connection inside the open transaction.
            task_id: The task to read.

        Returns:
            Mapping of ``event_id`` to :class:`JournalEvent`.
        """
        rows = await connection.fetch(
            f"SELECT * FROM {self._t('task_journal')} WHERE task_id = $1 ORDER BY seq",
            task_id,
        )
        return {row["event_id"]: self._row_to_event(row) for row in rows}

    def _check_capacity(self, existing_count: int, fresh: Sequence[JournalEvent]) -> None:
        """Refuse a batch that would exhaust the journal.

        Identical rule to the in-memory store: foreground work is refused
        while reserved headroom remains, and a batch counts as reserved
        only when *every* event in it is a reserved type. A batch
        carrying any ordinary work is ordinary work.

        Args:
            existing_count: Events already in the journal.
            fresh: The genuinely new events about to be appended.

        Raises:
            LimitExceeded: If appending the batch would pass the ceiling.
        """
        if not fresh:
            return
        reserved = all(event.event_type.is_reserved for event in fresh)
        final_index = existing_count + len(fresh) - 1
        if self._config.is_journal_exhausted(final_index, reserved=reserved):
            ceiling = self._config.journal_hard_limit + (self._config.journal_reserved_events if reserved else 0)
            raise LimitExceeded(
                "journal events",
                ceiling,
                existing_count + len(fresh),
                "reserved headroom is kept for terminal, recovery and retention events",
            )

    async def _migrated_state(self, connection: Any, row: Any, scope: TaskScope) -> TaskState:
        """Return a row's projection under **this** build's reducer.

        A projection written by an older reducer is rebuilt by replaying
        the journal — the journal is the source of truth and is therefore
        always sufficient. A projection written by a *newer* reducer is
        refused: this build cannot know what its fields meant, and
        best-effort interpretation is how a projection silently starts
        disagreeing with its journal.

        The replay happens under the task row lock the caller already
        holds, and the migrated projection is written back, so the work
        is done once rather than on every read.

        Args:
            connection: The connection inside the open transaction.
            row: The locked task row.
            scope: The task's trusted scope.

        Returns:
            The projection, migrated when it was stale.

        Raises:
            ReducerError: If the stored projection came from a newer
                reducer than this build implements.
        """
        version = int(row["reducer_version"])
        if version == REDUCER_VERSION:
            return self._row_to_state(row)
        if version > REDUCER_VERSION:
            raise ReducerError(
                f"task {row['task_id']} carries reducer version {version}, "
                f"but this build implements {REDUCER_VERSION}; refusing to interpret a newer projection"
            )

        self.logger.info(
            "[TaskMemory] replaying task %s from reducer version %s to %s",
            row["task_id"],
            version,
            REDUCER_VERSION,
        )
        events = list((await self._committed_events(connection, row["task_id"])).values())
        events.sort(key=lambda event: event.seq)
        rebuilt = replay(events, scope=scope)
        if rebuilt is None:  # pragma: no cover - a row always has its task_started
            raise ReducerError(f"task {row['task_id']} has an empty journal and cannot be replayed")
        await self._write_projection(connection, rebuilt)
        return rebuilt

    async def _write_projection(self, connection: Any, state: TaskState) -> None:
        """Persist a projection and the scalar columns derived from it.

        Args:
            connection: The connection inside the open transaction.
            state: The projection to store.
        """
        await connection.execute(
            f"""
            UPDATE {self._t('tasks')}
               SET status = $2,
                   goal = $3,
                   revision = $4,
                   last_event_seq = $5,
                   projection = $6::jsonb,
                   reducer_version = $7,
                   updated_at = $8,
                   terminal_at = $9
             WHERE task_id = $1
            """,
            state.task_id,
            state.status.value,
            state.goal,
            state.revision,
            state.last_event_seq,
            self._dump(state),
            REDUCER_VERSION,
            state.updated_at,
            state.terminal_at,
        )

    async def _insert_events(self, connection: Any, events: Sequence[JournalEvent]) -> None:
        """Insert journal rows for a staged batch.

        Args:
            connection: The connection inside the open transaction.
            events: Sequenced events, in order.
        """
        await connection.executemany(
            f"""
            INSERT INTO {self._t('task_journal')}
                (task_id, seq, event_id, event_type, occurred_at, actor,
                 turn_id, step_id, call_id, parent_call_id, attribution,
                 plan_revision, payload)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb)
            """,
            [
                (
                    event.task_id,
                    event.seq,
                    event.event_id,
                    event.event_type.value,
                    event.occurred_at,
                    event.actor.value,
                    event.turn_id,
                    event.step_id,
                    event.call_id,
                    event.parent_call_id,
                    event.attribution.value,
                    event.plan_revision,
                    self._dump(event.payload),
                )
                for event in events
            ],
        )

    async def _apply(
        self,
        connection: Any,
        row: Any,
        scope: TaskScope,
        events: Sequence[JournalEvent],
        expected_revision: Optional[int],
    ) -> AppendResult:
        """Run the atomic append against a locked task row.

        The ordering is the contract, not an implementation detail, and
        matches the in-memory store exactly.

        Args:
            connection: The connection inside the open transaction.
            row: The locked task row.
            scope: The caller's trusted scope.
            events: The batch, in order.
            expected_revision: Revision the caller believes is current,
                or ``None`` to skip the check.

        Returns:
            The append result.

        Raises:
            RevisionConflict: If the revision is stale and the batch is
                not a pure redelivery.
            ReducerError: If an event is malformed or an id is reused
                with a different payload.
            LimitExceeded: If capacity is exhausted.
        """
        state = await self._migrated_state(connection, row, scope)
        committed = await self._committed_events(connection, state.task_id)

        # 1. Redelivery FIRST. A caller retrying a batch that in fact
        #    committed has a legitimately stale revision *because of its
        #    own success*, so classification must precede the revision
        #    check or a correct retry would be rejected as a conflict.
        classification = self._classify(events, committed)

        if classification.is_noop:
            return AppendResult(
                state=state,
                appended_event_ids=(),
                deduplicated_event_ids=classification.duplicates,
                first_seq=None,
                last_seq=state.last_event_seq,
            )

        # 2. Optimistic concurrency. `None` is reserved for
        #    runtime-authored events (recovery, retention) that cannot
        #    meaningfully conflict with an agent's optimistic view.
        if expected_revision is not None and expected_revision != state.revision:
            raise RevisionConflict(state.task_id, expected_revision, state.revision)

        # 3. Capacity, still before any write.
        self._check_capacity(len(committed), classification.fresh)

        # 4. Reduce into a LOCAL variable. A malformed event anywhere in
        #    the batch raises here, before a single row is written.
        sequences = list(self._sequence_range(state.last_event_seq, len(classification.fresh)))
        staged = []
        working = state
        for seq, event in zip(sequences, classification.fresh):
            sequenced = event.model_copy(update={"seq": seq})
            working = reduce(working, sequenced, scope=scope)
            staged.append(sequenced)

        # 5. Write. Everything above succeeded; and anything that still
        #    fails here rolls the whole transaction back.
        await self._insert_events(connection, staged)
        await self._write_projection(connection, working)

        return AppendResult(
            state=working,
            appended_event_ids=tuple(event.event_id for event in staged),
            deduplicated_event_ids=classification.duplicates,
            first_seq=sequences[0],
            last_seq=sequences[-1],
        )

    @asynccontextmanager
    async def _unit_of_work(self, transaction: Optional[PostgresTransaction]) -> AsyncIterator[Any]:
        """Yield a connection inside a transaction, joining an existing one.

        When the caller supplies a transaction, its connection is reused
        and NOT committed here — the owner commits it, which is what lets
        an artifact publish and its journal event land together.

        Args:
            transaction: A transaction to enlist in, or ``None`` to open
                a private one.

        Yields:
            The connection to use.
        """
        if transaction is not None:
            yield transaction.connection
            return
        async with self.transaction() as owned:
            yield owned.connection

    # ── contract: commands ───────────────────────────────────────────

    @staticmethod
    def _normalize_creation(events: Sequence[JournalEvent], goal: str) -> Tuple[JournalEvent, ...]:
        """Stamp the task's goal onto its ``task_started`` event.

        Identical to the in-memory store's rule, and for the same reason:
        ``create_task`` receives the goal as an argument, but the journal
        is the source of truth, so a ``task_started`` that does not carry
        the goal cannot be replayed — a rebuild after a restart, or a
        reducer-version migration, would fail on it.

        Args:
            events: The creation batch, in order.
            goal: The goal supplied to ``create_task``.

        Returns:
            The batch with the goal stamped on its first event.

        Raises:
            ReducerError: If the batch is empty, its first event is not a
                ``task_started``, events disagree about the task id, or
                the event already carries a *different* goal.
        """
        if not events:
            raise ReducerError("create_task requires at least a task_started event")

        first = events[0]
        if first.event_type is not EventType.TASK_STARTED:
            raise ReducerError(f"a task's first event must be task_started, got {first.event_type.value!r}")

        task_id = first.task_id
        for event in events:
            if event.task_id != task_id:
                raise ReducerError(f"creation batch mixes tasks: {event.task_id!r} alongside {task_id!r}")

        payload = first.payload
        if not isinstance(payload, TaskLifecyclePayload):  # pragma: no cover - JournalEvent enforces this
            raise ReducerError("task_started requires a task_lifecycle payload")

        if payload.goal is None:
            first = first.model_copy(update={"payload": payload.model_copy(update={"goal": goal})})
        elif payload.goal != goal:
            raise ReducerError(
                f"task_started carries goal {payload.goal!r} but create_task was given {goal!r}; "
                "the journal and the command must agree"
            )

        return (first, *events[1:])

    async def create_task(
        self,
        scope: TaskScope,
        *,
        goal: str,
        events: Sequence[JournalEvent],
        transaction: Optional[PostgresTransaction] = None,
    ) -> AppendResult:
        """Create a task and append its first batch of events atomically.

        There is no window in which a task exists with an empty journal:
        the row and its whole creation batch commit together.

        Creation is idempotent and safe to race. Two pods creating the
        same task id concurrently produce one row and one journal — the
        loser of the ``INSERT ... ON CONFLICT DO NOTHING`` falls through
        to the ordinary append path, which recognises the identical batch
        as a redelivery.

        Args:
            scope: Trusted runtime scope the task belongs to.
            goal: The task's goal, stamped onto ``task_started`` when the
                event does not already carry it.
            events: Initial events, beginning with ``task_started``.
            transaction: A transaction to enlist in, or ``None``.

        Returns:
            The append result, including the reduced projection.

        Raises:
            LimitExceeded: If the scope already holds the maximum number
                of open tasks.
            ScopeViolation: If the task id already exists in a different
                scope.
            ReducerError: If the batch is malformed.
            PlanValidationError: If the initial plan is invalid.
        """
        normalized = self._normalize_creation(events, goal)
        task_id = normalized[0].task_id

        async with self._unit_of_work(transaction) as connection:
            existing = await self._lock_task(connection, task_id)
            if existing is not None:
                self._ensure_scope(scope, self._scope_of(existing), subject="task")
                return await self._apply(connection, existing, scope, normalized, expected_revision=None)

            # Reduce the creation batch BEFORE inserting anything, so a
            # malformed batch leaves no empty task behind.
            working: Optional[TaskState] = None
            staged = []
            for index, event in enumerate(normalized, start=1):
                sequenced = event.model_copy(update={"seq": index})
                working = reduce(working, sequenced, scope=scope)
                staged.append(sequenced)
            assert working is not None  # normalized is non-empty

            limit = self._config.max_open_tasks_per_scope
            open_tasks = await connection.fetchval(
                f"""
                SELECT count(*) FROM {self._t('tasks')}
                 WHERE chatbot_id = $1 AND user_id = $2 AND session_id = $3
                   AND terminal_at IS NULL
                """,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
            )
            if int(open_tasks) >= limit:
                raise LimitExceeded("open tasks per scope", limit, int(open_tasks) + 1)

            inserted = await connection.fetchval(
                f"""
                INSERT INTO {self._t('tasks')}
                    (task_id, chatbot_id, user_id, session_id, status, goal,
                     revision, last_event_seq, projection, reducer_version,
                     created_at, updated_at, terminal_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13)
                ON CONFLICT (task_id) DO NOTHING
                RETURNING task_id
                """,
                working.task_id,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
                working.status.value,
                working.goal,
                working.revision,
                working.last_event_seq,
                self._dump(working),
                REDUCER_VERSION,
                working.created_at,
                working.updated_at,
                working.terminal_at,
            )

            if inserted is None:
                # Another writer won the race between our lock attempt and
                # this insert. Re-lock and fall through to the append
                # path, which recognises an identical batch as a no-op.
                row = await self._lock_task(connection, task_id)
                if row is None:  # pragma: no cover - it was just inserted by someone
                    raise TaskMemoryUnavailable(f"task {task_id!r} vanished during creation")
                self._ensure_scope(scope, self._scope_of(row), subject="task")
                return await self._apply(connection, row, scope, normalized, expected_revision=None)

            await self._insert_events(connection, staged)
            return AppendResult(
                state=working,
                appended_event_ids=tuple(event.event_id for event in staged),
                deduplicated_event_ids=(),
                first_seq=1,
                last_seq=len(staged),
            )

    async def append_events(
        self,
        scope: TaskScope,
        task_id: str,
        events: Sequence[JournalEvent],
        *,
        expected_revision: Optional[int] = None,
        transaction: Optional[PostgresTransaction] = None,
    ) -> AppendResult:
        """Append a batch of events under an optimistic revision check.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to append to.
            events: The batch, in order.
            expected_revision: Revision the caller believes is current.
                ``None`` skips the check.
            transaction: A transaction to enlist in, or ``None``.

        Returns:
            The append result.

        Raises:
            ScopeViolation: If the task does not exist in this scope.
            RevisionConflict: If the revision is stale and the batch is
                not a pure redelivery. Nothing is written.
            ReducerError: If an id is reused with a different payload, or
                an event is malformed.
            LimitExceeded: If the journal's capacity is exhausted.
        """
        async with self._unit_of_work(transaction) as connection:
            row = await self._lock_task(connection, task_id)
            if row is None:
                raise ScopeViolation(f"task {task_id!r} does not exist in this scope")
            self._ensure_scope(scope, self._scope_of(row), subject="task")
            return await self._apply(connection, row, scope, events, expected_revision)

    # ── contract: reads ──────────────────────────────────────────────

    async def load_snapshot(self, scope: TaskScope, task_id: str) -> Optional[TaskSnapshot]:
        """Load one task's projection consistently.

        The projection, its sequence fence and the event count are read
        in ONE transaction, so a concurrent append cannot make them
        describe different instants.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to load.

        Returns:
            The snapshot, or ``None`` when no such task exists in this
            scope. A task owned by another scope reads as absent rather
            than forbidden — an existence oracle is a leak.
        """
        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await self._lock_task(connection, task_id)
                if row is None or not scope.matches(self._scope_of(row)):
                    return None
                state = await self._migrated_state(connection, row, scope)
                count = await connection.fetchval(
                    f"SELECT count(*) FROM {self._t('task_journal')} WHERE task_id = $1",
                    task_id,
                )
                return TaskSnapshot(
                    state=state,
                    as_of_seq=state.last_event_seq,
                    event_count=int(count),
                )

    async def list_tasks(
        self,
        scope: TaskScope,
        *,
        statuses: Optional[Sequence[TaskStatus]] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> TaskPage:
        """List tasks in a scope, newest activity first.

        Ordering is ``(updated_at desc, task_id asc)``, matching the
        in-memory store. The task-id tiebreak makes the order *total*, so
        keyset pagination cannot skip or repeat a row when two tasks
        share a timestamp.

        Args:
            scope: Trusted runtime scope.
            statuses: Restrict to these statuses; ``None`` means open
                (non-terminal) tasks only.
            limit: Bounded page size.
            cursor: Opaque cursor from a previous page.

        Returns:
            A bounded page of summaries.

        Raises:
            CursorError: If the cursor is malformed, out of bounds, or
                was issued for a different scope or query.
        """
        size = self._bounded(limit, default=self.default_task_page)
        wanted = tuple(status.value for status in statuses) if statuses is not None else None
        query = {"statuses": wanted}

        conditions = ["chatbot_id = $1", "user_id = $2", "session_id = $3"]
        args: list = [scope.chatbot_id, scope.user_id, scope.session_id]

        if wanted is None:
            conditions.append("terminal_at IS NULL")
        else:
            args.append(list(wanted))
            conditions.append(f"status = ANY(${len(args)})")

        if cursor is not None:
            position = self._decode_cursor(cursor, scope, query)
            from datetime import datetime as _dt

            args.append(_dt.fromisoformat(str(position["ts"])))
            args.append(str(position["id"]))
            # Row-value comparison expresses "strictly after this row in
            # (updated_at desc, task_id asc)" in one indexable predicate.
            conditions.append(f"(updated_at, task_id) < (${len(args) - 1}, ${len(args)})")

        args.append(size + 1)
        sql = (
            f"SELECT task_id, goal, status, updated_at FROM {self._t('tasks')} "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY updated_at DESC, task_id DESC LIMIT ${len(args)}"
        )

        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(sql, *args)
            total_open = await connection.fetchval(
                f"""
                SELECT count(*) FROM {self._t('tasks')}
                 WHERE chatbot_id = $1 AND user_id = $2 AND session_id = $3
                   AND terminal_at IS NULL
                """,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
            )

        has_more = len(rows) > size
        window = rows[:size]
        next_cursor: Optional[str] = None
        if has_more and window:
            last = window[-1]
            next_cursor = self._encode_cursor(
                scope, query, {"ts": last["updated_at"].isoformat(), "id": last["task_id"]}
            )

        return TaskPage(
            items=tuple(
                TaskSummary(
                    task_id=row["task_id"],
                    goal_preview=goal_preview(row["goal"], chars=GOAL_PREVIEW_CHARS),
                    status=TaskStatus(row["status"]),
                    updated_at=row["updated_at"],
                )
                for row in window
            ),
            next_cursor=next_cursor,
            total_open=int(total_open),
        )

    async def list_events(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 50,
        as_of_seq: Optional[int] = None,
    ) -> EventPage:
        """Page a task's journal in ascending sequence order.

        Reads never append: no statement here writes, so repeated reads
        cannot change a task's sequence or fill its journal.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to read.
            after_seq: Return events strictly after this sequence.
            limit: Bounded page size.
            as_of_seq: Fence the read at this sequence.

        Returns:
            A bounded page of events.

        Raises:
            ScopeViolation: If the task does not exist in this scope.
        """
        size = self._bounded(limit, default=self.default_event_page)
        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT chatbot_id, user_id, session_id FROM {self._t('tasks')} WHERE task_id = $1",
                task_id,
            )
            if row is None or not scope.matches(self._scope_of(row)):
                raise ScopeViolation(f"task {task_id!r} does not exist in this scope")

            conditions = ["task_id = $1", "seq > $2"]
            args: list = [task_id, after_seq]
            if as_of_seq is not None:
                args.append(as_of_seq)
                conditions.append(f"seq <= ${len(args)}")
            args.append(size + 1)
            rows = await connection.fetch(
                f"SELECT * FROM {self._t('task_journal')} "
                f"WHERE {' AND '.join(conditions)} ORDER BY seq LIMIT ${len(args)}",
                *args,
            )

        has_more = len(rows) > size
        window = [self._row_to_event(row) for row in rows[:size]]
        return EventPage(
            events=tuple(window),
            next_seq=window[-1].seq if window else after_seq,
            has_more=has_more,
        )

    # ── contract: crash reconciliation (spec §2 Recovery) ────────────

    _UNRESOLVED_SQL = """
        SELECT
            j.call_id,
            j.seq            AS started_seq,
            j.occurred_at    AS started_at,
            j.step_id        AS step_id,
            j.turn_id        AS turn_id,
            j.parent_call_id AS parent_call_id,
            j.payload        AS payload,
            EXISTS (
                SELECT 1 FROM {journal} c
                WHERE c.task_id = j.task_id AND c.parent_call_id = j.call_id
            ) AS is_aggregate
        FROM {journal} j
        WHERE j.task_id = $1
          AND j.call_id IS NOT NULL
          AND j.event_type = $2
          AND NOT EXISTS (
              SELECT 1 FROM {journal} t
              WHERE t.task_id = j.task_id
                AND t.call_id = j.call_id
                AND t.event_type = ANY($3::text[])
          )
        ORDER BY j.seq
    """

    async def _read_unresolved(self, connection: Any, task_id: str) -> Tuple[UnresolvedCall, ...]:
        """Read every started-but-unsettled call for a task.

        Uses one anti-join rather than paging the journal in Python: the
        journal of a long-lived task is unbounded, and recovery must not
        become the thing that runs out of memory.

        Args:
            connection: A connection, ideally already holding the task lock.
            task_id: The task to scan.

        Returns:
            The unresolved calls, in start order.
        """
        rows = await connection.fetch(
            self._UNRESOLVED_SQL.format(journal=self._t("task_journal")),
            task_id,
            EventType.TOOL_STARTED.value,
            list(TERMINAL_CALL_EVENTS),
        )
        calls = []
        for row in rows:
            payload = self._loads_payload(row["payload"])
            calls.append(
                UnresolvedCall(
                    call_id=row["call_id"],
                    tool_name=str(payload.get("tool_name") or "unknown"),
                    started_at=row["started_at"],
                    started_seq=int(row["started_seq"]),
                    step_id=row["step_id"],
                    turn_id=row["turn_id"],
                    parent_call_id=row["parent_call_id"],
                    attempt=int(payload.get("attempt") or 1),
                    is_aggregate=bool(row["is_aggregate"]),
                )
            )
        return tuple(calls)

    @staticmethod
    def _loads_payload(value: Any) -> dict:
        """Decode a stored event row's JSONB payload.

        Args:
            value: The raw column value.

        Returns:
            The nested ``payload`` mapping, or an empty dict.
        """
        import json

        data = value
        if isinstance(data, (str, bytes, bytearray)):
            try:
                data = json.loads(data)
            except Exception:  # noqa: BLE001 — a malformed row must not stop recovery
                return {}
        if not isinstance(data, dict):
            return {}
        payload = data.get("payload")
        return payload if isinstance(payload, dict) else {}

    async def unresolved_calls(self, scope: TaskScope, task_id: str) -> Tuple[UnresolvedCall, ...]:
        """List calls this task started but never settled.

        Read-only and appends nothing. An unresolved call is a question,
        not a verdict: a ten-minute tool call is unresolved for ten
        minutes and is perfectly healthy throughout.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to scan.

        Returns:
            The unresolved calls, in start order.

        Raises:
            ScopeViolation: If the task does not exist in this scope.
        """
        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(f"SELECT * FROM {self._t('tasks')} WHERE task_id = $1", task_id)
            if row is None:
                raise ScopeViolation(f"task {task_id!r} does not exist in this scope")
            self._ensure_scope(scope, self._scope_of(row), subject="task")
            return await self._read_unresolved(connection, task_id)

    async def has_terminal_event(self, scope: TaskScope, task_id: str, call_id: str) -> bool:
        """Whether a call already has a settled outcome.

        This is the durable half of fencing. A late result from an old
        owner is rejected on the strength of *this*, not on Redis: the
        journal is the record, and a decision already written there
        cannot be overwritten by a slower owner that has just woken up.

        Args:
            scope: Trusted runtime scope.
            task_id: The owning task.
            call_id: The attempt.

        Returns:
            ``True`` when a terminal event exists for the call.

        Raises:
            ScopeViolation: If the task does not exist in this scope.
        """
        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(f"SELECT * FROM {self._t('tasks')} WHERE task_id = $1", task_id)
            if row is None:
                raise ScopeViolation(f"task {task_id!r} does not exist in this scope")
            self._ensure_scope(scope, self._scope_of(row), subject="task")
            found = await connection.fetchval(
                f"SELECT 1 FROM {self._t('task_journal')} "
                "WHERE task_id = $1 AND call_id = $2 AND event_type = ANY($3::text[]) LIMIT 1",
                task_id,
                call_id,
                list(TERMINAL_CALL_EVENTS),
            )
            return found is not None

    def _unknown_event(self, task_id: str, call: UnresolvedCall, reason: str) -> JournalEvent:
        """Build the ``tool_outcome_unknown`` event for a dead call.

        Args:
            task_id: The owning task.
            call: The unresolved call.
            reason: Why it was reconciled.

        Returns:
            The event.
        """
        from ..models import ToolCallPayload

        return JournalEvent(
            task_id=task_id,
            occurred_at=utc_now(),
            event_type=EventType.TOOL_OUTCOME_UNKNOWN,
            actor=Actor.RUNTIME,
            turn_id=call.turn_id,
            step_id=call.step_id,
            call_id=call.call_id,
            parent_call_id=call.parent_call_id,
            payload=ToolCallPayload(
                call_id=call.call_id,
                tool_name=call.tool_name,
                attempt=call.attempt,
                # The call really did start, so a body may well have run.
                # Claiming otherwise would understate the risk that its
                # external effect happened.
                executed=True,
                outcome=CallOutcome.UNKNOWN,
                error=reason[: Limits.MAX_REASON],
                # An aggregate is not a physical attempt, exactly as at
                # first-hand terminal time.
                counted=not call.is_aggregate,
            ),
        )

    async def reconcile_calls(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        is_live: Optional[LivenessProbe] = None,
        min_age_seconds: float = 0.0,
        now: Optional[datetime] = None,
        reason: str = (
            "the owner of this call is no longer live and its outcome was never recorded; "
            "the tool may or may not have run, so this is UNKNOWN and must not be retried automatically"
        ),
    ) -> ReconcileReport:
        """Settle provably-dead calls as ``tool_outcome_unknown``, once.

        Three properties this method exists to guarantee:

        - **A live call is never touched.** ``is_live`` must return
          ``False`` — *provably* gone — before anything is appended.
          ``True`` and ``None`` are both left alone, so neither a slow
          call nor an unreachable cache can be mistaken for a crash. An
          expired append lease is not consulted at all: it says nothing
          about whether a call is running.
        - **At most one unknown per call, ever.** The whole pass runs
          under the task row's ``SELECT ... FOR UPDATE``, and the
          unresolved set is read *inside* that lock. A second reconciler
          blocks, then re-reads and finds the call already settled. Two
          concurrent reconcilers therefore append one event between them,
          not two — and a repeated scan appends none.
        - **Nothing is retried.** This records that an outcome is
          unknown. It never re-dispatches: the effect may already have
          happened, and repeating it is the one unrecoverable mistake.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to reconcile.
            is_live: Tri-state liveness probe. ``None`` means no probe is
                available, in which case nothing is reconciled — refusing
                to guess is the point.
            min_age_seconds: Grace period. A call younger than this is
                left alone even if it looks dead, so a claim that has not
                yet been written cannot be raced.
            now: Injected clock, for deterministic tests.
            reason: Text recorded on the event.

        Returns:
            A :class:`ReconcileReport` distinguishing every skip reason.

        Raises:
            ScopeViolation: If the task does not exist in this scope.
        """
        moment = now or utc_now()
        cutoff = moment - timedelta(seconds=max(0.0, min_age_seconds))

        async with self._unit_of_work(None) as connection:
            # The lock is taken FIRST and held across the read, the probe
            # and the append. Reading the unresolved set before the lock
            # would let two reconcilers both see the same open call.
            row = await self._lock_task(connection, task_id)
            if row is None:
                raise ScopeViolation(f"task {task_id!r} does not exist in this scope")
            self._ensure_scope(scope, self._scope_of(row), subject="task")

            calls = await self._read_unresolved(connection, task_id)
            reconciled: list = []
            alive: list = []
            unknown: list = []
            young: list = []
            events: list = []

            for call in calls:
                started = call.started_at
                if started.tzinfo is None:  # pragma: no cover - column is timestamptz
                    started = started.replace(tzinfo=timezone.utc)
                if started > cutoff:
                    young.append(call.call_id)
                    continue
                verdict = await is_live(call) if is_live is not None else None
                if verdict is None:
                    # Could not establish liveness. Leaving it unresolved
                    # is the honest answer; inventing a death here is how
                    # a healthy call gets its effect retried.
                    unknown.append(call.call_id)
                    continue
                if verdict:
                    alive.append(call.call_id)
                    continue
                reconciled.append(call.call_id)
                events.append(self._unknown_event(task_id, call, reason))

            if events:
                # expected_revision is None: this is runtime-authored
                # recovery, which cannot meaningfully conflict with an
                # agent's optimistic view of the plan.
                await self._apply(connection, row, scope, events, None)

            return ReconcileReport(
                scanned=len(calls),
                reconciled=tuple(reconciled),
                alive=tuple(alive),
                unknown_liveness=tuple(unknown),
                too_young=tuple(young),
            )

    async def count_events(self, scope: TaskScope, task_id: str) -> int:
        """Return how many events a task's journal holds.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to measure.

        Returns:
            The event count, or ``0`` when the task does not exist in
            this scope.
        """
        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT chatbot_id, user_id, session_id FROM {self._t('tasks')} WHERE task_id = $1",
                task_id,
            )
            if row is None or not scope.matches(self._scope_of(row)):
                return 0
            return int(
                await connection.fetchval(
                    f"SELECT count(*) FROM {self._t('task_journal')} WHERE task_id = $1",
                    task_id,
                )
            )

    # ── retention: durable purge and reference discovery ─────────────

    async def purge_task(self, scope: TaskScope, task_id: str) -> bool:
        """Delete one terminal task's journal and projection.

        Implements :class:`~..retention.JournalPurge`. Two guards make
        this safe to call from a sweeper that may be racing anything
        else in the system:

        **Only a terminal task is ever purged.** Retention only selects
        terminal tasks, but the check is repeated here because this is
        the last point before the rows are gone. A task that was resumed
        between selection and purge is left alone — the sweeper's view
        is a snapshot, and acting on a stale one is exactly how live work
        gets deleted.

        **Pins held by *other* tasks survive.** Deleting the row cascades
        to this task's ``task_journal`` and ``artifact_evidence`` rows
        only. A version another, still-live task references keeps that
        task's evidence row, so it stays pinned and is not swept
        afterwards. The artifact rows themselves are never touched here.

        .. warning::

           This destroys the local audit trail, including the
           ``retention_scheduled`` event recording the intent to destroy
           it. With ``archive_uri`` configured the archive carries that
           final event; without one the deletion is deliberately
           irreversible. Nothing in this method preserves in-journal
           audit, and it does not pretend to.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to remove.

        Returns:
            ``True`` when rows were removed. Idempotent: purging an
            already-purged task returns ``False`` rather than failing, so
            a retry after a crash converges instead of erroring.
        """
        async with self._unit_of_work(None) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT chatbot_id, user_id, session_id, status
                  FROM {self._t('tasks')}
                 WHERE task_id = $1
                   FOR UPDATE
                """,
                task_id,
            )
            if row is None:
                return False
            if not scope.matches(self._scope_of(row)):
                return False
            try:
                status = TaskStatus(row["status"])
            except ValueError:
                self.logger.warning(
                    "[TaskMemory] refusing to purge task %s: unrecognised status %r",
                    task_id,
                    row["status"],
                )
                return False
            if not status.is_terminal:
                self.logger.warning(
                    "[TaskMemory] refusing to purge task %s: status is %s, not terminal",
                    task_id,
                    status.value,
                )
                return False
            # The cascade removes task_journal and this task's
            # artifact_evidence rows. Artifacts themselves are deliberately
            # untouched: their retention is a separate rule with its own
            # pin check.
            await connection.execute(
                f"DELETE FROM {self._t('tasks')} WHERE task_id = $1",
                task_id,
            )
            return True

    async def live_storage_refs(self, scope: TaskScope) -> FrozenSet[str]:
        """Return every storage key an index row still points at.

        This is the "live index" half of the orphan rule. A blob absent
        from this set is *not* automatically an orphan — a publish may be
        in flight, or an archive may reference it — but a blob present in
        it is definitively not one.

        Args:
            scope: Trusted runtime scope.

        Returns:
            The referenced storage keys.
        """
        async with self._reader_connection() as connection:
            rows = await connection.fetch(
                f"""
                SELECT DISTINCT storage_ref
                  FROM {self._t('artifacts')}
                 WHERE chatbot_id = $1 AND user_id = $2 AND session_id = $3
                   AND storage_ref IS NOT NULL
                """,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
            )
        keys: List[str] = []
        for row in rows:
            raw = row["storage_ref"]
            if not raw:
                continue
            # `storage_ref` holds the serialized BlobRef, whose `key` is
            # the storage path. Reading the whole reference rather than
            # assuming the column is a bare key: it is not.
            blob = self._blob_key_of(raw)
            if blob:
                keys.append(blob)
        return frozenset(keys)

    @staticmethod
    def _blob_key_of(raw: Any) -> Optional[str]:
        """Extract the storage key from a serialized blob reference.

        Args:
            raw: The ``storage_ref`` column value.

        Returns:
            The key, or ``None`` when it cannot be read. An unreadable
            reference is reported as absent rather than guessed at: the
            caller treats "not live" conservatively via the other two
            orphan conditions.
        """
        import json

        if raw is None:
            return None
        value: Any = raw
        if isinstance(value, (str, bytes)):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return str(raw) or None
        if isinstance(value, dict):
            key = value.get("key")
            return str(key) if key else None
        return None

    @asynccontextmanager
    async def _reader_connection(self) -> AsyncIterator[Any]:
        """Yield a pooled connection for a read-only query.

        Yields:
            The connection.
        """
        pool = await self._acquire_pool()
        async with pool.acquire() as connection:
            yield connection


# ---------------------------------------------------------------------------
# Durable artifact store
# ---------------------------------------------------------------------------


class _BorrowedTransaction:
    """A transaction view over a connection this handle does not own.

    Used when the artifact store has opened its own unit of work and must
    hand that same connection to the task store's append path. It never
    commits or rolls back — the real owner does — which is what lets an
    artifact's index rows and its journal event land in one transaction
    without either store thinking it is in charge of the other's.
    """

    __slots__ = ("_connection",)

    def __init__(self, connection: Any) -> None:
        """Wrap a connection.

        Args:
            connection: A connection inside an already-open transaction.
        """
        self._connection = connection

    @property
    def connection(self) -> Any:
        """The connection every enlisted store must write through."""
        return self._connection

    @property
    def is_active(self) -> bool:
        """Always ``True``: the owner controls the real lifetime."""
        return True

    async def rollback(self) -> None:
        """No-op: this handle does not own the transaction."""
        return None


class PostgresArtifactStore:
    """Durable aliases, versions and evidence pins on PostgreSQL (Delivery B).

    The catalog backend of decision D1, made durable. It satisfies
    :class:`~parrot.interfaces.artifact_store.ArtifactStore` and must be
    *behaviourally identical* to
    :class:`~..artifacts.InMemoryArtifactStore` (AC2) — where the two
    could differ, this class follows the in-memory store's decisions
    rather than inventing its own, and the shared conformance suite runs
    against both.

    **The publish order is the guarantee** (spec §2 Persistence and
    Recovery)::

        write the immutable blob
          -> verify readability and checksum
            -> ATOMICALLY commit the alias/version index, the evidence
               rows and the `artifact_registered` journal event, on ONE
               connection

    A crash between the blob write and the commit leaves an **orphan
    blob**, which is expected and sweepable. The order exists to make the
    opposite impossible: an index row pointing at bytes that were never
    written is a phantom reference, and nothing downstream can recover
    from one.

    **Version allocation serializes on the alias row.** A writer takes
    ``SELECT ... FOR UPDATE`` on ``artifact_aliases`` before computing
    ``latest_version + 1``, so two concurrent overwrites of the same
    alias cannot both allocate the same number. PostgreSQL does here what
    the in-memory store gets from its ``asyncio.Lock``.

    **Pinning is derived, never stored.** A version is pinned while any
    *nonterminal* task references it in ``artifact_evidence`` — including
    a task other than the one that produced it. A single mutable flag
    could not express "two tasks reference this, one has finished", and
    consulting only the producing task would let a cross-task reference
    be swept out from under its holder.

    Args:
        tasks: The task store whose pool, schema and transaction
            coordinator this store shares.
        blobs: Durable byte storage
            (:class:`~..blob.ArtifactBlobStore`). Without it, versions
            are registered as metadata only and reported honestly as
            ``missing`` — durable metadata with no durable bytes is not
            evidence, and is never presented as such.
        config: Capacity configuration. Defaults to the task store's.
    """

    #: Columns every descriptor is rebuilt from. Kept as a tuple so a
    #: joined query can prefix them without string surgery.
    _COLUMN_NAMES: Tuple[str, ...] = (
        "artifact_id",
        "version",
        "chatbot_id",
        "user_id",
        "session_id",
        "task_id",
        "producer_call_id",
        "attribution",
        "alias",
        "kind",
        "availability",
        "fingerprint_algorithm",
        "fingerprint",
        "evidence_verifiable",
        "storage_ref",
        "byte_size",
        "shape",
        "schema_summary",
        "created_at",
        "invalidated",
        "invalidated_at",
    )

    #: The same columns as a bare select list.
    _COLUMNS: str = ", ".join(_COLUMN_NAMES)

    #: The same columns qualified for a join against ``artifacts a``.
    _COLUMNS_A: str = ", ".join(f"a.{_n}" for _n in _COLUMN_NAMES)

    def __init__(
        self,
        tasks: "PostgresTaskMemoryStore",
        *,
        blobs: Optional[Any] = None,
        config: Optional[TaskMemoryConfig] = None,
    ) -> None:
        """Initialize the store without connecting."""
        self._tasks = tasks
        self._blobs = blobs
        self._config = config or tasks._config
        self.logger = logging.getLogger(f"{__name__}.PostgresArtifactStore")

    # -- plumbing ----------------------------------------------------------

    def _t(self, name: str) -> str:
        """Return a schema-qualified table name.

        Args:
            name: Unqualified table name.

        Returns:
            ``"<schema>.<name>"``.
        """
        return self._tasks._t(name)

    @staticmethod
    def _ns(task_id: Optional[str]) -> str:
        """Return the alias namespace for a task.

        ``''`` means "not associated with a task". The sentinel is what
        makes the alias unique constraint actually constrain: in SQL
        ``NULL <> NULL``, so a nullable column would permit unlimited
        duplicate rows in the unassociated namespace and two concurrent
        writers would each allocate version 1 for the same key.

        Args:
            task_id: Owning task, or ``None``.

        Returns:
            The namespace value.
        """
        return task_id or ""

    def transaction(self) -> Any:
        """Open a transaction this store and the task store can share.

        Returns:
            An async context manager yielding a
            :class:`PostgresTransaction`.
        """
        return self._tasks.transaction()

    async def close(self) -> None:
        """Release resources. The pool belongs to the task store."""
        return None

    @asynccontextmanager
    async def _unit_of_work(self, transaction: Optional[Any]) -> AsyncIterator[Any]:
        """Yield a connection, joining a caller's transaction when given.

        Args:
            transaction: A transaction to enlist in, or ``None`` to open
                a private one.

        Yields:
            The connection to use.
        """
        if transaction is not None:
            yield transaction.connection
            return
        async with self.transaction() as owned:
            yield owned.connection

    @asynccontextmanager
    async def _reader(self) -> AsyncIterator[Any]:
        """Yield a pooled connection for a read-only query.

        Yields:
            The connection.
        """
        pool = await self._tasks._acquire_pool()
        async with pool.acquire() as connection:
            yield connection

    # -- row mapping -------------------------------------------------------

    @staticmethod
    def _loads(value: Any) -> Any:
        """Decode a JSONB column that may arrive as text.

        Args:
            value: The raw column value.

        Returns:
            The decoded value.
        """
        import json

        if isinstance(value, (str, bytes)):
            return json.loads(value)
        return value

    @classmethod
    def _stored_blob(cls, row: Any) -> Optional[Any]:
        """Rebuild the :class:`~..blob.BlobRef` recorded for a version.

        The whole reference — key, format, **checksum**, sizes — is
        persisted, not just the key. Without the checksum a later read
        could not tell correct bytes from corrupted ones, and silently
        returning corrupted evidence is precisely the failure the blob
        layer's read-back verification exists to prevent.

        Args:
            row: An ``artifacts`` record.

        Returns:
            The reference, or ``None`` when no bytes were retained.
        """
        raw = row["storage_ref"]
        if not raw:
            return None
        from ..blob import BlobRef

        try:
            return BlobRef.model_validate_json(raw)
        except Exception:  # noqa: BLE001 — a legacy plain key is not a usable reference
            return None

    @classmethod
    def _row_to_descriptor(cls, row: Any) -> ArtifactDescriptor:
        """Rebuild an :class:`ArtifactDescriptor` from an ``artifacts`` row.

        ``storage_ref`` is exposed as the plain storage **key**, not the
        serialized reference the column holds, so a descriptor stays
        readable and matches what the in-memory store reports.

        Args:
            row: An ``asyncpg`` record.

        Returns:
            The descriptor.
        """
        blob = cls._stored_blob(row)
        shape = cls._loads(row["shape"])
        return ArtifactDescriptor(
            ref=EvidenceRef(artifact_id=row["artifact_id"], version=row["version"]),
            alias=row["alias"],
            scope=TaskScope(chatbot_id=row["chatbot_id"], user_id=row["user_id"], session_id=row["session_id"]),
            task_id=row["task_id"],
            producer_call_id=row["producer_call_id"],
            attribution=Attribution(row["attribution"]),
            kind=ArtifactKind(row["kind"]),
            availability=ArtifactAvailability(row["availability"]),
            fingerprint=row["fingerprint"],
            fingerprint_algorithm=row["fingerprint_algorithm"],
            evidence_verifiable=row["evidence_verifiable"],
            invalidated=row["invalidated"],
            byte_size=row["byte_size"],
            shape=tuple(shape) if shape else None,
            schema_summary=cls._loads(row["schema_summary"]),
            storage_ref=blob.key if blob is not None else None,
            created_at=row["created_at"],
            invalidated_at=row["invalidated_at"],
        )

    async def _generation(self, connection: Any, scope: TaskScope) -> int:
        """Return the scope's availability generation.

        Derived from stored state rather than held in memory, so every
        pod agrees and a restart does not reset it. It must change
        whenever availability changes **without** a task event — a
        registration, an eviction or an invalidation — which is exactly
        what these three counts capture between them.

        Args:
            connection: The connection to query on.
            scope: Trusted runtime scope.

        Returns:
            A marker for this scope.
        """
        row = await connection.fetchrow(
            f"""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE invalidated) AS invalid,
                   count(*) FILTER (WHERE availability IN ('missing', 'expired')) AS gone
              FROM {self._t('artifacts')}
             WHERE chatbot_id = $1 AND user_id = $2 AND session_id = $3
            """,
            scope.chatbot_id,
            scope.user_id,
            scope.session_id,
        )
        return int(row["total"]) + int(row["invalid"]) + int(row["gone"])

    # -- registration ------------------------------------------------------

    async def put(
        self,
        scope: TaskScope,
        key: str,
        value: Any,
        *,
        task_id: Optional[str] = None,
        kind: Optional[ArtifactKind] = None,
        description: str = "",
        producer_call_id: Optional[str] = None,
        attribution: Attribution = Attribution.NONE,
        turn_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        transaction: Optional[Any] = None,
        pin_for: Optional[str] = None,
    ) -> ArtifactDescriptor:
        """Register a value durably, allocating or incrementing its version.

        Snapshotting and fingerprinting run on a worker thread **before**
        the transaction opens, so no database lock is held across CPU
        work. Only allocation, the blob write and publication happen
        inside it.

        ``pin_for`` registers and pins in one act. As in the in-memory
        store this matters for more than convenience: an unpinned version
        is an ordinary retention candidate, so a value pinned only
        afterwards can be swept before its pin ever applies.

        Args:
            scope: Trusted runtime scope.
            key: Working-memory alias to publish under.
            value: The value to register.
            task_id: Owning task, when one is selected.
            kind: Explicit evidence type; inferred when ``None``.
            description: Human-readable description, retained by the
                caller's catalog rather than stored here.
            producer_call_id: The physical attempt that produced it.
            attribution: How that attempt was attributed.
            turn_id: Conversation turn, stamped on the journal event.
            metadata: Caller metadata. Unused here; the catalog owns it.
            transaction: Shared transaction to enlist in, so the index
                rows and the journal event commit together.
            pin_for: Task id to pin this version for, atomically with
                registration.

        Returns:
            The read projection of the newly registered version.

        Raises:
            LimitExceeded: If the alias exceeds
                :data:`Limits.MAX_IDENTIFIER`.
            TaskMemoryUnavailable: If the database cannot be reached.
        """
        if len(key) > Limits.MAX_IDENTIFIER:
            raise LimitExceeded("artifact alias", Limits.MAX_IDENTIFIER, len(key))

        # Heavy work first: off the loop, outside the transaction.
        snapshot = await capture_snapshot_async(value, max_bytes=self._config.snapshot_max_bytes, kind=kind)

        async with self._unit_of_work(transaction) as connection:
            ref = await self._allocate(connection, scope, task_id, key)

            # Bytes are written and verified BEFORE any index row exists.
            # A crash here leaves an orphan blob, which retention sweeps;
            # the reverse would be a reference to bytes that never were.
            blob = None
            if self._blobs is not None:
                try:
                    blob = await self._blobs.publish(scope, ref, value, kind=snapshot.kind)
                except Exception as exc:  # noqa: BLE001 — recorded honestly below
                    self.logger.warning("[TaskMemory] durable publish failed for %s: %s", ref, exc)

            descriptor = self._descriptor_for(
                scope=scope,
                ref=ref,
                key=key,
                task_id=task_id,
                producer_call_id=producer_call_id,
                attribution=attribution,
                snapshot=snapshot,
                blob=blob,
            )

            await self._insert_version(connection, descriptor, blob)
            await self._move_alias(connection, scope, task_id, key, ref)
            if pin_for is not None:
                await self._pin(connection, pin_for, "__registration__", ref)
            if task_id is not None:
                await self._journal_registration(
                    connection, scope, task_id, descriptor, turn_id=turn_id, transaction=transaction
                )
            return descriptor

    def _descriptor_for(
        self,
        *,
        scope: TaskScope,
        ref: EvidenceRef,
        key: str,
        task_id: Optional[str],
        producer_call_id: Optional[str],
        attribution: Attribution,
        snapshot: Any,
        blob: Any,
    ) -> ArtifactDescriptor:
        """Turn a snapshot outcome and a blob result into a descriptor.

        The in-memory store's three outcomes are treated the same way,
        adjusted for the fact that durable storage — not a RAM copy — is
        what retains bytes here. ``CAPTURED`` and ``SPILL_REQUIRED`` both
        write through: the cap governs the optional RAM snapshot, not
        whether evidence survives a restart, so a small artifact is
        persisted too.

        A failed or absent blob write yields ``missing`` and
        ``evidence_verifiable=False``. Metadata without bytes is recorded
        honestly rather than presented as durable evidence.

        Args:
            scope: Owning scope.
            ref: The allocated version.
            key: The alias.
            task_id: Owning task.
            producer_call_id: Producing attempt.
            attribution: How that attempt was attributed.
            snapshot: The snapshot outcome.
            blob: The verified blob reference, or ``None``.

        Returns:
            The descriptor to store.
        """
        availability = ArtifactAvailability.MISSING
        storage_key: Optional[str] = None
        fingerprint = snapshot.fingerprint
        algorithm = snapshot.fingerprint_algorithm
        verifiable = snapshot.evidence_verifiable
        byte_size = snapshot.account.snapshot_bytes or snapshot.account.live_bytes

        if blob is not None:
            availability = ArtifactAvailability.PERSISTED
            storage_key = blob.key
            byte_size = blob.byte_size
            if blob.content_fingerprint:
                fingerprint = blob.content_fingerprint
                algorithm = blob.fingerprint_algorithm
        else:
            verifiable = False

        if not snapshot.kind.is_supported_evidence or not fingerprint:
            verifiable = False

        return ArtifactDescriptor(
            ref=ref,
            alias=key,
            scope=scope,
            task_id=task_id,
            producer_call_id=producer_call_id,
            attribution=attribution,
            kind=snapshot.kind,
            availability=availability,
            fingerprint=fingerprint,
            fingerprint_algorithm=algorithm,
            evidence_verifiable=verifiable,
            byte_size=byte_size,
            shape=snapshot.shape,
            schema_summary=snapshot.schema_summary,
            storage_ref=storage_key,
            created_at=utc_now(),
        )

    async def _allocate(self, connection: Any, scope: TaskScope, task_id: Optional[str], key: str) -> EvidenceRef:
        """Allocate the next version for an alias under a row lock.

        The alias row is the lock point. Taking ``FOR UPDATE`` on it
        before computing ``latest_version + 1`` is what stops two
        concurrent overwrites allocating the same number — and it is why
        a drop/recreate cycle CONTINUES the counter rather than
        restarting at 1, which would let a fresh unrelated version shadow
        still-pinned evidence at the same coordinates.

        Args:
            connection: The connection inside the open transaction.
            scope: Owning scope.
            task_id: Owning task namespace.
            key: The alias.

        Returns:
            The freshly allocated reference.
        """
        ns = self._ns(task_id)
        params = (scope.chatbot_id, scope.user_id, scope.session_id, ns, key)
        select_locked = f"""
            SELECT artifact_id, latest_version
              FROM {self._t('artifact_aliases')}
             WHERE chatbot_id = $1 AND user_id = $2 AND session_id = $3
               AND task_ns = $4 AND alias_key = $5
             FOR UPDATE
        """

        row = await connection.fetchrow(select_locked, *params)
        if row is None:
            # Two writers can both see no row. ON CONFLICT DO NOTHING
            # makes the loser fall through to a locked re-read, so they
            # serialize instead of both inserting.
            row = await connection.fetchrow(
                f"""
                INSERT INTO {self._t('artifact_aliases')}
                    (chatbot_id, user_id, session_id, task_ns, alias_key,
                     artifact_id, current_version, latest_version)
                VALUES ($1, $2, $3, $4, $5, $6, NULL, 0)
                ON CONFLICT (chatbot_id, user_id, session_id, task_ns, alias_key) DO NOTHING
                RETURNING artifact_id, latest_version
                """,
                *params,
                f"art_{uuid.uuid4().hex}",
            )
            if row is None:
                row = await connection.fetchrow(select_locked, *params)

        return EvidenceRef(artifact_id=row["artifact_id"], version=int(row["latest_version"]) + 1)

    async def _insert_version(self, connection: Any, descriptor: ArtifactDescriptor, blob: Any) -> None:
        """Insert the immutable ``artifacts`` row for a version.

        Args:
            connection: The connection inside the open transaction.
            descriptor: The version to record.
            blob: Its verified blob reference, persisted whole so a later
                read can verify the bytes it transferred.
        """
        await connection.execute(
            f"""
            INSERT INTO {self._t('artifacts')}
                (artifact_id, version, chatbot_id, user_id, session_id, task_id,
                 producer_call_id, attribution, alias, kind, availability,
                 fingerprint_algorithm, fingerprint, evidence_verifiable,
                 storage_ref, byte_size, shape, schema_summary, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                    $15, $16, $17::jsonb, $18::jsonb, $19)
            """,
            descriptor.ref.artifact_id,
            descriptor.ref.version,
            descriptor.scope.chatbot_id,
            descriptor.scope.user_id,
            descriptor.scope.session_id,
            descriptor.task_id,
            descriptor.producer_call_id,
            descriptor.attribution.value,
            descriptor.alias,
            descriptor.kind.value,
            descriptor.availability.value,
            descriptor.fingerprint_algorithm,
            descriptor.fingerprint,
            descriptor.evidence_verifiable,
            blob.model_dump_json() if blob is not None else None,
            descriptor.byte_size,
            self._tasks._dump(list(descriptor.shape)) if descriptor.shape else None,
            self._tasks._dump(descriptor.schema_summary) if descriptor.schema_summary else None,
            descriptor.created_at,
        )

    async def _move_alias(
        self, connection: Any, scope: TaskScope, task_id: Optional[str], key: str, ref: EvidenceRef
    ) -> None:
        """Point the alias at a newly allocated version.

        Clears any tombstone, so re-publishing under a dropped key
        revives the alias while keeping the version counter it
        accumulated.

        Args:
            connection: The connection inside the open transaction.
            scope: Owning scope.
            task_id: Owning task namespace.
            key: The alias.
            ref: The version it now names.
        """
        await connection.execute(
            f"""
            UPDATE {self._t('artifact_aliases')}
               SET current_version = $6,
                   latest_version = GREATEST(latest_version, $6),
                   tombstoned = FALSE,
                   tombstoned_at = NULL,
                   updated_at = now()
             WHERE chatbot_id = $1 AND user_id = $2 AND session_id = $3
               AND task_ns = $4 AND alias_key = $5
            """,
            scope.chatbot_id,
            scope.user_id,
            scope.session_id,
            self._ns(task_id),
            key,
            ref.version,
        )

    async def _pin(self, connection: Any, task_id: str, step_id: str, ref: EvidenceRef) -> None:
        """Record an evidence reference, which is what pins a version.

        Args:
            connection: The connection inside the open transaction.
            task_id: The referencing task.
            step_id: The referencing step.
            ref: The version referenced.
        """
        await connection.execute(
            f"""
            INSERT INTO {self._t('artifact_evidence')} (task_id, step_id, artifact_id, version)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT DO NOTHING
            """,
            task_id,
            step_id,
            ref.artifact_id,
            ref.version,
        )

    async def _journal_registration(
        self,
        connection: Any,
        scope: TaskScope,
        task_id: str,
        descriptor: ArtifactDescriptor,
        *,
        turn_id: Optional[str],
        transaction: Optional[Any],
    ) -> None:
        """Append ``artifact_registered`` on the SAME connection.

        Routed through the task store rather than writing a journal row
        directly, so sequence allocation, the task row lock and the
        reducer behave exactly as they do for every other event.

        A task id naming no task is not an error: an artifact may be
        registered against a task that has not been created yet, and
        refusing the registration for that reason would lose the artifact
        over a bookkeeping detail.

        Args:
            connection: The connection inside the open transaction.
            scope: Trusted runtime scope.
            task_id: The owning task.
            descriptor: The registered version.
            turn_id: The conversation turn.
            transaction: The caller's transaction, when it supplied one.
        """
        exists = await connection.fetchval(f"SELECT 1 FROM {self._t('tasks')} WHERE task_id = $1", task_id)
        if not exists:
            return

        event = JournalEvent(
            task_id=task_id,
            occurred_at=utc_now(),
            event_type=EventType.ARTIFACT_REGISTERED,
            actor=Actor.RUNTIME,
            turn_id=turn_id,
            payload=ArtifactPayload(
                ref=descriptor.ref,
                alias=descriptor.alias,
                artifact_kind=descriptor.kind,
                availability=descriptor.availability,
                fingerprint=descriptor.fingerprint,
                fingerprint_algorithm=descriptor.fingerprint_algorithm,
                evidence_verifiable=descriptor.evidence_verifiable,
                byte_size=descriptor.byte_size,
            ),
        )
        handle = transaction if transaction is not None else _BorrowedTransaction(connection)
        await self._tasks.append_events(scope, task_id, [event], expected_revision=None, transaction=handle)

    # -- pins --------------------------------------------------------------

    async def pin_evidence(
        self, scope: TaskScope, ref: EvidenceRef, task_id: str, *, step_id: str = "__task__"
    ) -> bool:
        """Pin a version for a task by recording an evidence reference.

        Args:
            scope: Trusted runtime scope.
            ref: The version to pin.
            task_id: The referencing task.
            step_id: The referencing step.

        Returns:
            ``True`` when the version exists in this scope and was pinned.
        """
        async with self._unit_of_work(None) as connection:
            if await self._version_row(connection, scope, ref) is None:
                return False
            await self._pin(connection, task_id, step_id, ref)
            return True

    async def unpin_evidence(self, scope: TaskScope, ref: EvidenceRef, task_id: str) -> bool:
        """Drop every reference a task holds on a version.

        Args:
            scope: Trusted runtime scope.
            ref: The version.
            task_id: The task releasing it.

        Returns:
            ``True`` when a reference was removed.
        """
        async with self._unit_of_work(None) as connection:
            if await self._version_row(connection, scope, ref) is None:
                return False
            result = await connection.execute(
                f"""
                DELETE FROM {self._t('artifact_evidence')}
                 WHERE task_id = $1 AND artifact_id = $2 AND version = $3
                """,
                task_id,
                ref.artifact_id,
                ref.version,
            )
            return not str(result).endswith(" 0")

    async def pins_for(self, scope: TaskScope, ref: EvidenceRef) -> Tuple[str, ...]:
        """Return the NONTERMINAL tasks still referencing a version.

        This is the pin query, and its shape is the point: a version is
        pinned while *any* nonterminal task references it, including one
        other than its producer. A terminal task's reference stops
        pinning, which is what lets retention proceed once every holder
        has finished — and what stops a cross-task reference being swept
        out from under a task that is still working.

        Args:
            scope: Trusted runtime scope.
            ref: The version.

        Returns:
            The pinning task ids, sorted.
        """
        async with self._reader() as connection:
            rows = await connection.fetch(
                f"""
                SELECT DISTINCT e.task_id
                  FROM {self._t('artifact_evidence')} e
                  JOIN {self._t('tasks')} t ON t.task_id = e.task_id
                  JOIN {self._t('artifacts')} a
                    ON a.artifact_id = e.artifact_id AND a.version = e.version
                 WHERE e.artifact_id = $1 AND e.version = $2
                   AND a.chatbot_id = $3 AND a.user_id = $4 AND a.session_id = $5
                   AND t.status NOT IN ('completed', 'failed', 'cancelled')
                 ORDER BY e.task_id
                """,
                ref.artifact_id,
                ref.version,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
            )
            return tuple(r["task_id"] for r in rows)

    # -- reads -------------------------------------------------------------

    async def _version_row(self, connection: Any, scope: TaskScope, ref: EvidenceRef) -> Optional[Any]:
        """Fetch one version row, enforcing scope.

        Args:
            connection: The connection to query on.
            scope: Trusted runtime scope.
            ref: The exact version.

        Returns:
            The row, or ``None`` when it does not exist in this scope.
        """
        return await connection.fetchrow(
            f"""
            SELECT {self._COLUMNS}
              FROM {self._t('artifacts')}
             WHERE artifact_id = $1 AND version = $2
               AND chatbot_id = $3 AND user_id = $4 AND session_id = $5
            """,
            ref.artifact_id,
            ref.version,
            scope.chatbot_id,
            scope.user_id,
            scope.session_id,
        )

    async def get_current(
        self, scope: TaskScope, key: str, *, task_id: Optional[str] = None
    ) -> Optional[ArtifactDescriptor]:
        """Resolve an alias to the version it currently points at.

        A plain key never searches another task's namespace, and a
        tombstoned alias resolves to nothing.

        Args:
            scope: Trusted runtime scope.
            key: The alias.
            task_id: Owning task namespace.

        Returns:
            The current descriptor, or ``None``.
        """
        async with self._reader() as connection:
            row = await connection.fetchrow(
                f"""
                SELECT {self._COLUMNS_A}
                  FROM {self._t('artifact_aliases')} al
                  JOIN {self._t('artifacts')} a
                    ON a.artifact_id = al.artifact_id AND a.version = al.current_version
                 WHERE al.chatbot_id = $1 AND al.user_id = $2 AND al.session_id = $3
                   AND al.task_ns = $4 AND al.alias_key = $5
                   AND NOT al.tombstoned
                """,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
                self._ns(task_id),
                key,
            )
            return self._row_to_descriptor(row) if row is not None else None

    async def get_version(
        self, scope: TaskScope, ref: EvidenceRef, *, task_id: Optional[str] = None
    ) -> Optional[ArtifactDescriptor]:
        """Resolve one exact version, checking scope.

        A globally unique artifact id is an identifier, not a capability:
        the scope check is not optional. A same-scope cross-task
        reference must be explicit, so a ``task_id`` mismatch reports the
        version as absent rather than resolving it implicitly.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.
            task_id: Owning task, when validating a cross-task reference.

        Returns:
            The descriptor, or ``None``.
        """
        async with self._reader() as connection:
            row = await self._version_row(connection, scope, ref)
            if row is None:
                return None
            if task_id is not None and row["task_id"] not in (None, task_id):
                return None
            return self._row_to_descriptor(row)

    async def load_payload(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        *,
        max_bytes: int,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> PayloadResult:
        """Materialize a version's payload under a hard byte ceiling.

        The bounds are delegated to the blob store, which checks the
        stored object's size *before* downloading it and verifies the
        checksum of what it transferred. A refusal never carries a
        payload.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.
            max_bytes: Ceiling on the decoded payload. ``0`` never
                materializes.
            offset: First row, for a tabular page.
            limit: Row count, for a tabular page.

        Returns:
            A result carrying either the payload or a refusal.
        """
        async with self._reader() as connection:
            row = await self._version_row(connection, scope, ref)

        if row is None:
            return PayloadResult(
                ref=ref,
                kind=ArtifactKind.OBJECT,
                refusal=PayloadRefusal.MISSING,
                guidance="no such artifact version in this scope",
            )

        descriptor = self._row_to_descriptor(row)
        if descriptor.invalidated:
            return PayloadResult(
                ref=ref,
                kind=descriptor.kind,
                refusal=PayloadRefusal.INVALIDATED,
                byte_size=descriptor.byte_size,
                guidance="this version's content was invalidated; re-run the step that produced it",
            )

        blob = self._stored_blob(row)
        if self._blobs is None or blob is None:
            return PayloadResult(
                ref=ref,
                kind=descriptor.kind,
                refusal=PayloadRefusal.MISSING,
                byte_size=descriptor.byte_size,
                guidance="no durable bytes were retained for this version",
            )
        return await self._blobs.load(scope, ref, blob, max_bytes=max_bytes, offset=offset, limit=limit)

    async def list(
        self,
        scope: TaskScope,
        *,
        task_id: Optional[str] = None,
        kinds: Optional[Sequence[ArtifactKind]] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        as_of_seq: Optional[int] = None,
    ) -> ArtifactPage:
        """Page artifact descriptors in a scope.

        Descriptors are metadata only: building a page reads no blob,
        calls no ``repr()`` and computes no summary.

        Args:
            scope: Trusted runtime scope.
            task_id: Restrict to one task's namespace.
            kinds: Restrict to these evidence types.
            limit: Bounded page size.
            cursor: Opaque cursor from a previous page.
            as_of_seq: Recorded in the cursor query, for symmetry with
                the in-memory store.

        Returns:
            A bounded page of descriptors.

        Raises:
            CursorError: If the cursor is malformed, out of bounds, or
                issued for a different scope or query.
        """
        size = bounded_limit(limit, default=50)
        wanted = tuple(k.value for k in kinds) if kinds else None
        query = {"task_id": task_id, "kinds": wanted, "as_of_seq": as_of_seq}

        offset = 0
        if cursor is not None:
            offset = int(decode_cursor(cursor, scope, query)["offset"])

        filters = (scope.chatbot_id, scope.user_id, scope.session_id, task_id, list(wanted) if wanted else None)
        predicate = """
             WHERE chatbot_id = $1 AND user_id = $2 AND session_id = $3
               AND ($4::text IS NULL OR task_id = $4)
               AND ($5::text[] IS NULL OR kind = ANY($5))
        """

        async with self._reader() as connection:
            total = int(await connection.fetchval(f"SELECT count(*) FROM {self._t('artifacts')} {predicate}", *filters))
            if offset > total:
                raise CursorError("cursor is out of bounds")

            rows = await connection.fetch(
                f"""
                SELECT {self._COLUMNS} FROM {self._t('artifacts')} {predicate}
                 ORDER BY artifact_id, version
                 LIMIT $6 OFFSET $7
                """,
                *filters,
                size,
                offset,
            )
            generation = await self._generation(connection, scope)

        next_cursor = encode_cursor(scope, query, {"offset": offset + size}) if offset + size < total else None
        return ArtifactPage(
            items=tuple(self._row_to_descriptor(r) for r in rows),
            next_cursor=next_cursor,
            availability_generation=generation,
        )

    # -- mutation ----------------------------------------------------------

    async def invalidate(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        *,
        reason: str,
        transaction: Optional[Any] = None,
    ) -> ArtifactDescriptor:
        """Mark one version's content as no longer valid evidence.

        Bytes are left alone: invalidation is a statement about
        *evidence*, not about storage, and a persisted payload remains on
        disk. ``evidence_verifiable`` is cleared, because a fingerprint
        that no longer describes the content proves nothing.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.
            reason: Why.
            transaction: Shared transaction to enlist in.

        Returns:
            The updated descriptor.

        Raises:
            ScopeViolation: If the version does not exist in this scope.
        """
        async with self._unit_of_work(transaction) as connection:
            row = await connection.fetchrow(
                f"""
                UPDATE {self._t('artifacts')}
                   SET invalidated = TRUE,
                       invalidated_at = now(),
                       invalidated_reason = $6,
                       evidence_verifiable = FALSE
                 WHERE artifact_id = $1 AND version = $2
                   AND chatbot_id = $3 AND user_id = $4 AND session_id = $5
             RETURNING {self._COLUMNS}
                """,
                ref.artifact_id,
                ref.version,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
                reason,
            )
            if row is None:
                raise ScopeViolation("artifact version does not exist in this scope")
            self.logger.info("[TaskMemory] invalidated %s: %s", ref, reason)
            return self._row_to_descriptor(row)

    async def evict(self, scope: TaskScope, ref: EvidenceRef) -> bool:
        """Release a version's stored bytes, keeping its metadata.

        Explicit eviction does **not** invalidate: the caller asked for
        the bytes back, and the fingerprint still describes what the
        version contained. A metadata tombstone always remains, so no
        step is left labelled valid against evidence that silently
        vanished.

        The index row is updated first and the object deleted afterwards.
        A crash between them leaves an orphan blob, which retention
        sweeps — the opposite order would leave the index pointing at
        bytes that are already gone.

        Args:
            scope: Trusted runtime scope.
            ref: The exact version.

        Returns:
            ``True`` when bytes were released.
        """
        async with self._unit_of_work(None) as connection:
            row = await self._version_row(connection, scope, ref)
            if row is None:
                return False
            blob = self._stored_blob(row)
            if blob is None:
                return False
            await connection.execute(
                f"""
                UPDATE {self._t('artifacts')}
                   SET availability = 'missing', storage_ref = NULL
                 WHERE artifact_id = $1 AND version = $2
                   AND chatbot_id = $3 AND user_id = $4 AND session_id = $5
                """,
                ref.artifact_id,
                ref.version,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
            )

        if self._blobs is not None:
            await self._blobs.delete(scope, blob)
        return True

    async def drop_alias(self, scope: TaskScope, key: str, *, task_id: Optional[str] = None) -> bool:
        """Remove a live alias without deleting the versions behind it.

        The identity and its version counter survive as a **tombstone**,
        so a later re-``put`` under the same key continues at
        ``latest + 1``. Restarting at 1 would let a fresh, unrelated
        version shadow still-pinned evidence at the same coordinates.

        Args:
            scope: Trusted runtime scope.
            key: The alias to remove.
            task_id: Owning task namespace.

        Returns:
            ``True`` when the alias existed and was live.
        """
        async with self._unit_of_work(None) as connection:
            result = await connection.execute(
                f"""
                UPDATE {self._t('artifact_aliases')}
                   SET current_version = NULL,
                       tombstoned = TRUE,
                       tombstoned_at = now(),
                       updated_at = now()
                 WHERE chatbot_id = $1 AND user_id = $2 AND session_id = $3
                   AND task_ns = $4 AND alias_key = $5
                   AND NOT tombstoned
                """,
                scope.chatbot_id,
                scope.user_id,
                scope.session_id,
                self._ns(task_id),
                key,
            )
            return not str(result).endswith(" 0")


async def _main(argv: Optional[Sequence[str]] = None) -> int:
    """Apply or revert the migration from the command line.

    Args:
        argv: Argument vector; ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Apply the FEAT-538 task-memory migration.")
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--schema", default=SCHEMA_NAME, help="Schema to operate in")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="Apply the migration")
    group.add_argument("--verify", action="store_true", help="Verify the schema")
    group.add_argument(
        "--revert",
        action="store_true",
        help="DESTRUCTIVE: drop the schema and everything in it",
    )
    args = parser.parse_args(argv)

    store = PostgresTaskMemoryStore(args.dsn, schema=args.schema)
    try:
        if args.apply:
            version = await store.apply_migrations()
            print(f"applied task-memory migration {version} to schema {args.schema}")
        elif args.verify:
            await store.verify_schema()
            print(f"schema {args.schema} is at task-memory migration {MIGRATION_VERSION}")
        else:
            await store.revert_migrations()
            print(f"reverted task-memory migration; schema {args.schema} dropped")
    except TaskMemoryUnavailable as exc:
        print(f"error: {exc}")
        return 1
    finally:
        await store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    import asyncio
    import sys

    sys.exit(asyncio.run(_main()))
