"""Base repository — where tenant isolation is enforced, once.

Every SaaS table carries a ``tenant_id`` column rather than living in a
per-tenant Postgres schema. That choice trades a physical boundary for a
logical one, so the logical one has to be hard to get wrong. This module makes
it hard in three ways:

1. The data helpers (:meth:`BaseRepository.fetch_one`, :meth:`fetch_all`,
   :meth:`execute`) take ``tenant_id`` as their **first positional argument,
   with no default**, and bind it as ``$1``. A caller cannot forget it — the
   call simply does not typecheck at runtime.
2. They **reject SQL that does not mention ``tenant_id``**. Passing the right
   argument to a query that ignores it is the realistic failure mode; this
   catches it at the call, not in a review.
3. Cross-tenant administration is possible but must be spelled
   ``admin_fetch_all`` / ``admin_execute``. Auditing the isolation of this
   package is therefore "grep for ``admin_``", which is a short list.

The driver is ``asyncdb`` (the repository's convention — see
``PostgresResultStorage`` and ``DurableCheckpointStore``). Note its ``pg``
driver exposes ``fetch_one(sentence, *args)`` / ``fetch_all(...)`` /
``execute(...)`` for parameterised queries; ``fetchrow``/``fetch`` have
different signatures entirely and silently break when called with arguments.

**Every operation borrows its own connection from a pool.** An earlier version
held a single shared ``AsyncDB``, which does not survive concurrency: asyncpg
guards each operation with ``_Atomic`` and raises ``InterfaceError: cannot
perform operation: another operation is in progress`` the moment a second
coroutine touches the same connection. Four concurrent reads on one connection
produce one result and three errors — verified, and the reason
``test_base_repository_concurrency.py`` exists.

A pool is also what makes :meth:`BaseRepository.transaction` meaningful. A
``SELECT ... FOR UPDATE`` only serialises writers if each holds its *own*
connection; on a shared one the lock would be re-entered by the same session
and the coupon issuer's budget check would let every caller through.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any, AsyncIterator, Optional, Sequence

from asyncdb import AsyncDB, AsyncPool
from navconfig.logging import logging

#: Schema and table names are interpolated into SQL — they cannot be bound as
#: parameters — so they are validated before any statement is issued.
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


class TenantScopeError(RuntimeError):
    """Raised when a tenant-scoped query is missing its tenant predicate.

    A programming error, never an operational one: it means a query that reads
    or writes tenant data was written without filtering by tenant.
    """


def check_identifier(value: str, what: str = "identifier") -> str:
    """Validate a SQL identifier destined for string interpolation.

    Args:
        value: Candidate schema or table name.
        what: Role name used in the error message.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If it does not match ``^[a-z_][a-z0-9_]*$``.
    """
    if not _IDENT_RE.match(value or ""):
        raise ValueError(f"unsafe {what} name: {value!r}")
    return value


class BaseRepository:
    """Async Postgres repository with mandatory tenant scoping.

    Args:
        dsn: PostgreSQL DSN.
        schema: Schema owning the SaaS tables.

    Attributes:
        logger: Module logger.
    """

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "saas",
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._schema = check_identifier(schema, "schema")
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[AsyncPool] = None
        self._pool_lock = asyncio.Lock()
        self.logger = logging.getLogger(
            f"parrot_saas.db.{type(self).__name__}"
        )

    # -- connection --------------------------------------------------------

    @property
    def schema(self) -> str:
        """The Postgres schema this repository reads and writes."""
        return self._schema

    def table(self, name: str) -> str:
        """Return a schema-qualified, validated table name.

        Args:
            name: Bare table name.

        Returns:
            ``"<schema>.<name>"``.
        """
        return f"{self._schema}.{check_identifier(name, 'table')}"

    async def pool(self) -> AsyncPool:
        """Return the connection pool, creating it on first use.

        Double-checked under a lock so a burst of concurrent requests creates
        one pool rather than several.
        """
        if self._pool is not None and self._pool.is_connected():
            return self._pool
        async with self._pool_lock:
            if self._pool is not None and self._pool.is_connected():
                return self._pool
            pool = AsyncPool(
                "pg",
                dsn=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
            )
            await pool.connect()
            self._pool = pool
            return pool

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[AsyncDB]:
        """Borrow a connection for the duration of the block.

        Use this when several statements must run on the *same* connection —
        a transaction, a ``FOR UPDATE`` lock, a cursor. Single statements
        should go through the tenant-scoped helpers instead, which borrow and
        return a connection each.

        Yields:
            A connected ``AsyncDB``.
        """
        pool = await self.pool()
        conn = await pool.acquire()
        try:
            yield conn
        finally:
            await pool.release(conn)

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncDB]:
        """Borrow a connection with a transaction already open.

        Commits on a clean exit, rolls back on any exception. The driver
        exposes ``transaction()`` / ``commit()`` / ``rollback()`` but *not* as
        a context manager, and it stores the in-flight transaction on the
        connection object — so hand-rolling this is how a forgotten rollback
        leaks a half-applied write into the next borrower of that connection.

        Yields:
            A connected ``AsyncDB`` inside an open transaction.
        """
        async with self.acquire() as conn:
            await conn.transaction()
            try:
                yield conn
            except BaseException:
                await conn.rollback()
                raise
            else:
                await conn.commit()

    async def connection(self) -> AsyncDB:
        """Return a pooled connection **that the caller must release**.

        Kept for the start-up path, which hands a raw connection to
        ``ensure_schema``. Everything else should use :meth:`acquire`, which
        cannot forget to give the connection back.

        Returns:
            A connected ``AsyncDB`` borrowed from the pool.
        """
        pool = await self.pool()
        return await pool.acquire()

    async def release(self, conn: AsyncDB) -> None:
        """Return a connection taken with :meth:`connection` to the pool."""
        if self._pool is not None:
            await self._pool.release(conn)

    async def aclose(self) -> None:
        """Close the pool if open."""
        if self._pool is not None:
            with contextlib.suppress(Exception):
                await self._pool.close()
        self._pool = None

    async def __aenter__(self) -> "BaseRepository":
        """Open the pool on context entry."""
        await self.pool()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the pool on context exit."""
        await self.aclose()

    # -- tenant-scoped access ---------------------------------------------

    @staticmethod
    def _require_tenant_predicate(sql: str) -> None:
        """Reject SQL that touches tenant data without naming ``tenant_id``.

        Args:
            sql: The statement about to be issued.

        Raises:
            TenantScopeError: If ``tenant_id`` does not appear in the
                statement.
        """
        if "tenant_id" not in sql:
            raise TenantScopeError(
                "refusing to run a tenant-scoped statement that does not "
                "reference tenant_id; use the admin_* helpers for deliberate "
                f"cross-tenant access. SQL: {sql.strip()[:120]}"
            )

    async def fetch_one(
        self, tenant_id: str, sql: str, *params: Any
    ) -> Optional[Any]:
        """Run a tenant-scoped query returning at most one row.

        ``tenant_id`` is bound as ``$1``; ``params`` follow from ``$2``.

        Args:
            tenant_id: Owning tenant. Mandatory and positional by design.
            sql: Statement referencing ``tenant_id`` and using ``$1`` for it.
            *params: Remaining bind parameters.

        Returns:
            The row, or ``None``.

        Raises:
            TenantScopeError: If ``sql`` has no tenant predicate.
        """
        self._require_tenant_predicate(sql)
        async with self.acquire() as conn:
            return await conn.fetch_one(sql, tenant_id, *params)

    async def fetch_all(
        self, tenant_id: str, sql: str, *params: Any
    ) -> Sequence[Any]:
        """Run a tenant-scoped query returning many rows.

        Args:
            tenant_id: Owning tenant.
            sql: Statement referencing ``tenant_id``, bound as ``$1``.
            *params: Remaining bind parameters.

        Returns:
            The rows, possibly empty.

        Raises:
            TenantScopeError: If ``sql`` has no tenant predicate.
        """
        self._require_tenant_predicate(sql)
        async with self.acquire() as conn:
            return await conn.fetch_all(sql, tenant_id, *params) or []

    async def execute(self, tenant_id: str, sql: str, *params: Any) -> Any:
        """Run a tenant-scoped statement.

        Args:
            tenant_id: Owning tenant.
            sql: Statement referencing ``tenant_id``, bound as ``$1``.
            *params: Remaining bind parameters.

        Returns:
            Whatever the driver returns.

        Raises:
            TenantScopeError: If ``sql`` has no tenant predicate.
        """
        self._require_tenant_predicate(sql)
        async with self.acquire() as conn:
            return await conn.execute(sql, tenant_id, *params)

    # -- deliberate cross-tenant access ------------------------------------
    #
    # Named so that auditing this package's isolation is a grep for `admin_`.

    async def admin_fetch_one(self, sql: str, *params: Any) -> Optional[Any]:
        """Run a query that is deliberately not scoped to one tenant."""
        async with self.acquire() as conn:
            return await conn.fetch_one(sql, *params)

    async def admin_fetch_all(self, sql: str, *params: Any) -> Sequence[Any]:
        """Run a listing that deliberately spans tenants."""
        async with self.acquire() as conn:
            return await conn.fetch_all(sql, *params) or []

    async def admin_execute(self, sql: str, *params: Any) -> Any:
        """Run a statement that is deliberately not scoped to one tenant."""
        async with self.acquire() as conn:
            return await conn.execute(sql, *params)


__all__ = ("BaseRepository", "TenantScopeError", "check_identifier")
