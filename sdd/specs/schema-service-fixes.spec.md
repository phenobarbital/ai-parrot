---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wiki, schema-plane, ledger-fix]
---

# Feature Specification: Schema Service Fixes

**Feature ID**: FEAT-632
**Date**: 2026-10-05
**Author**: agent:sdd-fix (ledger group `fixgroup:17a694eadacd`)
**Status**: approved
**Target version**: next
**Parent spec**: `sdd/specs/sql-schema-plane.spec.md` (FEAT-600)

---

## 1. Motivation & Business Requirements

### Problem Statement

`/sdd-fix` planned ledger group `fixgroup:17a694eadacd` with three `major` bugs
against `parrot/knowledge/wiki/schema/service.py`:

| Issue | Title | State on `origin/dev` (`dc2cf151c`) |
|---|---|---|
| `issue:c8423fbace97` | `SchemaPlaneService.ingest_ddl` is not atomic — TOCTOU window can let DDL overwrite a live page | **Open** — this spec fixes it |
| `issue:f3bcdfdc1373` | schema diff falsely reports type divergence (case-sensitive type comparison) | Already fixed by `f0c1cc7c8` (`_type_differs`, case-insensitive) |
| `issue:97acacf5af78` | `test_sync_then_unchanged_and_lookup` flaky on live-computed `age_days` | Already fixed by `bc08b74c3` (`model_dump(exclude={"age_days"})` + `approx`) |

`ingest_ddl` reads each table page with `get_page()` and then — in **separate**
transactions — writes `upsert_pages` / `upsert_columns` / `add_edges`. A
`schema sync <origin>` that commits between the read and the writes can have its
freshly written live page overwritten by DDL-derived facts, violating FEAT-600
AC5: *"a live page is never overwritten by DDL facts"*.

### Goals
- The live-page check and the resulting DDL write for one record happen in a
  single `BEGIN IMMEDIATE` transaction.
- `ingest_ddl`'s observable `SyncReport` (created / updated / unchanged) is
  unchanged for sequential use.

### Non-Goals (explicitly out of scope)
- Making a whole multi-record `ingest_ddl` call one transaction (per-record
  atomicity is what the merge rule needs; one long write lock would block
  concurrent readers' writers for the whole fold).
- Re-fixing the two already-resolved issues.

---

## 2. Architectural Design

### Overview

Add `SchemaStore.fold_ddl_table(...)`, a conditional write modelled on
`SQLiteWikiStore.compare_and_swap_page`: inside one `self._write(...)` it reads
the existing page's body and `content_hash`, decides, and writes pages, columns
and edges on the same connection. `SchemaPlaneService.ingest_ddl` calls it once
per folded record and maps the returned outcome onto its `SyncReport`.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SchemaStore` (`schema/store.py`) | new method | uses `_write`, `_upsert_pages_conn`, `_insert_edges_conn`, `_replace_columns_conn` |
| `SchemaPlaneService.ingest_ddl` (`schema/service.py`) | modified | replaces read-then-write sequence |

### New Public Interfaces

```python
class SchemaStore(SQLiteWikiStore):
    async def fold_ddl_table(
        self,
        page: WikiPageRecord,
        columns: list[ColumnRecord],
        edges: list[tuple[str, str, str, str]],
        *,
        changed_only: bool = False,
    ) -> Literal["created", "updated", "unchanged"]: ...
```

---

## 3. Module Breakdown

### Module 1: atomic DDL fold (TASK-4067)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py`
- **Responsibility**: single-transaction read-check-write per DDL record.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_fold_ddl_table_never_overwrites_live_page` | store | a live page is left intact; only `defined_in` edges are added; returns `unchanged` |
| `test_fold_ddl_table_created_updated_unchanged` | store | outcomes for absent / changed / `changed_only` + same hash |
| `test_ingest_ddl_does_not_read_outside_transaction` | service | `ingest_ddl` never calls `get_page` / `upsert_pages` separately |

Existing tests in `packages/ai-parrot/tests/knowledge/wiki/schema/` keep passing.

---

## 5. Acceptance Criteria

- [ ] AC1: `ingest_ddl` performs the live-page check and the write for a record inside one `_write()` transaction.
- [ ] AC2: a page whose frontmatter `source` is not `ddl` is never overwritten by `fold_ddl_table`; only its `defined_in` edges are added.
- [ ] AC3: `SyncReport` created/updated/unchanged semantics unchanged (existing schema tests pass).
- [ ] AC4: new unit tests from §4 pass; `ruff check` clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.wiki.schema.store import SchemaStore        # schema/store.py
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.schema.models import ColumnRecord
```

### Existing Class Signatures
```python
# parrot/knowledge/wiki/store.py
async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]   # BEGIN IMMEDIATE ... COMMIT
async def _upsert_pages_conn(self, conn, pages: list[WikiPageRecord]) -> None
async def _insert_edges_conn(self, conn, edges: list[tuple]) -> None
async def compare_and_swap_page(self, page, expected_content_hash) -> bool       # pattern to mirror
# parrot/knowledge/wiki/schema/store.py
async def _replace_columns_conn(self, conn, columns, table_ids: set[str]) -> int
# parrot/knowledge/wiki/schema/service.py
def _page_source(page: dict[str, Any]) -> str      # reads frontmatter "source" from page["body"]
```

### Does NOT Exist (Anti-Hallucination)
- ~~`SchemaStore.fold_ddl_table`~~ — created by this spec.
- ~~a store-level "get page inside an open transaction" helper~~ — query `pages` directly on `conn`.

---

## 7. Implementation Notes & Constraints

- `_page_source` lives in `service.py`, and the store must not import the
  service (circular import). Move the frontmatter parsing (`_page_content`,
  `_page_source`) into `store.py` and have `service.py` import them from there,
  so both sides share one definition.
- Look the page up by `concept_id` only (table ids are concept ids).

---

## 8. Open Questions

None.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-10-05 | agent:sdd-fix | Initial spec from ledger group `fixgroup:17a694eadacd` |
