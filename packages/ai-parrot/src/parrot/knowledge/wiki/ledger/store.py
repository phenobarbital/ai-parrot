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
        """Read (offset, last_event_id) through `_read()`; a missing ledger_state table reads as (0, None).

        Returns:
            Tuple of (byte_offset, last_event_id) where byte_offset is the cursor position
            and last_event_id is the ID of the last processed event, or None if no state exists.
        """
        async with self._read() as conn:
            try:
                # Check if ledger_state table exists
                async with conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'ledger_state'"
                ) as cur:
                    row = await cur.fetchone()
                    if not row or row[0] == 0:
                        return (0, None)

                # Read cursor state
                async with conn.execute("SELECT value FROM ledger_state WHERE key = 'cursor_offset'") as cur:
                    offset_row = await cur.fetchone()

                async with conn.execute("SELECT value FROM ledger_state WHERE key = 'last_event_id'") as cur:
                    event_id_row = await cur.fetchone()

                offset = int(offset_row[0]) if offset_row else 0
                event_id = event_id_row[0] if event_id_row else None

                return (offset, event_id)
            except Exception:
                # If anything fails, return default state
                return (0, None)

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
