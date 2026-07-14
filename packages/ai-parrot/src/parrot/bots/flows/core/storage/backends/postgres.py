"""PostgresResultStorage — Postgres backend for crew/flow execution results (FEAT-147).

One row per execution in a ``jsonb``-payload table; idempotent DDL on first write.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from navconfig.logging import logging
from asyncdb import AsyncDB

from parrot.conf import CREW_RESULT_STORAGE_PG_DSN
from .base import ResultStorage


_TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_NAMED_COLUMNS = frozenset(
    (
        "crew_name", "method", "user_id", "session_id", "timestamp",
        "execution_id", "tenant", "prompt",
    )
)


class PostgresResultStorage(ResultStorage):
    """Persist crew/flow execution results to Postgres (one row per execution).

    On first ``save()`` per table the backend issues idempotent DDL
    (``CREATE TABLE IF NOT EXISTS`` + two indexes). Subsequent saves for the
    same table skip the DDL (in-process cache on ``self._initialised``).

    The ``collection`` argument selects the table name and is validated
    against ``^[a-z_][a-z0-9_]*$`` before any SQL is issued to prevent
    injection.
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        """Initialise the Postgres backend.

        Args:
            dsn: PostgreSQL DSN; defaults to ``CREW_RESULT_STORAGE_PG_DSN``.
        """
        self._dsn = dsn or CREW_RESULT_STORAGE_PG_DSN
        self._conn: Optional[AsyncDB] = None
        self._initialised: set[str] = set()
        self.logger = logging.getLogger("parrot.crew_storage.postgres")

    async def _ensure(self) -> AsyncDB:
        """Lazily open the Postgres connection on first use."""
        if self._conn is None:
            self._conn = AsyncDB("pg", dsn=self._dsn)
            await self._conn.connection()
        return self._conn

    async def _ensure_table(self, conn: AsyncDB, table: str) -> None:
        """Issue idempotent DDL for *table* if not yet done in this process.

        Args:
            conn: Open asyncdb connection.
            table: Validated table name.
        """
        # Validate before the cache check (defense-in-depth): every call site
        # builds SQL by f-string-interpolating `table`, so this must hold
        # regardless of whether DDL has already run for this table name.
        if not _TABLE_RE.match(table):
            raise ValueError(
                f"Refusing to issue DDL for unsafe table name: {table!r}"
            )
        if table in self._initialised:
            return
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            f"  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),"
            f"  crew_name     text        NOT NULL,"
            f"  method        text        NOT NULL,"
            f"  user_id       text,"
            f"  session_id    text,"
            f"  execution_id  text,"
            f"  timestamp     timestamptz NOT NULL DEFAULT now(),"
            f"  payload       jsonb       NOT NULL"
            f")"
        )
        # Idempotent — covers tables created before execution_id existed.
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS execution_id text"
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_crew_name_idx ON {table} (crew_name)"
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_session_id_idx ON {table} (session_id)"
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_execution_id_idx ON {table} (execution_id)"
        )
        # FEAT-307: idempotent DDL to add tenant/prompt columns + composite index
        # to tables created before this feature shipped.
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant TEXT NOT NULL DEFAULT 'global'"
        )
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS prompt TEXT"
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_tenant_user_idx ON {table} (tenant, user_id)"
        )
        self._initialised.add(table)

    async def save(self, collection: str, document: dict[str, Any]) -> None:
        """Insert one execution record into the target table.

        Args:
            collection: Table name (validated against safe-name regex).
            document: Execution result document.
        """
        try:
            conn = await self._ensure()
            await self._ensure_table(conn, collection)

            crew_name = document.get("crew_name", "unknown")
            method = document.get("method", "unknown")
            user_id = document.get("user_id")
            session_id = document.get("session_id")
            execution_id = document.get("execution_id")
            tenant = document.get("tenant", "global")
            prompt = document.get("prompt")
            ts_raw = document.get("timestamp")
            timestamp = (
                datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                if isinstance(ts_raw, (int, float))
                else datetime.now(tz=timezone.utc)
            )

            payload_dict = {k: v for k, v in document.items() if k not in _NAMED_COLUMNS}
            # Spec §7 gotcha: bare-string `result` must be wrapped as {"raw": ...}
            if isinstance(payload_dict.get("result"), str):
                payload_dict["result"] = {"raw": payload_dict["result"]}
            payload = json.dumps(payload_dict, default=str)

            await conn.execute(
                f"INSERT INTO {collection} "
                "(crew_name, method, user_id, session_id, execution_id, timestamp, tenant, prompt, payload) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                crew_name,
                method,
                user_id,
                session_id,
                execution_id,
                timestamp,
                tenant,
                prompt,
                payload,
            )
        except Exception as exc:
            self.logger.warning(
                "PostgresResultStorage save failed for collection=%s: %s",
                collection,
                exc,
            )

    async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]:
        """Return all rows in *collection* whose ``execution_id`` matches.

        Named columns are merged with the ``payload`` jsonb blob to
        reconstruct the original document shape.

        Args:
            collection: Table name (validated against safe-name regex).
            execution_id: Crew-level execution id to filter by.

        Returns:
            List of reconstructed documents; empty list when nothing matches.

        Raises:
            Exception: Connection/query errors are logged then re-raised —
                unlike ``save()``, read failures must not be silently
                swallowed into an empty result.
        """
        try:
            conn = await self._ensure()
            await self._ensure_table(conn, collection)
            # FEAT-307: include tenant/prompt so fetch() and list()/get() never
            # diverge in the document shape they return for the same table.
            rows = await conn.execute(
                f"SELECT crew_name, method, user_id, session_id, "
                f"execution_id, timestamp, tenant, prompt, payload FROM {collection} "
                "WHERE execution_id = $1",
                execution_id,
            )
            documents: list[dict[str, Any]] = []
            for row in rows or []:
                row_dict = dict(row)
                payload = row_dict.pop("payload", {}) or {}
                if isinstance(payload, str):
                    payload = json.loads(payload)
                documents.append({**row_dict, **payload})
            return documents
        except Exception as exc:
            self.logger.warning(
                "PostgresResultStorage fetch failed for collection=%s, execution_id=%s: %s",
                collection,
                execution_id,
                exc,
            )
            raise

    async def close(self) -> None:
        """Release the Postgres connection. Safe to call multiple times."""
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None
                self._initialised.clear()

    # ──────────────────────────────────────────────────────────────────
    # Read methods (FEAT-307)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_where(filters: Optional[dict[str, Any]]) -> tuple[list[str], list[Any]]:
        """Build a parameterized ``WHERE`` clause from a plain-dict filter set.

        Legacy rows with ``tenant IS NULL`` are matched via
        ``COALESCE(tenant, 'global')`` so pre-FEAT-307 records remain visible
        under the ``"global"`` tenant.

        Args:
            filters: Optional filters: ``tenant``, ``user_id``, ``crew_name``,
                ``method``, ``date_from``, ``date_to``.

        Returns:
            A tuple of ``(conditions, params)`` where ``conditions`` is a list
            of SQL condition fragments using ``$N`` placeholders and ``params``
            is the ordered list of bound values.
        """
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        filters = filters or {}
        if filters.get("tenant"):
            conditions.append(f"COALESCE(tenant, 'global') = ${idx}")
            params.append(filters["tenant"])
            idx += 1
        if filters.get("user_id"):
            conditions.append(f"user_id = ${idx}")
            params.append(filters["user_id"])
            idx += 1
        if filters.get("crew_name"):
            conditions.append(f"crew_name = ${idx}")
            params.append(filters["crew_name"])
            idx += 1
        if filters.get("method"):
            conditions.append(f"method = ${idx}")
            params.append(filters["method"])
            idx += 1
        if filters.get("date_from"):
            conditions.append(f"timestamp >= ${idx}")
            params.append(filters["date_from"])
            idx += 1
        if filters.get("date_to"):
            conditions.append(f"timestamp <= ${idx}")
            params.append(filters["date_to"])
            idx += 1

        return conditions, params

    @staticmethod
    def _row_to_document(row: Any) -> dict[str, Any]:
        """Convert a fetched row into an execution document.

        The ``payload`` jsonb column is parsed into a plain dict (drivers may
        return it as a JSON-encoded string or as an already-decoded dict).

        Args:
            row: A dict-like row as returned by ``conn.fetch``/``conn.fetchrow``.

        Returns:
            A plain dict with ``id`` stringified and ``payload`` parsed.
        """
        doc = dict(row)
        raw_payload = doc.get("payload")
        if isinstance(raw_payload, str):
            doc["payload"] = json.loads(raw_payload) if raw_payload else {}
        elif not isinstance(raw_payload, dict):
            doc["payload"] = {}
        if "id" in doc and doc["id"] is not None and not isinstance(doc["id"], str):
            doc["id"] = str(doc["id"])
        return doc

    async def list(
        self,
        collection: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List execution documents ordered by ``timestamp DESC``.

        Args:
            collection: Table name (validated against safe-name regex).
            filters: Optional filters — see :meth:`_build_where`.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip (pagination).

        Returns:
            A list of execution documents, newest first. Empty list on error
            or when no rows match.
        """
        try:
            conn = await self._ensure()
            await self._ensure_table(conn, collection)

            conditions, params = self._build_where(filters)
            where = " AND ".join(conditions) if conditions else "TRUE"
            idx = len(params) + 1

            rows = await conn.fetch(
                f"SELECT * FROM {collection} WHERE {where} "
                f"ORDER BY timestamp DESC LIMIT ${idx} OFFSET ${idx + 1}",
                *params,
                limit,
                offset,
            )
            return [self._row_to_document(row) for row in rows] if rows else []
        except Exception as exc:
            self.logger.warning(
                "PostgresResultStorage list failed for collection=%s: %s",
                collection,
                exc,
            )
            return []

    async def get(
        self,
        collection: str,
        record_id: str,
    ) -> Optional[dict[str, Any]]:
        """Retrieve a single execution document by its record id.

        Args:
            collection: Table name (validated against safe-name regex).
            record_id: UUID of the record, as a string.

        Returns:
            The execution document, or ``None`` if not found or on error.
        """
        try:
            conn = await self._ensure()
            await self._ensure_table(conn, collection)

            row = await conn.fetchrow(
                f"SELECT * FROM {collection} WHERE id = $1",
                record_id,
            )
            return self._row_to_document(row) if row else None
        except Exception as exc:
            self.logger.warning(
                "PostgresResultStorage get failed for collection=%s, id=%s: %s",
                collection,
                record_id,
                exc,
            )
            return None

    async def delete(
        self,
        collection: str,
        record_id: str,
    ) -> bool:
        """Delete a single execution document by its record id.

        Args:
            collection: Table name (validated against safe-name regex).
            record_id: UUID of the record, as a string.

        Returns:
            ``True`` if a row was deleted, ``False`` otherwise (including on
            error, so callers see a uniform "nothing happened" signal).
        """
        try:
            conn = await self._ensure()
            await self._ensure_table(conn, collection)

            result = await conn.execute(
                f"DELETE FROM {collection} WHERE id = $1",
                record_id,
            )
            # asyncpg-style command status strings look like "DELETE 1".
            if isinstance(result, str) and result.split():
                return int(result.split()[-1]) > 0
            return False
        except Exception as exc:
            self.logger.warning(
                "PostgresResultStorage delete failed for collection=%s, id=%s: %s",
                collection,
                record_id,
                exc,
            )
            return False

    async def count(
        self,
        collection: str,
        filters: Optional[dict[str, Any]] = None,
    ) -> int:
        """Count execution documents matching the given filters.

        Args:
            collection: Table name (validated against safe-name regex).
            filters: Optional filters — see :meth:`_build_where`.

        Returns:
            The number of matching rows, or ``0`` on error.
        """
        try:
            conn = await self._ensure()
            await self._ensure_table(conn, collection)

            conditions, params = self._build_where(filters)
            where = " AND ".join(conditions) if conditions else "TRUE"

            result = await conn.fetchval(
                f"SELECT COUNT(*) FROM {collection} WHERE {where}",
                *params,
            )
            return int(result) if result is not None else 0
        except Exception as exc:
            self.logger.warning(
                "PostgresResultStorage count failed for collection=%s: %s",
                collection,
                exc,
            )
            return 0
