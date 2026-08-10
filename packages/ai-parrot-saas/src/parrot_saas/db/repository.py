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
"""
from __future__ import annotations

import re
from typing import Any, Optional, Sequence

from asyncdb import AsyncDB
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

    def __init__(self, dsn: str, *, schema: str = "saas") -> None:
        self._dsn = dsn
        self._schema = check_identifier(schema, "schema")
        self._conn: Optional[AsyncDB] = None
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

    async def connection(self) -> AsyncDB:
        """Return an open connection, opening one on first use."""
        if self._conn is None:
            self._conn = AsyncDB("pg", dsn=self._dsn)
        if not self._conn.is_connected():
            await self._conn.connection()
        return self._conn

    async def aclose(self) -> None:
        """Close the connection if open."""
        if self._conn is not None and self._conn.is_connected():
            await self._conn.close()
        self._conn = None

    async def __aenter__(self) -> "BaseRepository":
        """Open the connection on context entry."""
        await self.connection()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the connection on context exit."""
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
        conn = await self.connection()
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
        conn = await self.connection()
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
        conn = await self.connection()
        return await conn.execute(sql, tenant_id, *params)

    # -- deliberate cross-tenant access ------------------------------------
    #
    # Named so that auditing this package's isolation is a grep for `admin_`.

    async def admin_fetch_one(self, sql: str, *params: Any) -> Optional[Any]:
        """Run a query that is deliberately not scoped to one tenant."""
        conn = await self.connection()
        return await conn.fetch_one(sql, *params)

    async def admin_fetch_all(self, sql: str, *params: Any) -> Sequence[Any]:
        """Run a listing that deliberately spans tenants."""
        conn = await self.connection()
        return await conn.fetch_all(sql, *params) or []

    async def admin_execute(self, sql: str, *params: Any) -> Any:
        """Run a statement that is deliberately not scoped to one tenant."""
        conn = await self.connection()
        return await conn.execute(sql, *params)


__all__ = ("BaseRepository", "TenantScopeError", "check_identifier")
