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

What it does **not** own: task and artifact CRUD. The durable journal and
reducer projections are TASK-2995; durable aliases, versions and evidence
pins are TASK-2997. The methods those tasks fill in raise
:class:`NotImplementedError` here naming their owner, rather than
shipping a plausible-looking implementation that silently does the wrong
thing.

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

from ..models import JournalEvent, TaskMemoryUnavailable, TaskScope, TaskStatus
from ._base import BaseTaskMemoryStore

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import asyncpg
    from parrot.interfaces.task_memory import AppendResult, EventPage, TaskPage, TaskSnapshot

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

    Only the schema lifecycle, the pool and the transaction coordinator
    are implemented here. The command and read paths belong to TASK-2995
    (journal + projections) and TASK-2997 (aliases, versions, evidence
    pins), and raise :class:`NotImplementedError` naming their owner
    until then.

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
    ) -> None:
        """Initialize the store without connecting."""
        if dsn is None and pool is None:
            raise ValueError("PostgresTaskMemoryStore requires either a dsn or an existing pool")
        self._dsn = dsn
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

    # -- command and read paths owned by later tasks -----------------------

    async def create_task(
        self,
        scope: TaskScope,
        *,
        goal: str,
        events: Sequence[JournalEvent],
        transaction: Optional[PostgresTransaction] = None,
    ) -> "AppendResult":
        """Not implemented here — TASK-2995 owns the durable journal."""
        raise NotImplementedError(
            "PostgresTaskMemoryStore.create_task is implemented by TASK-2995 "
            "(durable task journal and reducer projections)"
        )

    async def append_events(
        self,
        scope: TaskScope,
        task_id: str,
        events: Sequence[JournalEvent],
        *,
        expected_revision: Optional[int] = None,
        transaction: Optional[PostgresTransaction] = None,
    ) -> "AppendResult":
        """Not implemented here — TASK-2995 owns the durable journal."""
        raise NotImplementedError(
            "PostgresTaskMemoryStore.append_events is implemented by TASK-2995 "
            "(durable task journal and reducer projections)"
        )

    async def load_snapshot(self, scope: TaskScope, task_id: str) -> Optional["TaskSnapshot"]:
        """Not implemented here — TASK-2995 owns the durable journal."""
        raise NotImplementedError("PostgresTaskMemoryStore.load_snapshot is implemented by TASK-2995")

    async def list_tasks(
        self,
        scope: TaskScope,
        *,
        statuses: Optional[Sequence[TaskStatus]] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> "TaskPage":
        """Not implemented here — TASK-2995 owns the durable journal."""
        raise NotImplementedError("PostgresTaskMemoryStore.list_tasks is implemented by TASK-2995")

    async def list_events(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 50,
        as_of_seq: Optional[int] = None,
    ) -> "EventPage":
        """Not implemented here — TASK-2995 owns the durable journal."""
        raise NotImplementedError("PostgresTaskMemoryStore.list_events is implemented by TASK-2995")

    async def count_events(self, scope: TaskScope, task_id: str) -> int:
        """Not implemented here — TASK-2995 owns the durable journal."""
        raise NotImplementedError("PostgresTaskMemoryStore.count_events is implemented by TASK-2995")


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
