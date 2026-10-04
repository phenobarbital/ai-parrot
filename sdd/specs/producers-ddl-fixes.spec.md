---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wiki, schema-plane, ledger-fix]
---

# Feature Specification: Schema-plane producer & annotation fixes (FEAT-600 review follow-up)

**Feature ID**: FEAT-628
**Date**: 2026-10-05
**Author**: agent:sdd-fix
**Status**: approved
**Target version**: next
**Origin**: `/sdd-fix` ledger group `fixgroup:67a4a2f018c0` — `issue:5ebd43788504`, `issue:7aee524c981c`
(both `discovered_from: review:FEAT-600`). Parent spec: `sdd/specs/sql-schema-plane.spec.md`.

---

## 1. Motivation & Business Requirements

### Problem Statement

The FEAT-600 code review filed two ledger issues against the SQL schema plane. Re-deriving both
from the source on 2026-10-05 (dev @ `82ca4f5c5`):

1. **issue:5ebd43788504 — FK over-count.** The reported symptom (`test_fold_ddl_task_memory_corpus`
   recovering 4 FKs vs a documented 3) was already reconciled by `bc08b74c3`: the 4th entry is the
   composite `(artifact_id, version)` constraint decomposed per column, which is the intended
   convention. **But the hypothesis the issue names is a real, separate defect**:
   `producers/ddl.py` never dedupes `foreign_keys`. One logical FK expressed both inline
   (`pid INT REFERENCES p(id)`) and as a table-level `FOREIGN KEY (pid) REFERENCES p(id)` — or
   re-asserted by a later `ALTER TABLE … ADD CONSTRAINT` — yields duplicate identical entries
   (reproduced: 3 identical entries for one relationship). Duplicates inflate `references` edges
   and relation counts.

2. **issue:7aee524c981c — AC7 / AC4 unverified.** Writing the missing AC7 test reveals AC7 is
   **broken, not merely untested**: `wiki_remember(…, link_page_id="table:…", rel="about")` writes
   its edge to the local `wiki.db` (unqualified `table:` ids are local), while
   `SchemaPlaneService.lookup()` reads `about` annotations only from `schema.db`. Result:
   `wiki_schema_lookup` returns `annotations: []` both before and after a sync, although
   `wiki_related` on the same table does show the note. `create_schema_tools()` receives the
   federated read store and discards it. AC4's full-corpus bar (≥ 20 tables, ≥ 329 columns; corpus
   is now 41 tracked `.sql` files → 34 tables / 419 columns) has no test at all.

### Goals
- G1: `fold_ddl` emits each `(column, ref_schema, ref_table, ref_column)` FK at most once per table.
- G2: `wiki_schema_lookup` surfaces `about` annotations written by `wiki_remember` to the local
  plane, and they survive `schema sync` (AC7 of FEAT-600).
- G3: Automated coverage for AC7 (survive-sync, dropped-table = dangling edge not deleted note,
  store-level preserved-edge path) and AC4 (full in-repo `.sql` corpus bar).

### Non-Goals (explicitly out of scope)
- The CLI `wikitoolkit schema lookup` path (it builds the service without a federated store) —
  unchanged; only the MCP tool surface gets local annotations.
- `REFERENCES t` with no column list (implicit PK target) — still skipped, as today.
- Changing the per-column composite-FK convention.

---

## 2. Architectural Design

### Overview
- `producers/ddl.py`: route both `_add_inline_fk` and `_add_fk` through one `_append_fk` helper that
  skips an entry already present in `meta.foreign_keys`.
- `service.py`: `SchemaPlaneService.lookup(ref, *, annotation_store=None)` — when a store is given,
  merge its `rel == "about"` neighbors of the table into `annotations`, deduped by the
  namespace-stripped `concept_id` (so the schema plane's own rows, seen through the federation as
  `schema::…`, are not doubled).
- `tools.py`: `WikiSchemaLookupTool` takes an optional `annotation_store`; `create_schema_tools`
  passes the `store` it already receives.

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `mcp_server.create_wiki_mcp_server` | unchanged | already passes `read_store` to `create_schema_tools` |
| `FederatedWikiStore.neighbors` | read | returns local + overlay rows with `namespace` key |
| `parrot.knowledge.wiki.context.split_namespaced_id` | uses | strip `ns::` for dedupe |

### New Public Interfaces
```python
async def lookup(self, ref: str, *, annotation_store: Optional[BaseWikiStore] = None) -> LookupResult | list[str]
class WikiSchemaLookupTool(_SchemaTool):
    def __init__(self, service: SchemaPlaneService, annotation_store: Optional[BaseWikiStore] = None) -> None
```

---

## 3. Module Breakdown

### Module 1: FK dedupe (`producers/ddl.py`)
### Module 2: Federated annotations in lookup (`service.py`, `tools.py`)
### Module 3: Tests (`tests/knowledge/wiki/schema/`)
All three are one task (TASK-4058) — small, tightly coupled, single package.

---

## 4. Test Specification

| Test | File | Covers |
|---|---|---|
| `test_fold_ddl_dedupes_repeated_foreign_keys` | `test_ddl_producer.py` | G1 |
| `test_fold_ddl_repo_corpus_baseline` | `test_ddl_producer.py` | G3 / AC4 |
| `test_sync_preserves_memory_annotations` | `test_service.py` | G2 / AC7 via MCP server |
| `test_dropped_table_leaves_memory_note` | `test_service.py` | AC7 dropped-table case |
| `test_replace_slice_preserves_external_about_edge` | `test_store.py` | `_replace_source_slice_conn` preserved-edge path |

---

## 5. Acceptance Criteria
- [ ] AC1 — the inline + table-level + ALTER triple for one FK folds to exactly 1 entry; the
  composite-FK corpus test still yields 4.
- [ ] AC2 — after `wiki_remember(link_page_id="table:…", rel="about")`, `wiki_schema_lookup`
  lists the memory in `annotations`, before and after a re-sync that changes the table.
- [ ] AC3 — re-syncing without the table: the memory page still exists; lookup of the table errors.
- [ ] AC4 — folding every git-tracked `*.sql` recovers ≥ 20 tables and ≥ 329 columns.
- [ ] AC5 — `pytest packages/ai-parrot/tests/knowledge/wiki/schema/` green; `ruff check` clean.

---

## 6. Codebase Contract
Verified on dev @ `82ca4f5c5`:
- `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py` — `_add_inline_fk(meta, column, reference, default_schema)`, `_add_fk(meta, fk, default_schema)`
- `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py:256` — `async def lookup(self, ref: str)`
- `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py:124` — `create_schema_tools(store, root, config, service=None)`
- `packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py:135` — `SchemaStore._replace_source_slice_conn`
- `parrot.knowledge.wiki.context.split_namespaced_id(page_id) -> tuple[str | None, str]`

## 7. Open Questions
None.
