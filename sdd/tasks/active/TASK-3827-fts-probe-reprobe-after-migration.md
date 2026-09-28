# TASK-3827: Re-probe the legacy-FTS shape after another process migrates the plane

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3822
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 ("stale legacy-FTS probe"), found while verifying Q4 on 2026-09-28.
`SQLiteWikiStore._uses_legacy_fts` probes whether `pages_fts`/`symbols_fts` still use the
`concept_id`-keyed shape, and **caches the answer per instance** (`store.py:1474-1481`).

A long-lived **read-only** handle, such as the `wikitoolkit mcp` server's handle on a federated
namespace, keeps its cached `True` after another process opens the same plane writable and
`_migrate_fts` converts it. From then on, every query on the old handle uses the
`concept_id` join and fails. What happened:

1. The fieldsync MCP server queried the `parrot` namespace successfully (legacy shape, cached).
2. A CLI `wikitoolkit status` in the parrot checkout opened the plane writable, and it migrated.
3. The next MCP `wiki_symbol_lookup(namespace="parrot")` failed with
   `no such column: symbols_fts.concept_id`.

The fix recovers **inside the handle**: on that error, forget the cached shape, re-probe, and
retry once.

---

## Scope

- In `SQLiteWikiStore.search_symbols_fts` (`store.py:1884`) and in the `pages_fts` lexical
  search (`store.py:2030-2040`, the method that holds the second `_uses_legacy_fts` call):
  - catch `sqlite3.OperationalError` whose message contains `no such column`;
  - drop the table's entry from `self._legacy_fts`;
  - rebuild the join by re-probing;
  - retry the query **once**.

  A second failure propagates unchanged. Keep this in one small private helper, so both call
  sites share it (complexity budget).
- Log the recovery at `DEBUG` with the table name.
- Write a test that reproduces the exact sequence against a real legacy plane.

**NOT in scope**: changing `_migrate_fts`, invalidating caches across processes (not
possible), and the federated fan-out (TASK-3829).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | re-probe-and-retry-once at both FTS query sites |
| `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_reprobe.py` | CREATE | real legacy plane → migrate by a second handle → first handle recovers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import sqlite3                                            # aiosqlite surfaces sqlite3.OperationalError
from parrot.knowledge.wiki.store import SQLiteWikiStore   # store.py:855
```

### Existing Signatures to Use
```python
# store.py:918     self._legacy_fts: dict[str, bool] = {}
# store.py:1446    self._legacy_fts.clear()          (inside _migrate_fts — the only other writer)
# store.py:1454    async def _uses_legacy_fts(self, conn: aiosqlite.Connection, table: str) -> bool:
# store.py:1474-1481 cached = self._legacy_fts.get(table); ... PRAGMA table_info(...); legacy = "concept_id" in columns  (occurrences: 1)
# store.py:1884    async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]:
# store.py:1897-1907
#        async with self._read() as conn:
#            join = ("SELECT s.* FROM symbols_fts JOIN symbols s ON s.concept_id = symbols_fts.concept_id"
#                    if await self._uses_legacy_fts(conn, "symbols_fts")
#                    else "SELECT s.* FROM symbols_fts JOIN symbols s ON s.rowid = symbols_fts.rowid")
#            async with conn.execute(join + " WHERE symbols_fts MATCH ? ORDER BY bm25(symbols_fts) LIMIT ?", ...)
# store.py:2030-2034  same pattern for pages_fts (" FROM pages_fts JOIN pages p ON p.concept_id = pages_fts.concept_id")
```
```python
# packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_external_content.py
#   :236 / :259  legacy DDL: "concept_id UNINDEXED, …" for pages_fts / symbols_fts
#   :268         @pytest.fixture def legacy_db(self, tmp_path) -> Path   (class-scoped; builds a real legacy plane)
#   :300-311     precedent: SQLiteWikiStore(legacy_db).search_symbols_fts("legacydoc") migrates + finds
```

### Does NOT Exist
- ~~A cross-process cache invalidation signal (file watcher, `data_version` check)~~: out of
  scope. The retry is the fix.
- ~~`SQLiteWikiStore.reset_fts_cache()`~~: do not add a public method. Use the private helper.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_reprobe.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._uses_legacy_fts",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.search_symbols_fts"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Match on the message (`"no such column" in str(exc)`), not on the bare exception type:
  `OperationalError` also covers "database is locked", which must keep its existing handling.
- Retry exactly once. A loop would hide a genuinely broken plane.
- The read-only handle must stay read-only. The recovery only re-reads `PRAGMA table_info`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the failing test first. *Why*: it is the mutation proof, and today it raises.
2. Add the helper and use it at both call sites. 3. Run the new test and the existing FTS tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _uses_legacy_fts(self, conn: aiosqlite.Connection, table: str) -> bool:' store.py)
# AFTER — insert below the end of `_uses_legacy_fts` (its last line `        return legacy`, verified: store.py:1481)

    async def _fts_fetch(
        self,
        conn: aiosqlite.Connection,
        table: str,
        build_sql: Callable[[bool], str],
        params: tuple[Any, ...],
    ) -> list[Any]:
        """Run an FTS query built for the probed shape; re-probe once if the shape moved.

        A read-only handle caches the probe for its lifetime, but another process may
        migrate the plane underneath it (``_migrate_fts``), after which the cached
        legacy join fails with ``no such column``. Forget the cached shape, re-probe,
        and retry exactly once (FEAT-609 M5).
        """
        sql = build_sql(await self._uses_legacy_fts(conn, table))
        try:
            async with conn.execute(sql, params) as cur:
                return list(await cur.fetchall())
        except sqlite3.OperationalError as exc:
            if "no such column" not in str(exc):
                raise
            self.logger.debug("FTS shape of %s changed under this handle; re-probing", table)
            self._legacy_fts.pop(table, None)
            sql = build_sql(await self._uses_legacy_fts(conn, table))
            async with conn.execute(sql, params) as cur:
                return list(await cur.fetchall())
```
Then rewrite `search_symbols_fts`'s body (`store.py:1897-1907`) to build `build_sql = lambda legacy: (<legacy join> if legacy else <rowid join>) + " WHERE symbols_fts MATCH ? ORDER BY bm25(symbols_fts) LIMIT ?"`
and return `[_row_to_symbol_record(row) for row in await self._fts_fetch(conn, "symbols_fts", build_sql, (match_expr, limit))]`.
Do the same for the `pages_fts` site (`store.py:2030-2045`).
```python
# FILL IN: pages_fts call site — it appends category/limit clauses and params after the join
# (store.py:2036-2045); fold them into build_sql/params without changing the SQL text for either
# shape — bounded by "existing test_sqlite_fts_external_content.py passes unmodified"
```
Confirm that `sqlite3`, `Callable` and `Any` are imported in `store.py`, and add only what is
missing.

### `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_reprobe.py` (CREATE)
```python
"""FEAT-609 M5: a read-only handle survives another process migrating its FTS shape."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from parrot.knowledge.wiki.store import SQLiteWikiStore

from .test_sqlite_fts_external_content import LEGACY_V2_SCHEMA  # module-level constant


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    """The same pre-hotfix plane as TestLegacyPlaneMigration.legacy_db."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(LEGACY_V2_SCHEMA)
        # FILL IN: the same 4 INSERTs as test_sqlite_fts_external_content.py:273-293
        # (one page + pages_fts row "legacyword", one symbol + symbols_fts row "legacydoc")
        conn.commit()
    finally:
        conn.close()
    return path


async def test_legacy_fts_reprobe_after_migration(legacy_db: Path) -> None:
    reader = SQLiteWikiStore(legacy_db, read_only=True)
    assert await reader.search_symbols_fts("legacydoc")          # probes + caches "legacy"

    writer = SQLiteWikiStore(legacy_db)
    assert await writer.search_symbols_fts("legacydoc")          # migrates the plane

    hits = await reader.search_symbols_fts("legacydoc")          # today: no such column
    assert hits, "read-only handle must recover after the plane was migrated"


async def test_legacy_pages_fts_reprobe_after_migration(legacy_db: Path) -> None:
    # FILL IN: same sequence over search_fts("legacyword")
    ...
```
**Reproduced 2026-09-28** with ai-parrot 1.0.6 (whose `store.py` is byte-identical to
`origin/dev` 8bf475842), on a plane built from `LEGACY_V2_SCHEMA`: `reader 1: 1`, `writer : 1`,
`reader 2 ERROR: OperationalError no such column: symbols_fts.concept_id`.
**Why**: this is the production sequence (reader cached → writer migrated → reader queried),
built on a real legacy plane with no mocks. Mutation proof: remove the `except` branch and see
the first test fail with `no such column: symbols_fts.concept_id`.

### FILL IN checklist
- [ ] The `pages_fts` call-site refactor. Bound: SQL text unchanged for both shapes.
- [ ] The fixture's 4 INSERTs. Bound: identical to the existing fixture's plane.
- [ ] The pages test. Bound: the same sequence as the symbols test.

---

## Acceptance Criteria

- [ ] A read-only handle that probed a legacy plane recovers after a second handle migrates it,
      for both `search_symbols_fts` and `search_fts`.
- [ ] Mutation-checked: without the retry, `test_legacy_fts_reprobe_after_migration` raises
      `no such column`.
- [ ] `test_sqlite_fts_external_content.py` passes unmodified.
- [ ] Non-"no such column" `OperationalError`s propagate unchanged.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_reprobe.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_external_content.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Confirm TASK-3822 is `done` (the same file, `store.py`), and verify the contract.
3. Write the failing test first, then implement, validate, and stage only the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3827 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
