"""LedgerStore — SQLiteWikiStore specialization for the SDD work ledger.

Implements the ledger_state table and composable write transactions per
spec §3 Module 5. Delegates all actual transaction/begin/commit/rollback
and busy-timeout handling to FEAT-557's SQLiteWikiStore._write().
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Optional

import aiosqlite

from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from parrot.knowledge.wiki.store import SQLitePragmaPolicy

logger = logging.getLogger(__name__)


class LedgerCursorInvalid(ValueError):
    """Persisted cursor fields are incomplete or invalid."""


class LedgerStore(SQLiteWikiStore):
    """SQLiteWikiStore specialisation for ledger.db: ledger_state table + composable write transactions."""

    def __init__(
        self,
        db_path: str,
        wiki_name: str = "",
        *,
        read_only: bool = False,
        sqlite_policy: Optional[SQLitePragmaPolicy] = None,
        persistent_writer: bool = False,
    ) -> None:
        """Initialize the LedgerStore.

        Args:
            db_path: Path to the ledger database file.
            wiki_name: Optional wiki name.
            read_only: Whether to open in read-only mode.
            sqlite_policy: SQLite connection policy from FEAT-557.
            persistent_writer: Whether to maintain a persistent writer connection.
        """
        super().__init__(
            db_path=db_path,
            wiki_name=wiki_name,
            read_only=read_only,
            sqlite_policy=sqlite_policy,
            persistent_writer=persistent_writer,
        )

    @asynccontextmanager
    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:
        """Yield a connection inside FEAT-557's `_write(operation)`; creates `ledger_state` on first use.

        Propagates WikiStoreBusy unchanged.

        Args:
            operation: Logical name of the write operation.

        Yields:
            A connection inside an open immediate transaction.
        """
        async with self._write(operation) as conn:
            # Create ledger_state table on first use if it doesn't exist
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            yield conn

    async def read_cursor(self) -> tuple[int, str | None]:
        """Return one coherent cursor; propagate real database and I/O failures.

        Returns:
            Tuple of (byte_offset, last_event_id) where byte_offset is the cursor position
            and last_event_id is the ID of the last processed event, or None if no state exists.
        """
        async with self._read() as conn:
            return await self.read_cursor_in(conn)

    async def read_cursor_in(self, conn: aiosqlite.Connection) -> tuple[int, str | None]:
        """Read the supplied transaction without owning its lifecycle.

        Args:
            conn: An open SQLite connection, optionally inside a write transaction.

        Returns:
            The persisted byte offset and last event identifier, or the empty cursor.

        Raises:
            LedgerCursorInvalid: The persisted cursor is partial or has invalid values.
            sqlite3.Error: The schema or storage could not be read.
        """
        async with conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ledger_state'") as cursor:
            if await cursor.fetchone() is None:
                return 0, None

        async with conn.execute(
            "SELECT key, value FROM ledger_state WHERE key IN ('cursor_offset', 'last_event_id')"
        ) as cursor:
            values = {row[0]: row[1] for row in await cursor.fetchall()}

        offset_value = values.get("cursor_offset")
        event_id_value = values.get("last_event_id")
        if offset_value is None and event_id_value is None:
            return 0, None
        if offset_value is None or event_id_value is None:
            raise LedgerCursorInvalid("Persisted ledger cursor is incomplete.")

        try:
            offset = int(offset_value)
        except (TypeError, ValueError) as exc:
            raise LedgerCursorInvalid("Persisted ledger cursor offset is not an integer.") from exc
        if offset < 0:
            raise LedgerCursorInvalid("Persisted ledger cursor offset is negative.")
        if not isinstance(event_id_value, str) or not event_id_value.strip():
            raise LedgerCursorInvalid("Persisted ledger cursor event ID is empty.")
        return offset, event_id_value

    async def upsert_pages_in(self, conn: aiosqlite.Connection, pages: list[WikiPageRecord]) -> None:
        """Delegate to _upsert_pages_conn on the caller's transaction.

        Args:
            conn: Active connection within a transaction.
            pages: Pages to upsert.
        """
        await self._upsert_pages_conn(conn, pages)

    async def add_edges_in(self, conn: aiosqlite.Connection, edges: list[tuple]) -> None:
        """Delegate to _insert_edges_conn on the caller's transaction.

        Args:
            conn: Active connection within a transaction.
            edges: Edges to insert.
        """
        await self._insert_edges_conn(conn, edges)
