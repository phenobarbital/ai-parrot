# TASK-421: Implement MongoSource

**Feature**: datasetmanager-sources
**Spec**: `sdd/specs/datasetmanager-sources.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 2 from the spec: the `MongoSource` DataSource subclass.
> MongoDB/DocumentDB is a document-oriented database. This source is **read-only** with
> a strict requirement that every `fetch()` call must include a filter — no full-collection
> scans are allowed.
>
> The owner resolved that `projection` must always be explicitly provided to limit returned fields.

---

## Scope

- Implement `MongoSource(DataSource)` at `sources/mongo.py`
- Implement `prefetch_schema()`: call `find_one()` on the collection to get a single document, infer field names and Python types, exclude `_id` field
- Implement `fetch(**params)`:
  - **Require** a `filter` dict parameter — raise `ValueError` if not provided or empty
  - Accept `projection` dict parameter to limit returned fields (always required per owner)
  - Call `driver.query()` or equivalent with filter and projection
  - Convert results list to `pd.DataFrame`
- Implement `describe()`: return human-readable string with collection name and database
- Implement `cache_key` property: format `mongo:{database}:{collection}`
- Credential resolution: support DSN (MongoDB connection string) or credentials dict; use `_resolve_credentials` pattern from `table.py` for mongo driver
- Write unit tests for all the above

**NOT in scope**: DatasetManager registration method (TASK-423), write operations, full-collection scans

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/mongo.py` | CREATE | MongoSource implementation |
| `packages/ai-parrot/tests/tools/test_mongo_source.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
from .base import DataSource
from parrot._imports import lazy_import

class MongoSource(DataSource):
    def __init__(
        self,
        collection: str,
        name: str,
        database: str,
        credentials: Optional[Dict] = None,
        dsn: Optional[str] = None,
        required_filter: bool = True,
    ):
        self._collection = collection
        self._name = name
        self._database = database
        self._credentials = credentials
        self._dsn = dsn
        self._required_filter = required_filter
        self._schema: Dict[str, str] = {}

    async def fetch(self, **params) -> pd.DataFrame:
        filter_dict = params.get('filter')
        if self._required_filter and not filter_dict:
            raise ValueError(
                f"MongoSource '{self._name}' requires a filter parameter. "
                "Full-collection scans are not allowed."
            )
        projection = params.get('projection')
        if not projection:
            raise ValueError(
                f"MongoSource '{self._name}' requires a projection parameter."
            )
        # ... query with asyncdb mongo driver
```

### Key Constraints
- **Filter is mandatory** — this is a safety guardrail against returning millions of documents
- **Projection is mandatory** — per owner decision, always limit returned fields
- Exclude `_id` from schema prefetch (internal MongoDB field)
- MongoDB query syntax for filter: `{"status": "active", "amount": {"$gt": 100}}`
- asyncdb mongo driver API:
  - Connection via `AsyncDB('mongo', dsn=dsn)` or `AsyncDB('mongo', params=credentials)`
  - `driver.query(filter_dict)` or `driver.find(filter_dict, projection=projection)`
  - Results come as list of dicts → convert to DataFrame
- Type inference from `find_one()`: map Python types to string type names

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` — credential resolution pattern
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` — DataSource ABC
- asyncdb mongo driver: `https://github.com/phenobarbital/asyncdb/blob/master/asyncdb/drivers/mongo.py`

---

## Acceptance Criteria

- [ ] `MongoSource` inherits from `DataSource` and implements all abstract methods
- [ ] `prefetch_schema()` uses `find_one()` and excludes `_id` field
- [ ] `fetch()` raises `ValueError` when no filter is provided
- [ ] `fetch()` raises `ValueError` when no projection is provided
- [ ] `fetch(filter={...}, projection={...})` queries and returns DataFrame
- [ ] `cache_key` returns `mongo:{database}:{collection}`
- [ ] Credential resolution supports DSN and credentials dict
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_mongo_source.py -v`
- [ ] Import works: `from parrot.tools.dataset_manager.sources.mongo import MongoSource`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_mongo_driver():
    driver = AsyncMock()
    driver.find_one = AsyncMock(return_value={
        '_id': 'abc123', 'order_id': '123', 'amount': 99.99, 'status': 'shipped'
    })
    driver.query = AsyncMock(return_value=[
        {'order_id': '123', 'amount': 99.99, 'status': 'shipped'},
        {'order_id': '456', 'amount': 49.99, 'status': 'pending'},
    ])
    return driver


class TestMongoSource:
    async def test_prefetch_schema(self, mock_mongo_driver):
        """prefetch_schema calls find_one and infers types, excludes _id."""
        ...

    async def test_fetch_with_filter(self, mock_mongo_driver):
        """fetch(filter={...}, projection={...}) queries collection."""
        ...

    async def test_fetch_no_filter_raises(self):
        """fetch() without filter raises ValueError."""
        ...

    async def test_fetch_no_projection_raises(self):
        """fetch(filter={...}) without projection raises ValueError."""
        ...

    def test_cache_key(self):
        """cache_key format: mongo:{database}:{collection}."""
        ...

    def test_describe(self):
        """describe() includes collection and database name."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-sources.spec.md` for full context
2. **Check dependencies** — no dependencies for this task
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-421-mongo-source.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
