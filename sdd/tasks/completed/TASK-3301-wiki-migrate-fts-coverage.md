# TASK-3301: Add v2→v3 `_migrate_fts` coverage to the wiki migration test

**Feature**: FEAT-562 — CI Test-Failure Root-Cause Remediation
**Spec**: `sdd/specs/ci-test-failures-root-cause-remediation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Completes Module 5. The stale `SCHEMA_VERSION == "2"` assertion is already
fixed on `dev` (now `assert row[0] == SCHEMA_VERSION`), which unblocked CI — but
the M5 acceptance criterion "the file gains at least one assertion that
specifically exercises `_migrate_fts`" was NOT met: the file's four tests all
cover the v1→v2 shape (columns, `symbols`/`symbols_fts` tables, no-rewrite,
noop-reopen) and only assert the FINAL schema version, never the distinctive
effect of the 2→3 step. Commit `a26ff2824e` added `SQLiteWikiStore._migrate_fts`
which rebuilds the FTS5 tables as **external-content** (`content='pages'` /
`content='symbols'`) — that is the 2→3 behaviour this task must assert, so the
migration chain 1→2→3 is genuinely exercised, not just relabeled.

---

## Scope

- Add one test to `tests/knowledge/wiki/test_store_migration_v2.py` that opens
  the committed `wiki_v1.db` fixture (which migrates all the way to the current
  schema, v3) and asserts the FTS5 external-content form introduced by
  `_migrate_fts`: the `pages_fts` (and `symbols_fts`) virtual tables are
  external-content (`content='pages'` / `content='symbols'`) and the FTS
  triggers exist.
- Reuse the existing `v1_db` fixture and `_tables` helper (in-place upgrade
  path — no new binary `wiki_v2.db` fixture needed).

**NOT in scope**: changing the already-fixed `SCHEMA_VERSION` assertion; any
change to `store.py`; the other stale-test modules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/test_store_migration_v2.py` | MODIFY | Add a test asserting `_migrate_fts`'s v3 external-content FTS schema |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import SCHEMA_VERSION, SQLiteWikiStore  # verified: test_store_migration_v2.py:16 (already imported)
import sqlite3  # already imported in the file
import pytest   # already imported (@pytest.mark.asyncio in use)
```

### Existing Signatures to Use
```python
# tests/knowledge/wiki/test_store_migration_v2.py — reuse verbatim:
@pytest.fixture
def v1_db(tmp_path: Path) -> Path: ...          # copy of the committed v1 fixture (line 21)
def _tables(db_path: Path) -> set[str]: ...     # sqlite_master type='table' names (line 37)
# Migration is triggered by any read on the store, e.g.:
#   store = SQLiteWikiStore(v1_db, wiki_name="v1-fixture"); await store.list_pages(limit=100)
#   (pattern verified: test_open_v1_db_migrates_to_v2, lines 60-63)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "3"                              # line 50
async def _migrate_fts(self, conn) -> None: ...  # added by a26ff2824e; rebuilds FTS5 as external-content
# The v3 FTS tables are external-content, e.g. symbols_fts is created with
#   `content = 'symbols', content_rowid = 'rowid'` (verified: store.py ~line 193).
#   pages_fts is the analogous `content='pages'` external-content table.
```

### Does NOT Exist
- ~~a `wiki_v2.db` fixture~~ — not committed; use the in-place upgrade of
  `wiki_v1.db` (the fixture migrates through 2→3 on open).
- ~~a public `store.migrate()` / `store.schema_version` API to call directly~~
  — migration runs implicitly on first read; assert on the resulting SQLite
  schema via `sqlite3`, as the existing tests do.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "tests/knowledge/wiki/test_store_migration_v2.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- In-place upgrade only: open the v1 fixture through `SQLiteWikiStore`, let the
  implicit migration run to v3, then introspect the resulting DB.
- Assert the DISTINCTIVE v3 effect (external-content FTS), not just
  `schema_version == "3"` (that is already covered). Query
  `sqlite_master.sql` for `pages_fts` and assert the external-content marker
  (`content` referencing `pages`) is present.
- Keep it a `@pytest.mark.asyncio` test consistent with the file's style.

---

## Implementation Blueprint

### Steps (in order)
1. Add a `_fts_create_sql(db_path, table)` helper (or inline query) reading
   `sqlite_master.sql` for the FTS table — *why*: the external-content marker
   lives in the CREATE statement, which is the observable v3 signature.
2. Add `test_open_v1_db_reaches_v3_external_content_fts` opening the v1 fixture
   and asserting the external-content FTS + triggers — *why*: exercises the
   `_migrate_fts` (2→3) step the AC requires.

### `tests/knowledge/wiki/test_store_migration_v2.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_second_open_is_a_noop' tests/knowledge/wiki/test_store_migration_v2.py)
# AFTER — append below `test_second_open_is_a_noop` (the last test, ~line 96)

def _fts_create_sql(db_path: Path, table: str) -> str:
    """Return the CREATE statement for an FTS virtual table (or '')."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        ).fetchone()
        return row[0] if row and row[0] else ""
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_open_v1_db_reaches_v3_external_content_fts(v1_db: Path):
    """Opening a v1 plane migrates through _migrate_fts (2->3), which rebuilds
    the FTS5 tables as external-content — the distinctive v3 signature."""
    store = SQLiteWikiStore(v1_db, wiki_name="v1-fixture")
    await store.list_pages(limit=100)  # triggers migration to the current schema

    assert SCHEMA_VERSION == "3"  # guards this test's premise about the 2->3 step
    pages_fts_sql = _fts_create_sql(v1_db, "pages_fts")
    # FILL IN: assert the external-content marker in pages_fts_sql (e.g. that it
    #   references `content` = 'pages') AND that the FTS sync triggers exist in
    #   _tables()/sqlite_master — read store.py's WIKI_FTS_SQL for the exact
    #   trigger names and content-table spelling before asserting.
    #   bounded by M5 AC "at least one assertion that specifically exercises
    #   _migrate_fts (the 2->3 step)". Do NOT merely re-assert schema_version.
    raise NotImplementedError
```
**Why this shape**: reuses the file's `v1_db` fixture and read-triggers-migration
pattern; the external-content CREATE statement is the observable proof that
`_migrate_fts` ran, distinguishing this from the existing v1→v2 assertions.

### FILL IN checklist
- [ ] Assert `pages_fts` (and/or `symbols_fts`) is external-content per store.py's actual `WIKI_FTS_SQL` spelling; assert the FTS triggers exist — bounded by M5 AC.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/test_store_migration_v2.py -q` passes.
- [ ] The file contains at least one assertion that specifically exercises the
      `_migrate_fts` (v2→v3) step — the external-content FTS schema — not just
      the final `schema_version`.
- [ ] No change to the existing (already-fixed) `SCHEMA_VERSION` assertion and
      no change to `store.py`.
- [ ] `ruff check tests/knowledge/wiki/test_store_migration_v2.py` clean.

---

## Test Specification

The added test is the deliverable. It must fail if `_migrate_fts` were reverted
(i.e. if the FTS tables were left in their non-external-content v2 form), which
is what makes it genuine 2→3 coverage rather than a relabeled literal.

---

## Agent Instructions

Standard SDD flow. No dependencies — can start immediately. Read `store.py`'s
`WIKI_FTS_SQL` / `_migrate_fts` for the exact external-content spelling and
trigger names before writing the assertion.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.8), retarget pass
**Date**: 2026-09-17
**Notes**: Re-applied on top of current dev (branch rebuilt from dev to guarantee zero
conflict with dev PR #1408). `test_open_v1_db_reaches_v3_external_content_fts` +
`_triggers`/`_fts_create_sql` helpers added to `test_store_migration_v2.py`; verified
5/5 pass locally (`wiki.store` imports fine). Non-conflicting with dev (dev has no
`_migrate_fts` coverage). This is the only original FEAT-562 task that survived the
retarget as-is.
