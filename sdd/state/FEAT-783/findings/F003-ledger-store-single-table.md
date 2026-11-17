---
id: F003
query_id: Q042
type: read
intent: "Read the ledger store to see how a plane persists and queries rows."
executed_at: 2026-10-30T22:39:05Z
duration_ms: 150
parent_id: null
depth: 0
lane: codebase
merged_from: ['FC-003']
---

# F003 — LedgerStore is a thin SQLiteWikiStore subclass: one cursor table, pages+edges for everything else

## Summary

`LedgerStore` (123 lines total) subclasses `SQLiteWikiStore` and adds exactly three
things: a `ledger_transaction(operation)` context manager that creates `ledger_state`
on first use, a `read_cursor()` accessor, and two pass-throughs
(`upsert_pages_in`, `add_edges_in`) that let a caller write pages/edges inside an
already-open transaction. All `BEGIN`/`COMMIT`/busy-timeout handling is delegated
upward to FEAT-557's `SQLiteWikiStore._write()` — the module docstring states the
ledger "never issues BEGIN/COMMIT/ROLLBACK itself". A new plane therefore gets
transaction safety and WAL/busy-timeout policy for free, but gets **no row storage
of its own**: its only persistence options today are (a) `pages` rows with encoded
bodies, or (b) new DDL that no existing code models.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py`
  lines: 24-25
  symbol: `LedgerStore`
  excerpt: |
    class LedgerStore(SQLiteWikiStore):
        """SQLiteWikiStore specialisation for ledger.db: ledger_state table + composable write transactions."""

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py`
  lines: 1-6
  symbol: `module docstring`
  excerpt: |
    """LedgerStore — SQLiteWikiStore specialization for the SDD work ledger.

    Implements the ledger_state table and composable write transactions per
    spec §3 Module 5. Delegates all actual transaction/begin/commit/rollback
    and busy-timeout handling to FEAT-557's SQLiteWikiStore._write().
    """

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py`
  lines: 107-123
  symbol: `LedgerStore.upsert_pages_in` / `LedgerStore.add_edges_in`
  excerpt: |
    async def upsert_pages_in(self, conn: aiosqlite.Connection, pages: list[WikiPageRecord]) -> None:
        """Delegate to _upsert_pages_conn on the caller's transaction."""
        await self._upsert_pages_conn(conn, pages)

    async def add_edges_in(self, conn: aiosqlite.Connection, edges: list[tuple]) -> None:
        """Delegate to _insert_edges_conn on the caller's transaction."""
        await self._insert_edges_conn(conn, edges)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py`
  lines: 75-90
  symbol: `LedgerStore.read_cursor`
  excerpt: |
    async def read_cursor(self) -> tuple[int, str | None]:
        """Read (offset, last_event_id) through `_read()`; a missing ledger_state table reads as (0, None)."""

## Notes

- `read_cursor` swallows every exception and returns `(0, None)` (store.py:103-105), i.e. an
  unreadable cursor silently triggers a full replay rather than failing.
- A usage plane that wants real columns (`model`, `input_tokens`, …) and a unique index on
  `(seat, source_ref)` would be the first component in the ledger to introduce its own DDL,
  and would need a migration story the package currently has no example of.
