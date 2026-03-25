# TASK-432: MongoDB Source

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-427, TASK-428
**Assigned-to**: unassigned

---

## Context

MongoDB is a non-SQL source that requires custom query validation (JSON-based)
and metadata discovery (collection listing + field inference via `$sample`).
This is the base source that `DocumentDBSource` and `AtlasSource` will extend.

Implements **Module 6** from the spec.

---

## Scope

- Implement `MongoSource` — driver `"mongo"`, `sqlglot_dialect = None`.
- Override `validate_query()`:
  - Parse query string as JSON.
  - Verify it is a valid dict (filter document) or list of dicts (aggregation pipeline).
  - Return `ValidationResult(valid=False)` for non-JSON or malformed input.
- Implement `get_metadata(credentials, tables)`:
  - Use `list_collection_names()` to discover collections.
  - Use `$sample` aggregate to infer field names and types from a small sample.
  - Return collections as `TableMeta`, inferred fields as `ColumnMeta`.
- Implement `query(credentials, sql, params)`:
  - Parse the query string as JSON.
  - Support two forms:
    - Filter-only: `{"status": "active"}` — applied to `collection_name` from credentials.
    - Command-style: `{"find": "users", "filter": {...}, "limit": 10}`.
  - `collection_name` must be in credentials or in the command-style query.
- Implement `query_row()` — same as `query()` but returns single document.

**NOT in scope**: DocumentDB, Atlas (those extend this source in TASK-433).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/sources/mongodb.py` | CREATE | MongoSource |

---

## Implementation Notes

### Pattern to Follow
```python
import json
from parrot.tools.database.base import (
    AbstractDatabaseSource, ValidationResult, MetadataResult,
    QueryResult, RowResult, TableMeta, ColumnMeta,
)
from parrot.tools.database.sources import register_source


@register_source("mongo")
class MongoSource(AbstractDatabaseSource):
    driver = "mongo"
    sqlglot_dialect = None

    async def validate_query(self, query: str) -> ValidationResult:
        try:
            parsed = json.loads(query)
            if isinstance(parsed, dict):
                return ValidationResult(valid=True, dialect="json")
            if isinstance(parsed, list) and all(isinstance(d, dict) for d in parsed):
                return ValidationResult(valid=True, dialect="json-pipeline")
            return ValidationResult(
                valid=False,
                error="Query must be a JSON object (filter) or array of objects (pipeline)"
            )
        except json.JSONDecodeError as e:
            return ValidationResult(valid=False, error=str(e))
```

### Key Constraints
- asyncdb uses `"mongo"` driver with optional `dbtype` parameter
- `collection_name` is required in credentials for filter-only queries
- The `$sample` stage for metadata should sample ~100 documents max
- MongoDB field types are inferred from Python types (`str`, `int`, `float`,
  `list`, `dict`, `bool`, `datetime`)
- Query string is always a JSON string, never a raw Python dict

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` — MongoDB handling section
- `DriverInfo.DRIVER_MAP["mongo"]` — driver config reference

---

## Acceptance Criteria

- [ ] `MongoSource` registered as `"mongo"` in source registry
- [ ] `validate_query('{"status": "active"}')` returns `valid=True`
- [ ] `validate_query('[{"$match": {"status": "active"}}]')` returns `valid=True` (pipeline)
- [ ] `validate_query('not json')` returns `valid=False`
- [ ] `validate_query('"just a string"')` returns `valid=False`
- [ ] `get_metadata()` discovers collections and infers field types
- [ ] `query()` supports both filter-only and command-style queries
- [ ] `query_row()` returns single document
- [ ] Import works: `from parrot.tools.database.sources.mongodb import MongoSource`

---

## Test Specification

```python
# tests/tools/database/test_mongo_source.py
import pytest
from parrot.tools.database.sources.mongodb import MongoSource


class TestMongoSource:
    def test_driver_and_dialect(self):
        src = MongoSource()
        assert src.driver == "mongo"
        assert src.sqlglot_dialect is None

    @pytest.mark.asyncio
    async def test_validate_filter(self):
        src = MongoSource()
        result = await src.validate_query('{"status": "active"}')
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_pipeline(self):
        src = MongoSource()
        result = await src.validate_query('[{"$match": {"age": {"$gt": 25}}}]')
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_json(self):
        src = MongoSource()
        result = await src.validate_query("not json at all")
        assert result.valid is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_validate_non_object(self):
        src = MongoSource()
        result = await src.validate_query('"just a string"')
        assert result.valid is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — TASK-427 and TASK-428 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-432-dbtoolkit-mongo-source.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
