---
type: Wiki Overview
title: 'TASK-1087: PgVectorStore metadata_filters Extension'
id: doc:sdd-tasks-completed-task-1087-pgvector-metadata-filters-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.stores.postgres import PgVectorStore # verified: postgres.py:58'
relates_to:
- concept: mod:parrot.stores.postgres
  rel: mentions
---

# TASK-1087: PgVectorStore metadata_filters Extension

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Module 4 of the spec. Extends `PgVectorStore` with two improvements:
> 1. Add `list` value support to `similarity_search()`'s existing `metadata_filters` (currently only scalar equality).
> 2. Add `metadata_filters` parameter to `add_documents()` to scope upsert delete-and-insert operations.
>
> Both are generic, reusable extensions. The concept embedding pipeline and hybrid resolver
> depend on these for tenant-scoped operations.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/stores/postgres.py`:
  - **`similarity_search()`** (line 741): Extend existing `metadata_filters` handling (lines 867-877) to support list values with `IN (...)` semantics using parameter-bound SQL.
  - **`add_documents()`** (line 588): Add `metadata_filters: dict[str, Any] | None = None` parameter. When provided, delete existing rows matching the filter before inserting new ones (upsert pattern).
- All filter values must be parameter-bound (no f-string interpolation) to prevent SQL injection.
- Write comprehensive unit tests including an injection safety test.

**NOT in scope**: Creating the concepts namespace/table, the concept embedding pipeline (TASK-1085), the hybrid resolver (TASK-1088).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/postgres.py` | MODIFY | Extend metadata_filters on similarity_search + add to add_documents |
| `packages/ai-parrot/tests/stores/test_pgvector_metadata_filters.py` | CREATE | Unit tests for metadata_filters |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.stores.postgres import PgVectorStore  # verified: postgres.py:58
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/stores/postgres.py:58
class PgVectorStore(AbstractStore):
    def __init__(self, table=None, schema='public', ...):  # line 63

    async def add_documents(
        self,
        documents: List[Document],
        table: str = None,
        schema: str = None,
        embedding_column: str = 'embedding',
        content_column: str = 'document',
        metadata_column: str = 'cmetadata',
        **kwargs
    ) -> None:  # line 588
        # Does NOT currently accept metadata_filters.

    async def similarity_search(
        self,
        query: str,
        table: str = None,
        schema: str = None,
        k: Optional[int] = None,
        limit: int = None,
        metadata_filters: Optional[Dict[str, Any]] = None,  # line 748 — ALREADY EXISTS
        score_threshold: Optional[float] = None,
        metric: str = None,
        embedding_column: str = 'embedding',
        content_column: str = 'document',
        metadata_column: str = 'cmetadata',
        id_column: str = 'id',
        additional_columns: Optional[List[str]] = None,
        include_parents: bool = False,
    ) -> List[SearchResult]:  # line 741

# Existing metadata_filters handling in similarity_search (lines 867-877):
# Currently only supports scalar equality:
#   if isinstance(val, bool):
#       metadata_col[key].astext.cast(Boolean) == val
#   else:
#       metadata_col[key].astext == str(val)
# DOES NOT support list values → this task adds list/IN support.
```

### Does NOT Exist
- ~~`similarity_search()` supporting list values in metadata_filters~~ — only scalar equality today (lines 867-877)
- ~~`add_documents()` accepting metadata_filters~~ — does NOT exist; this task adds it
- ~~A generic delete-by-metadata method on PgVectorStore~~ — does NOT exist; the upsert delete is implemented inline in `add_documents()`

---

## Implementation Notes

### Pattern to Follow
```python
# In similarity_search, extend the metadata_filters loop (line 867):
if metadata_filters:
    for key, val in metadata_filters.items():
        if isinstance(val, list):
            # IN semantics — parameter-bound
            stmt = stmt.where(
                metadata_col[key].astext.in_([str(v) for v in val])
            )
        elif isinstance(val, bool):
            stmt = stmt.where(
                metadata_col[key].astext.cast(sqlalchemy.Boolean) == val
            )
        else:
            stmt = stmt.where(
                metadata_col[key].astext == str(val)
            )

# In add_documents, before inserting, delete matching rows:
if metadata_filters:
    delete_conditions = []
    for key, val in metadata_filters.items():
        if isinstance(val, list):
            delete_conditions.append(metadata_col[key].astext.in_([str(v) for v in val]))
        else:
            delete_conditions.append(metadata_col[key].astext == str(val))
    delete_stmt = delete(self.embedding_store).where(and_(*delete_conditions))
    await session.execute(delete_stmt)
```

### Key Constraints
- **SQL injection safety**: ALL filter values MUST be parameter-bound via SQLAlchemy's parameter substitution. NEVER use f-strings or string interpolation in WHERE clauses.
- **Backwards compatible**: `metadata_filters=None` or omitted → existing behavior unchanged.
- **List semantics**: `{"doc_type": ["policy", "manual"]}` → `metadata->>'doc_type' IN ('policy', 'manual')`.
- **Scalar semantics**: `{"tenant_id": "acme"}` → `metadata->>'tenant_id' = 'acme'` (existing behavior, preserved).
- The injection safety test must verify that `{"tenant_id": "a' OR 1=1 --"}` returns 0 rows, not all rows.

### References in Codebase
- `packages/ai-parrot/src/parrot/stores/postgres.py` — the file to modify (lines 741-928 for search, 588-615 for add_documents)

---

## Acceptance Criteria

- [ ] `similarity_search()` metadata_filters supports list values with `IN (...)` semantics
- [ ] `add_documents()` accepts `metadata_filters: dict[str, Any] | None = None`
- [ ] `add_documents()` with metadata_filters deletes matching rows before insert (upsert)
- [ ] All filter values are parameter-bound (no f-string interpolation)
- [ ] Injection test passes: `metadata_filters={"tenant_id": "a' OR 1=1 --"}` returns empty, not all rows
- [ ] `metadata_filters=None` or omitted → identical to today's behavior
- [ ] All tests pass: `pytest packages/ai-parrot/tests/stores/test_pgvector_metadata_filters.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/stores/postgres.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/stores/test_pgvector_metadata_filters.py
import pytest
from parrot.stores.postgres import PgVectorStore


class TestPgVectorMetadataFilters:
    async def test_metadata_filters_scalar_eq(self):
        """metadata_filters={'tenant_id': 'acme'} filters correctly."""

    async def test_metadata_filters_list_in(self):
        """metadata_filters={'doc_type': ['policy', 'manual']} uses IN semantics."""

    async def test_metadata_filters_injection_safe(self):
        """metadata_filters={'tenant_id': \"a' OR 1=1 --\"} returns 0 rows."""

    async def test_metadata_filters_absent(self):
        """metadata_filters=None → query identical to today's."""

    async def test_metadata_filters_bool(self):
        """metadata_filters={'is_current': True} handles boolean properly."""

    async def test_add_documents_upsert_with_filters(self):
        """add_documents(metadata_filters={'tenant_id': 'acme'}) deletes then inserts."""

    async def test_add_documents_no_filters_backwards_compat(self):
        """add_documents without metadata_filters works as before."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `packages/ai-parrot/src/parrot/stores/postgres.py` lines 741-928 to confirm metadata_filters handling
   - Read lines 588-615 to confirm add_documents signature
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1087-pgvector-metadata-filters-extension.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
