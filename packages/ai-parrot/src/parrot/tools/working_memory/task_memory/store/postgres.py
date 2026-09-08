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

What it does **not** own: durable aliases, versions and evidence pins,
which belong to the artifact store. Those methods raise
:class:`NotImplementedError` naming their owner rather than shipping a
plausible-looking implementation that silently does the wrong thing.

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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional, Sequence, Tuple

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
    EventType,
    JournalEvent,
    LimitExceeded,
    ReducerError,
    RevisionConflict,
    ScopeViolation,
    TaskLifecyclePayload,
    TaskMemoryUnavailable,
    TaskScope,
    TaskState,
    TaskStatus,
)
from ..reducer import REDUCER_VERSION, reduce, replay
from ._base import BaseTaskMemoryStore, goal_preview

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
)

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

    What this class does **not** own: durable aliases, versions and
    evidence pins, which belong to the artifact store. Those methods
    raise :class:`NotImplementedError` naming their owner rather than
    shipping a plausible-looking implementation that silently does the
    wrong thing.

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
