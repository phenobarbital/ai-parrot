---
type: Wiki Overview
title: 'TASK-933: Source-layer test_connection overrides for non-SQL drivers'
id: doc:sdd-tasks-completed-task-933-source-test-connection-overrides-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec Module 3. TASK-931 adds a default `test_connection()` to
relates_to:
- concept: mod:parrot.tools.databasequery.base
  rel: mentions
- concept: mod:parrot.tools.databasequery.sources.mongodb
  rel: mentions
---

# TASK-933: Source-layer test_connection overrides for non-SQL drivers

**Feature**: FEAT-136 — database-toolkit-parity
**Spec**: `sdd/specs/database-toolkit-parity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-931
**Assigned-to**: unassigned

---

## Context

Spec Module 3. TASK-931 adds a default `test_connection()` to
`AbstractDatabaseSource` that runs `SELECT 1`. This works for SQL drivers
(PG, MySQL, BigQuery, SQLite, Oracle, MSSQL, ClickHouse, DuckDB) but not
for non-SQL sources. This task adds overrides for MongoDB, Elastic, and InfluxDB.

---

## Scope

- Override `test_connection()` on `MongoSource` — use MongoDB `ping` command.
- Override `test_connection()` on `DocumentDBSource` — inherit from MongoSource
  or implement `ping` with SSL.
- Override `test_connection()` on `AtlasSource` — inherit from MongoSource
  or implement `ping`.
- Override `test_connection()` on `ElasticSource` — use cluster health or `info()`.
- Override `test_connection()` on `InfluxSource` — use `buckets()` or a health check.
- Write unit tests for each override (mocked connections).

**NOT in scope**: toolkit.py changes, credential work, SQL source overrides
(they use the base class default from TASK-931).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/mongodb.py` | MODIFY | Add `test_connection` override |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/documentdb.py` | MODIFY | Add `test_connection` override (or inherit) |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/atlas.py` | MODIFY | Add `test_connection` override (or inherit) |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/elastic.py` | MODIFY | Add `test_connection` override |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/influx.py` | MODIFY | Add `test_connection` override |
| `tests/tools/test_database_test_connection.py` | CREATE | Unit tests for source overrides |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.databasequery.base import AbstractDatabaseSource  # verified: base.py:186
# After TASK-931 adds it:
# AbstractDatabaseSource.test_connection(self, credentials) -> bool
```

### Existing Signatures to Use
```python
# sources/mongodb.py:35
class MongoSource(AbstractDatabaseSource):
    driver = "mongo"                                  # line 42
    sqlglot_dialect = None                            # line 43
    def __init__(self): ...                           # line 45
    async def get_default_credentials(self): ...      # line 49
    # _get_db inherited from base

# sources/elastic.py:40
class ElasticSource(AbstractDatabaseSource):
    driver = "elastic"                                # line 48
    sqlglot_dialect = None                            # line 49
    @staticmethod
    def _get_es_client(conn): ...                     # line 74

# sources/influx.py (registered as "influx")
class InfluxSource(AbstractDatabaseSource):
    driver = "influx"
    sqlglot_dialect = None

# base.py — connection pool helper
def _get_db(self, asyncdb_driver, dsn, params) -> Any:  # line 328
```

### Does NOT Exist
- ~~`MongoSource.ping()`~~ — not a method; must implement via asyncdb connection
- ~~`ElasticSource.health()`~~ — not a method; use the ES client from `_get_es_client()`
- ~~`InfluxSource.health()`~~ — not a method; must implement

---

## Implementation Notes

### Pattern to Follow
```python
# MongoSource.test_connection (mongodb.py)
async def test_connection(self, credentials: dict[str, Any]) -> bool:
    try:
        dsn = credentials.get("dsn")
        params = {k: v for k, v in credentials.items() if k != "dsn"}
        db = self._get_db("mongo", dsn, params or None)
        async with await db.connection() as conn:
            await conn.ping()
        return True
    except Exception:
        return False

# ElasticSource.test_connection (elastic.py)
async def test_connection(self, credentials: dict[str, Any]) -> bool:
    try:
        dsn = credentials.get("dsn")
        params = {k: v for k, v in credentials.items() if k != "dsn"}
        db = self._get_db("elastic", dsn, params or None)
        async with await db.connection() as conn:
            es = self._get_es_client(conn)
            await es.info()
        return True
    except Exception:
        return False
```

### Key Constraints
- Must return `bool`, never raise exceptions
- Use `self._get_db()` for connection pool reuse
- DocumentDB and Atlas can likely inherit MongoSource's implementation
  if their parent class hierarchy supports it; verify first
- All implementations must be async

---

## Acceptance Criteria

- [ ] `MongoSource().test_connection(creds)` uses MongoDB ping command
- [ ] `ElasticSource().test_connection(creds)` uses ES client info/health
- [ ] `InfluxSource().test_connection(creds)` uses a health check
- [ ] `DocumentDBSource().test_connection(creds)` works (inherits or overrides)
- [ ] `AtlasSource().test_connection(creds)` works (inherits or overrides)
- [ ] All overrides return `bool` and never raise
- [ ] All tests pass: `pytest tests/tools/test_database_test_connection.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestMongoTestConnection:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        from parrot.tools.databasequery.sources.mongodb import MongoSource
        source = MongoSource()
        # Mock the connection to succeed
        with patch.object(source, '_get_db') as mock_db:
            mock_conn = AsyncMock()
            mock_db.return_value.connection = AsyncMock(return_value=mock_conn)
            result = await source.test_connection({"host": "localhost"})
            assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self):
        from parrot.tools.databasequery.sources.mongodb import MongoSource
        source = MongoSource()
        with patch.object(source, '_get_db', side_effect=Exception("fail")):
            result = await source.test_connection({"host": "badhost"})
            assert result is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-931 is in `tasks/completed/`
3. **Verify** that `AbstractDatabaseSource.test_connection()` exists (added by TASK-931)
4. **Check asyncdb API** — verify `conn.ping()` exists for mongo driver, and
   what methods are available on the elastic client
5. **Implement** overrides, then tests
6. **Move this file** to `tasks/completed/` and update index

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-04-29
**Notes**: Implemented test_connection() overrides for all non-SQL drivers:
- MongoSource: added ping command override using `_get_mongo_client(conn).admin.command("ping")`
- ElasticSource: added info() call override using `_get_es_client(conn).info()`
- InfluxSource: added buckets() Flux query override via `conn.query("buckets()")`
- DocumentDBSource: docstring updated to document inheritance from MongoSource (no override needed)
- AtlasSource: docstring updated to document inheritance from MongoSource (no override needed)
- Created tests/tools/test_database_test_connection.py with 23 tests (all pass)

**Deviations from spec**: DocumentDBSource and AtlasSource files were modified with
docstring updates (not code overrides) since inheritance from MongoSource is sufficient per
task spec ("inherit from MongoSource or implement ping").
