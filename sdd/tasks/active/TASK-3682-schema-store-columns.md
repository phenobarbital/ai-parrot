# TASK-3682: `SchemaStore(SQLiteWikiStore)` with the `columns` side table and slice replace

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3680
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (part 3). Mirrors `LedgerStore` (own SQLite file, `SQLiteWikiStore` subclass) and the `symbols` side table (store.py:131) for columns. `replace_schema_slice` wraps `replace_source_slice("schema:<origin>")` plus the column rows in one write.

---

## Scope

- Create `schema/store.py` — `SchemaStore` with `COLUMNS_DDL`, `upsert_columns`, `columns_for`, `find_columns`, `replace_schema_slice`.
- Write `test_store.py`.

**NOT in scope**: Rendering (TASK-3681), service/producers (TASK-3683+). No FTS over columns beyond `find_columns` LIKE matching.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py` | CREATE | SchemaStore |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_store.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
import aiosqlite
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord        # verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:855, :409
from parrot.knowledge.wiki.store import SQLitePragmaPolicy   # verified: store.py:243 — import under TYPE_CHECKING like ledger/store.py:18-19
from parrot.knowledge.wiki.schema.models import ColumnRecord                    # TASK-3680
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class SQLiteWikiStore(BaseWikiStore):                                                     # :855
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False,
                 sqlite_policy: SQLitePragmaPolicy | None = None, persistent_writer: bool = False) -> None   # :903
    async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]        # :1143 (asynccontextmanager; rows are dict-like)
    def _assert_writable(self) -> None                                                   # :964
    async def replace_source_slice(self, source_id, pages, edges=None) -> dict[str, Any]  # :1614 (deletes pages with source_id, re-inserts, preserves incoming edges)
    async def add_edges(self, edges: list[tuple]) -> int                                  # :1593 (3- or 4-tuples)
    # edges DDL :112-120; symbols DDL :131 (side-table precedent)
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:24-123
class LedgerStore(SQLiteWikiStore): __init__ forwards db_path/wiki_name/read_only/sqlite_policy/persistent_writer;
    ledger_transaction(): `async with self._write(op) as conn: await conn.execute("CREATE TABLE IF NOT EXISTS …")`  ← same lazy-DDL pattern
```

### Does NOT Exist
- ~~`SQLiteWikiStore.upsert_columns` / a `columns` table~~ — only `symbols` exists; this task adds it
- ~~a hook to extend the base schema DDL~~ — create the table lazily inside `_write()` like `LedgerStore.ledger_transaction`
- ~~edge payload column~~ — none; do not add one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_store.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.replace_source_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`ledger/store.py:24-123` (`LedgerStore`) for the subclass + lazy `CREATE TABLE IF NOT EXISTS` inside `_write()`; `store.py:1747 upsert_symbols` for delete-then-insert.

### Key Constraints
- All writes inside one `self._write(operation)`; call `self._assert_writable()` first.
- `replace_schema_slice` passes 3-tuples `(src, dst, rel)` to `replace_source_slice` (provenance defaults to `extracted`).
- Column rows of table ids removed by the slice replace are deleted in the same transaction.

### References in Codebase
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:24-123
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1614-1700, :1747

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Create `SchemaStore` from the block — why: same lifecycle as `LedgerStore`, own `schema.db`, no `wiki.lock` contention.
2. Ensure `columns` DDL runs lazily on first write — why: `SQLiteWikiStore` has no schema-extension hook.
3. Implement `replace_schema_slice` as slice replace + columns replace in ONE `_write` — why: partial writes must not leave orphan column rows.
4. Write tests with a temp `schema.db`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py` (CREATE)
```python
"""SchemaStore — SQLiteWikiStore specialisation for schema.db with a `columns` side table (FEAT-600 M1)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import aiosqlite

from parrot.knowledge.wiki.schema.models import ColumnRecord
from parrot.knowledge.wiki.store import SQLitePragmaPolicy  # verified: store.py:243
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord  # verified: store.py:855, :409

COLUMNS_DDL = """
CREATE TABLE IF NOT EXISTS columns (
    table_id TEXT NOT NULL, ordinal INTEGER NOT NULL, name TEXT NOT NULL, data_type TEXT NOT NULL,
    nullable INTEGER NOT NULL DEFAULT 1, dflt TEXT, comment TEXT, is_primary_key INTEGER NOT NULL DEFAULT 0,
    fk_target TEXT, PRIMARY KEY (table_id, name));
CREATE INDEX IF NOT EXISTS idx_columns_name ON columns(name);
CREATE INDEX IF NOT EXISTS idx_columns_fk ON columns(fk_target);
"""


class SchemaStore(SQLiteWikiStore):
    """SQLiteWikiStore specialisation for schema.db: adds the `columns` side table."""

    def __init__(self, db_path: str | Path, wiki_name: str = "schema", *, read_only: bool = False,
                 sqlite_policy: Optional[SQLitePragmaPolicy] = None, persistent_writer: bool = False) -> None:
        super().__init__(db_path=db_path, wiki_name=wiki_name, read_only=read_only, sqlite_policy=sqlite_policy,
                         persistent_writer=persistent_writer)

    async def _ensure_columns_table(self, conn: aiosqlite.Connection) -> None:
        """Create the side table lazily (same pattern as LedgerStore.ledger_transaction, ledger/store.py:60+)."""
        await conn.executescript(COLUMNS_DDL)

    async def _replace_columns_conn(self, conn: aiosqlite.Connection, columns: list[ColumnRecord], table_ids: set[str]) -> int:
        """Delete every row of ``table_ids`` then insert ``columns``; returns rows inserted."""
        await self._ensure_columns_table(conn)
        for tid in table_ids:
            await conn.execute("DELETE FROM columns WHERE table_id = ?", (tid,))
        rows = [(c.table_id, c.ordinal, c.name, c.data_type, int(c.nullable), c.default, c.comment, int(c.is_primary_key), c.fk_target) for c in columns]
        await conn.executemany("INSERT INTO columns VALUES (?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    async def upsert_columns(self, columns: list[ColumnRecord]) -> int:
        """Replace all rows of each table_id present in ``columns`` (delete-then-insert inside one _write())."""
        self._assert_writable()
        async with self._write("upsert_columns") as conn:
            return await self._replace_columns_conn(conn, columns, {c.table_id for c in columns})

    async def columns_for(self, table_id: str) -> list[ColumnRecord]:
        """Return the columns of one table ordered by ordinal (empty when unknown)."""
        # FILL IN: SELECT … FROM columns WHERE table_id=? ORDER BY ordinal via the read connection helper the base class uses in get_page (store.py:1937) — bounded by "read path never introspects"
        raise NotImplementedError

    async def find_columns(self, name: Optional[str] = None, fk_target_prefix: Optional[str] = None, limit: int = 50) -> list[ColumnRecord]:
        """LIKE match on column name and/or fk_target prefix (mirrors find_symbols, store.py:768)."""
        # FILL IN: build WHERE from the non-None filters; `name` matches `LIKE ?` with `%name%`; return ≤ limit rows
        raise NotImplementedError

    async def replace_schema_slice(self, origin: str, pages: list[WikiPageRecord], columns: list[ColumnRecord],
                                   edges: list[tuple[str, str, str, str]]) -> dict[str, Any]:
        """replace_source_slice(f"schema:{origin}", pages, edges) + column rows of the affected table ids, atomically."""
        self._assert_writable()
        table_ids = {p.concept_id for p in pages if p.category == "table"}
        report = await self.replace_source_slice(f"schema:{origin}", pages, [(s, d, r) for s, d, r, _p in edges])  # verified: store.py:1614
        async with self._write("replace_schema_columns") as conn:
            # FILL IN: also delete column rows for table ids that were in the OLD slice but not in `pages` — bounded by "dropped tables leave no orphan columns"
            report["columns_written"] = await self._replace_columns_conn(conn, columns, table_ids)
        return report
```
**Why**: Copies `LedgerStore`'s lazy-DDL pattern because `SQLiteWikiStore` exposes no schema hook; `replace_source_slice` already preserves incoming edges (annotations) across a re-ingest.

### FILL IN checklist
- [ ] `columns_for` SELECT via the base read helper — bounded by read-only path
- [ ] `find_columns` WHERE builder — bounded by ≤ limit rows
- [ ] `replace_schema_slice` orphan-column cleanup for dropped tables
- [ ] tests: replace semantics, fk prefix search, dropped-table cleanup, read-only store raises `PermissionError`

---

## Acceptance Criteria

- [ ] `upsert_columns` twice for one table leaves exactly the second set of rows
- [ ] `find_columns(fk_target_prefix='table:o/epson.stores')` returns the FK column
- [ ] `replace_schema_slice` with a table removed deletes its column rows and its page
- [ ] `SchemaStore(path, read_only=True).upsert_columns([...])` raises `PermissionError`
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_store.py
import pytest
from parrot.knowledge.wiki.schema.models import ColumnRecord
from parrot.knowledge.wiki.schema.store import SchemaStore

@pytest.fixture
def store(plane_dir):
    plane_dir.mkdir(parents=True); return SchemaStore(plane_dir / "schema.db")

async def test_upsert_columns_replaces(store):
    tid = "table:o/public.users"
    await store.upsert_columns([ColumnRecord(table_id=tid, ordinal=0, name="id", data_type="int")])
    await store.upsert_columns([ColumnRecord(table_id=tid, ordinal=0, name="uid", data_type="uuid")])
    assert [c.name for c in await store.columns_for(tid)] == ["uid"]

async def test_read_only_refuses(plane_dir):
    plane_dir.mkdir(parents=True); SchemaStore(plane_dir / "schema.db")
    ro = SchemaStore(plane_dir / "schema.db", read_only=True)
    with pytest.raises(PermissionError):
        await ro.upsert_columns([ColumnRecord(table_id="table:o/s.t", ordinal=0, name="x", data_type="int")])
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3680` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
