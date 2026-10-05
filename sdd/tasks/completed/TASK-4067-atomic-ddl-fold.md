# TASK-4067: Atomic DDL fold in SchemaPlaneService.ingest_ddl

**Feature**: FEAT-632 — Schema Service Fixes
**Spec**: `sdd/specs/schema-service-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Resolves ledger `issue:c8423fbace97`. `ingest_ddl` reads a table page and then
writes pages/columns/edges in separate transactions, so a concurrent
`schema sync` can land in between and have its live page overwritten by DDL
facts (FEAT-600 AC5). Spec §2.

## Scope

- Move `_page_content` / `_page_source` from `schema/service.py` to `schema/store.py`; `service.py` imports them.
- Add `SchemaStore.fold_ddl_table(page, columns, edges, *, changed_only=False)` that, inside one `self._write("fold_ddl_table")`:
  1. selects `body, content_hash` from `pages` by `concept_id`;
  2. if the page exists and its source is not `ddl` → inserts only the `defined_in` edges, returns `"unchanged"`;
  3. if `changed_only` and the stored `content_hash` equals `page.content_hash` → returns `"unchanged"`;
  4. otherwise upserts the page, replaces the table's columns, inserts all edges, returns `"updated"` / `"created"`.
- `ingest_ddl` calls it per record and appends to the matching `SyncReport` list.

**NOT in scope**: whole-call transaction; `sync()`, `diff()`, `lookup()`.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py` | MODIFY |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_ingest_and_diff.py` | MODIFY (add tests) |

## Codebase Contract (Anti-Hallucination)

See spec §6. `SQLiteWikiStore._write`, `_upsert_pages_conn`, `_insert_edges_conn`
(`parrot/knowledge/wiki/store.py`), `SchemaStore._replace_columns_conn`,
`_ensure_columns_table` (`schema/store.py`). `render_page(record)` returns
`(page, columns, edges)` with 4-tuple edges `(src, dst, rel, provenance)`.

## Acceptance Criteria

- [ ] Spec AC1–AC4.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src pytest -q packages/ai-parrot/tests/knowledge/wiki/schema/
ruff check packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py packages/ai-parrot/tests/knowledge/wiki/schema/test_ingest_and_diff.py
```

## Completion Note

**Completed**: 2026-10-05 — commit `9b7ca7d5a` (agent:sdd-fix)

- `SchemaStore.fold_ddl_table()` does the live-page check, the `changed_only`
  hash check and the page/columns/edges write in one `_write("fold_ddl_table")`
  (`BEGIN IMMEDIATE`) transaction, mirroring `compare_and_swap_page`.
- `_page_content` / `_page_source` moved from `service.py` to `store.py`
  (the store cannot import the service); `service.py` imports them.
- `ingest_ddl` calls `fold_ddl_table` once per record; `SyncReport` semantics unchanged.
- Small behaviour change: a DDL rewrite now replaces the table's column rows even
  when the new DDL has zero columns (the old `upsert_columns([])` left stale rows).
- Tests: `test_ingest_ddl_check_and_write_share_one_transaction` (injects a live
  write right before the fold transaction; fails on the old code, passes now) and
  `test_ingest_ddl_created_updated_unchanged`. `tests/knowledge/wiki/schema/`: 55 passed.
- Resolves ledger `issue:c8423fbace97`. The other two issues in the fix group
  (`f3bcdfdc1373`, `97acacf5af78`) were already fixed on dev by `f0c1cc7c8` and
  `bc08b74c3`.
