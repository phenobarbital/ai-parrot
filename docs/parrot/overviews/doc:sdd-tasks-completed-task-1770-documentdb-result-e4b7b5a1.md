---
type: Wiki Overview
title: 'TASK-1770: DocumentDbResultStorage Read Methods'
id: doc:sdd-tasks-completed-task-1770-documentdb-result-storage-read-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module 4.
relates_to:
- concept: mod:parrot.bots.flows.core.storage.backends.documentdb
  rel: mentions
- concept: mod:parrot.interfaces.documentdb
  rel: mentions
---

# TASK-1770: DocumentDbResultStorage Read Methods

**Feature**: FEAT-306 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1765
**Assigned-to**: unassigned

---

## Context

`DocumentDbResultStorage` wraps the `DocumentDb` MongoDB interface. The underlying
`DocumentDb` class already has rich read methods (`find_documents()`, `read_one()`,
`delete_many()`), making this the most straightforward backend to implement.

Implements spec Module 4.

---

## Scope

- Implement `list()` in `DocumentDbResultStorage`:
  - Use `DocumentDb.find_documents()` with a MongoDB query built from filters
  - Tenant + user_id scoping via query filter
  - Sort by timestamp descending, apply limit (skip via Motor cursor)
- Implement `get()`:
  - Use `DocumentDb.read_one()` with `{"_record_id": record_id}` or equivalent
    unique identifier query (note: MongoDB uses `_id` by default; the save path
    does NOT currently set a custom `_id`, so documents get auto-generated ObjectIds)
  - Strategy: add a `record_id` field during save, or query by composite key
- Implement `delete()`:
  - Use `DocumentDb.delete_many()` with a single-document query
  - Return True if `deleted_count > 0`
- Implement `count()`:
  - Use `DocumentDb.find_documents()` or a Motor `count_documents()` equivalent
- Write unit tests

**NOT in scope**: Modifying the DocumentDb interface itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/documentdb.py` | MODIFY | Add list, get, delete, count methods |
| `tests/unit/test_documentdb_result_storage_read.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends.documentdb import DocumentDbResultStorage  # documentdb.py:17
from parrot.interfaces.documentdb import DocumentDb  # documentdb.py:63
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/documentdb.py:17
class DocumentDbResultStorage(ResultStorage):
    def __init__(self) -> None: ...  # line 25
    async def save(self, collection, document) -> None: ...  # line 28
    # Uses: async with DocumentDb() as db: await db.write(collection, document)
    async def close(self) -> None: ...  # line 45 (no-op)

# packages/ai-parrot/src/parrot/interfaces/documentdb.py:63
class DocumentDb:
    async def find_documents(self, collection_name, query, sort=None, limit=None, projection=None) -> List[dict]: ...  # line 317
    async def read_one(self, collection_name, query) -> Optional[dict]: ...  # line 409
    async def delete_many(self, collection_name, query) -> Any: ...  # line 351
    async def read(self, collection_name, query=None, limit=None, projection=None, sort=None) -> List[dict]: ...  # line 367
    # find_documents pops '_id' from results (line 335)
```

### Does NOT Exist
- ~~`DocumentDbResultStorage.list()`~~ — does not exist yet
- ~~`DocumentDbResultStorage.get()`~~ — does not exist yet
- ~~`DocumentDbResultStorage.count()`~~ — does not exist yet
- ~~`DocumentDb.count_documents()`~~ — no count method on DocumentDb wrapper
- ~~A `record_id` field in saved documents~~ — save() stores raw document dict, no ID added

---

## Implementation Notes

### Pattern to Follow
Follow the per-write context manager pattern from `save()`:

```python
async def list(self, collection, filters=None, limit=20, offset=0):
    try:
        query = {}
        if filters:
            if filters.get("tenant"):
                query["tenant"] = filters["tenant"]
            if filters.get("user_id"):
                query["user_id"] = filters["user_id"]
            if filters.get("crew_name"):
                query["crew_name"] = filters["crew_name"]
            if filters.get("method"):
                query["method"] = filters["method"]
            # date range: {"timestamp": {"$gte": ..., "$lte": ...}}

        async with DocumentDb() as db:
            results = await db.find_documents(
                collection,
                query,
                sort=[("timestamp", -1)],
                limit=limit + offset,  # Motor doesn't support skip via find_documents
            )
        return results[offset:offset + limit]
    except Exception as exc:
        self.logger.warning("DocumentDbResultStorage list failed: %s", exc)
        return []
```

### Key Constraints
- `find_documents()` strips `_id` from results (line 335 of documentdb.py)
- For `get()`: since there's no guaranteed unique ID field, consider adding a
  `record_id` (UUID) to the document during `save()`. Alternatively, query by
  a composite of `crew_name` + `timestamp` + `user_id`.
- Recommended: modify `save()` to add `record_id = str(uuid.uuid4())` to the
  document before writing, enabling clean `get()` and `delete()` by ID.
- For `count()`: use `find_documents()` with the query and count the result
  list length (no native count on DocumentDb wrapper).
- Connection lifecycle is per-operation (fresh `async with DocumentDb()` per call)

---

## Acceptance Criteria

- [ ] `list()` returns filtered results from MongoDB via `find_documents()`
- [ ] `list()` supports tenant, user_id, crew_name, method, date range filters
- [ ] `list()` sorts by timestamp descending
- [ ] `get()` retrieves single document by identifier
- [ ] `delete()` removes document and returns bool
- [ ] `count()` returns total matching documents
- [ ] Tests pass
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_documentdb_result_storage_read.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestDocumentDbResultStorageRead:
    async def test_list_builds_query(self):
        """list() builds correct MongoDB query from filters."""

    async def test_list_sorts_by_timestamp(self):
        """list() requests sort by timestamp descending."""

    async def test_list_pagination(self):
        """list() applies offset and limit."""

    async def test_get_by_record_id(self):
        """get() finds document by record_id."""

    async def test_get_not_found(self):
        """get() returns None when not found."""

    async def test_delete_success(self):
        """delete() calls delete_many and returns True."""

    async def test_delete_not_found(self):
        """delete() returns False when no document deleted."""

    async def test_count(self):
        """count() returns correct total."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1765 must be completed
3. **Verify the Codebase Contract** — confirm DocumentDb methods and DocumentDbResultStorage
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1770-documentdb-result-storage-read.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Followed the task's own "Recommended" approach: `save()` now does
`document.setdefault("record_id", str(uuid.uuid4()))` before writing, giving
`get()`/`delete()` a stable identifier query on (`{"record_id": record_id}`) since
MongoDB's auto-generated `_id` is stripped by `find_documents()` and `read_one()`
never exposed it either. Implemented `list()` via `find_documents()` with a
`_build_query()` helper (tenant/user_id/crew_name/method exact-match + `timestamp`
`$gte`/`$lte` range for date_from/date_to), sorted `[("timestamp", -1)]`, and
`limit=limit+offset` sliced in-memory (Motor cursor has no `skip` exposed by this
wrapper). `get()` uses `read_one()`, `delete()` uses `delete_many()` + checks
`result.deleted_count > 0` (same pattern as `parrot/storage/backends/mongodb.py`).
`count()` uses `find_documents()` (unbounded) and counts the result list, since
`DocumentDb` has no native count method. Created
`tests/unit/test_documentdb_result_storage_read.py` covering all 8 scenarios from
the task's Test Specification plus 4 exception-handling tests. 15/15 new tests
pass; 83/83 across the full storage test slice touched by
TASK-1765/1766/1768/1769/1770. `ruff check` clean.

**Deviations from spec**: One necessary collateral fix — the pre-existing
`tests/bots/flows/core/storage/test_documentdb_backend.py::test_documentdb_save_uses_async_with`
asserted `write()` was called with the exact original document (no extra keys).
Since `save()` now stamps `record_id` onto the document in-place, updated the
assertion to check `write()` was called once with the right collection, that
`crew_name` is preserved, and that `record_id` is present — rather than exact
dict equality. No change to the test's intent.
