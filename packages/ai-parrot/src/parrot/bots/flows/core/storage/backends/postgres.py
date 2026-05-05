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
_NAMED_COLUMNS = frozenset(("crew_name", "method", "user_id", "session_id", "timestamp"))


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
            f"  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),"
            f"  crew_name   text        NOT NULL,"
            f"  method      text        NOT NULL,"
            f"  user_id     text,"
            f"  session_id  text,"
            f"  timestamp   timestamptz NOT NULL DEFAULT now(),"
            f"  payload     jsonb       NOT NULL"
            f")"
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_crew_name_idx ON {table} (crew_name)"
        )
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_session_id_idx ON {table} (session_id)"
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
                "(crew_name, method, user_id, session_id, timestamp, payload) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                crew_name,
                method,
                user_id,
                session_id,
                timestamp,
                payload,
            )
        except Exception as exc:
            self.logger.warning(
                "PostgresResultStorage save failed for collection=%s: %s",
                collection,
                exc,
            )

    async def close(self) -> None:
        """Release the Postgres connection. Safe to call multiple times."""
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None
                self._initialised.clear()
