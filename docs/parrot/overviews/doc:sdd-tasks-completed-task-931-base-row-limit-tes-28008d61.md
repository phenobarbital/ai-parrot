---
type: Wiki Overview
title: 'TASK-931: Add row-limit helper and test_connection to AbstractDatabaseSource'
id: doc:sdd-tasks-completed-task-931-base-row-limit-test-connection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec Module 1. The toolkit has no row-limit enforcement and no way to test
relates_to:
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.tools.databasequery
  rel: mentions
- concept: mod:parrot.tools.databasequery.base
  rel: mentions
- concept: mod:parrot.tools.databasequery.sources
  rel: mentions
---

# TASK-931: Add row-limit helper and test_connection to AbstractDatabaseSource

**Feature**: FEAT-136 — database-toolkit-parity
**Spec**: `sdd/specs/database-toolkit-parity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 1. The toolkit has no row-limit enforcement and no way to test
connectivity. This task adds two foundational pieces to `base.py` that all
subsequent tasks depend on:

1. A `add_row_limit()` free function ported from the legacy tool's
   `_add_row_limit()` (tool.py:692-739).
2. A `test_connection()` method on `AbstractDatabaseSource` with a default
   SQL implementation (`SELECT 1`).

---

## Scope

- Add `add_row_limit(query, max_rows, driver)` free function to `base.py`.
  Must handle SQL (`LIMIT`), Flux (`|> limit(n:)`), Elastic JSON (`size`),
  and pass-through for MQL. Port logic from tool.py:692-739.
- Add `async def test_connection(self, credentials) -> bool` to
  `AbstractDatabaseSource` with a concrete default implementation that
  calls `self.query(credentials, "SELECT 1")` and returns `True` on
  success, `False` on exception. Non-SQL sources will override in TASK-933.
- Import `normalize_driver` from `sources/__init__.py` and the
  `_DRIVER_TO_QUERY_LANGUAGE` mapping from `toolkit.py` (or duplicate the
  small mapping locally) to resolve the dialect for `add_row_limit`.
- Export `add_row_limit` from `databasequery/__init__.py`.
- Write unit tests for `add_row_limit` covering all dialects and edge cases.

**NOT in scope**: modifying toolkit.py, source overrides for non-SQL
test_connection, or the interface credential work.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/databasequery/base.py` | MODIFY | Add `add_row_limit()` function and `test_connection()` method |
| `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py` | MODIFY | Export `add_row_limit` |
| `tests/tools/test_database_row_limit.py` | CREATE | Unit tests for `add_row_limit` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.databasequery.base import AbstractDatabaseSource  # verified: base.py:186
from parrot.tools.databasequery.base import QueryResult             # verified: base.py:147
from parrot.tools.databasequery.sources import normalize_driver     # verified: sources/__init__.py:45
from parrot.security import QueryLanguage                           # verified: security/__init__.py:10
```

### Existing Signatures to Use
```python
# parrot/tools/databasequery/base.py
class AbstractDatabaseSource(ABC):                    # line 186
    driver: str                                       # line 199
    sqlglot_dialect: str | None = None                # line 200
    async def query(self, credentials, sql, params?) -> QueryResult:  # line 289

# parrot/tools/databasequery/toolkit.py — query language mapping to port
_DRIVER_TO_QUERY_LANGUAGE: dict[str, QueryLanguage]   # line 36-54

# parrot/tools/databasequery/tool.py — reference implementation to port
def _add_row_limit(self, query, max_rows, driver):    # line 692-739
```

### Does NOT Exist
- ~~`AbstractDatabaseSource.test_connection()`~~ — does not exist yet; this task adds it
- ~~`base.add_row_limit()`~~ — does not exist yet; this task adds it
- ~~`AbstractDatabaseSource.max_rows`~~ — not an attribute; max_rows is a parameter

---

## Implementation Notes

### Pattern to Follow
```python
# Port from tool.py:692-739, adapted as a free function
def add_row_limit(query: str, max_rows: int, driver: str) -> str:
    """Inject dialect-specific row limit into a query string."""
    from parrot.security import QueryLanguage
    from parrot.tools.databasequery.sources import normalize_driver
    # ... resolve language, inject LIMIT/|> limit()/size
```

```python
# Default test_connection on AbstractDatabaseSource
async def test_connection(self, credentials: dict[str, Any]) -> bool:
    """Test connectivity. SQL sources use SELECT 1; non-SQL override."""
    try:
        await self.query(credentials, "SELECT 1")
        return True
    except Exception:
        return False
```

### Key Constraints
- `add_row_limit` must be a free function (not a method) — importable independently
- Must handle the case where `LIMIT` is already present (no double-limit)
- MQL queries pass through unchanged (limit is a parameter, not in the query string)
- `test_connection` must catch all exceptions and return bool (never raise)

---

## Acceptance Criteria

- [ ] `add_row_limit("SELECT * FROM t", 100, "pg")` returns `"SELECT * FROM t LIMIT 100"`
- [ ] `add_row_limit("SELECT * FROM t LIMIT 50", 100, "pg")` returns unchanged
- [ ] `add_row_limit('from(bucket:"b")', 10, "influx")` appends `|> limit(n: 10)`
- [ ] `add_row_limit('{"query":{}}', 10, "elastic")` sets `"size": 10` in JSON
- [ ] `add_row_limit('{"status":"active"}', 10, "mongo")` returns unchanged (MQL)
- [ ] `AbstractDatabaseSource.test_connection()` returns `True` when `query()` succeeds
- [ ] `AbstractDatabaseSource.test_connection()` returns `False` when `query()` raises
- [ ] `from parrot.tools.databasequery import add_row_limit` works
- [ ] All tests pass: `pytest tests/tools/test_database_row_limit.py -v`

---

## Test Specification

```python
import json
import pytest
from parrot.tools.databasequery.base import add_row_limit


class TestAddRowLimit:
    def test_sql_adds_limit(self):
        result = add_row_limit("SELECT * FROM users", 100, "pg")
        assert result == "SELECT * FROM users LIMIT 100"

    def test_sql_no_double_limit(self):
        result = add_row_limit("SELECT * FROM users LIMIT 50", 100, "pg")
        assert "LIMIT 50" in result
        assert result.count("LIMIT") == 1

    def test_flux_adds_limit(self):
        q = 'from(bucket:"test") |> range(start: -1h)'
        result = add_row_limit(q, 10, "influx")
        assert "|> limit(n: 10)" in result

    def test_elastic_adds_size(self):
        q = json.dumps({"query": {"match_all": {}}})
        result = add_row_limit(q, 50, "elastic")
        parsed = json.loads(result)
        assert parsed["size"] == 50

    def test_mql_passthrough(self):
        q = '{"status": "active"}'
        result = add_row_limit(q, 10, "mongo")
        assert result == q

    def test_mysql_alias(self):
        result = add_row_limit("SELECT 1", 5, "mariadb")
        assert "LIMIT 5" in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-931-base-row-limit-test-connection.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
