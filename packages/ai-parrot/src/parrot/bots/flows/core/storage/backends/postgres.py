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
    ("crew_name", "method", "user_id", "session_id", "timestamp", "execution_id")
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
        if table in self._initialised:
            return
        if not _TABLE_RE.match(table):
            raise ValueError(
                f"Refusing to issue DDL for unsafe table name: {table!r}"
            )
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
                "(crew_name, method, user_id, session_id, execution_id, timestamp, payload) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                crew_name,
                method,
                user_id,
                session_id,
                execution_id,
                timestamp,
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
            rows = await conn.execute(
                f"SELECT crew_name, method, user_id, session_id, "
                f"execution_id, timestamp, payload FROM {collection} "
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
