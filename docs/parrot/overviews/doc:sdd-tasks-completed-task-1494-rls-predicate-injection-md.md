---
type: Wiki Overview
title: 'TASK-1494: RLS Predicate Injection'
id: doc:sdd-tasks-completed-task-1494-rls-predicate-injection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: '— sqlglot AST rewrite: wrap as `SELECT * FROM (<orig>) AS _rls WHERE <pred>`'
relates_to:
- concept: mod:parrot.auth.rls_registry
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.dialects
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.query_slug
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.rls
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.table
  rel: mentions
---

# TASK-1494: RLS Predicate Injection

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1490, TASK-1493
**Assigned-to**: unassigned

---

## Context

> Spec Module 5. Once the RLS registry (TASK-1493) provides rendered predicates,
> this module injects them into the actual queries/sources. Each source type has
> a different injection mechanism: sqlglot AST rewrite for SQL, permanent_filter
> for TableSource/QuerySlugSource, Mongo filter merge, and post-fetch for API
> sources. This is the mechanism that makes row-level restrictions deterministic.

---

## Scope

- Implement injection functions for each source type:
  - `inject_rls_sql(sql: str, dialect: str, predicates: list[RlsPredicate]) -> tuple[str, dict]`
    — sqlglot AST rewrite: wrap as `SELECT * FROM (<orig>) AS _rls WHERE <pred>`
    or push predicate into base-table scans. Return rewritten SQL + bound params.
  - `inject_rls_table_source(source: TableSource, predicates: list[RlsPredicate]) -> TableSource`
    — extend existing `permanent_filter` dict with RLS conditions.
  - `inject_rls_query_slug(source: QuerySlugSource, predicates: list[RlsPredicate]) -> QuerySlugSource`
    — merge predicate into slug conditions.
  - `inject_rls_mongo(source: MongoSource, predicates: list[RlsPredicate]) -> dict`
    — merge predicate into Mongo query filter dict via `$and`.
  - `inject_rls_postfetch(df: pd.DataFrame, predicates: list[RlsPredicate]) -> pd.DataFrame`
    — post-fetch row filter for API sources (Airtable/Smartsheet).
- All injection methods use bound parameters — never interpolate values into SQL.
- Write unit tests for each injection type.

**NOT in scope**: Registry logic (TASK-1493), resolver logic (TASK-1491),
guard evaluation (TASK-1495), `AuthorizingDataSource` orchestration (TASK-1496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/rls.py` | CREATE | All RLS injection functions |
| `tests/auth/test_rls_injection.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-1493
from parrot.auth.rls_registry import RlsPredicate

# From TASK-1490
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect

# sqlglot for AST rewrite
import sqlglot
from sqlglot import exp

# Source classes
from parrot.tools.dataset_manager.sources.table import TableSource
# TableSource.__init__: permanent_filter: Optional[Dict[str, Any]] = None (line 153)
# Stored as: self._permanent_filter: Dict[str, Any] = permanent_filter or {} (line 161)

from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
# QuerySlugSource.__init__: permanent_filter: Optional[Dict[str, Any]] = None (line 55)
# Stored as: self._permanent_filter: Dict[str, Any] = permanent_filter or {} (line 59)
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/sources/table.py:146
class TableSource(DataSource):
    def __init__(self, table: str, driver: str, dsn=None, credentials=None,
                 strict_schema=True, permanent_filter=None, allowed_columns=None):
    # self._permanent_filter: Dict[str, Any]  (line 161)
    # self._driver: str
    # self._table: str

# parrot/tools/dataset_manager/sources/query_slug.py:51
class QuerySlugSource(DataSource):
    def __init__(self, slug: str, prefetch_schema_enabled=True, permanent_filter=None):
    # self._permanent_filter: Dict[str, Any]  (line 59)

# parrot/tools/dataset_manager/sources/mongo.py:70
class MongoSource(DataSource):
    # self._collection, self._database
    # Mongo queries use filter dicts — verify exact fetch() signature
```

### Does NOT Exist
- ~~`parrot.tools.dataset_manager.sources.rls`~~ — does not exist yet (this task creates it)
- ~~`TableSource.add_rls_filter()`~~ — does not exist; modify `_permanent_filter` directly
- ~~`QuerySlugSource.add_filter()`~~ — does not exist; modify `_permanent_filter` directly
- ~~`MongoSource.query_filter`~~ — verify exact attribute name before using

---

## Implementation Notes

### Pattern to Follow

```python
import sqlglot
from sqlglot import exp

def inject_rls_sql(
    sql: str,
    dialect: str,
    predicates: list["RlsPredicate"],
) -> tuple[str, dict]:
    """Inject RLS predicates into a SQL query via sqlglot AST rewrite.

    Returns (rewritten_sql, bound_params) where bound_params maps
    placeholder names to values for parameterized execution.
    """
    if not predicates:
        return sql, {}

    # Strategy: wrap original query and add WHERE clause
    # SELECT * FROM (<original>) AS _rls WHERE <pred1> AND <pred2>
    all_params = {}
    where_parts = []
    for pred in predicates:
        where_parts.append(pred.sql_predicate)
        all_params.update(pred.bound_params)

    combined = " AND ".join(f"({p})" for p in where_parts)
    wrapped = f"SELECT * FROM ({sql}) AS _rls WHERE {combined}"
    return wrapped, all_params
```

### Key Constraints
- **NEVER interpolate** subject values into SQL. The `RlsPredicate.sql_predicate`
  contains parameter placeholders (`:p0`, `:p1`); the actual values are in
  `bound_params`. The injection function passes both through.
- For `TableSource` and `QuerySlugSource`, modifying `_permanent_filter` is the
  existing mechanism — extend it, don't replace it.
- For Mongo, predicates are translated to filter dict format (`{"$and": [...]}`).
- For post-fetch (Airtable/Smartsheet), apply pandas DataFrame filtering.
- The wrapping approach (`SELECT * FROM (...) AS _rls WHERE ...`) is simpler
  and more reliable than pushing predicates into individual table scans. Use it
  as the default strategy.

### References in Codebase
- `parrot/tools/dataset_manager/sources/table.py` — `permanent_filter` usage
- `parrot/tools/dataset_manager/sources/query_slug.py` — `permanent_filter` usage
- `parrot/tools/dataset_manager/sources/mongo.py` — Mongo filter patterns

---

## Acceptance Criteria

- [ ] `inject_rls_sql(sql, dialect, [pred])` returns wrapped SQL with WHERE clause
- [ ] Bound parameters are passed through, never interpolated into SQL
- [ ] Multiple predicates combined with AND
- [ ] Empty predicate list → original SQL unchanged
- [ ] `inject_rls_table_source()` extends `_permanent_filter`
- [ ] `inject_rls_query_slug()` merges into slug conditions
- [ ] `inject_rls_mongo()` produces `$and` filter structure
- [ ] `inject_rls_postfetch()` filters DataFrame rows correctly
- [ ] AC9 verified: crafted attribute value cannot inject SQL
- [ ] All tests pass: `pytest tests/auth/test_rls_injection.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/sources/rls.py`

---

## Test Specification

```python
# tests/auth/test_rls_injection.py
import pytest
from parrot.auth.rls_registry import RlsPredicate
from parrot.tools.dataset_manager.sources.rls import (
    inject_rls_sql,
    inject_rls_postfetch,
)


class TestInjectRlsSql:
    def test_single_predicate(self):
        pred = RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0, :p1)",
            bound_params={"p0": ["northeast"], "p1": ["southeast"]},
        )
        sql, params = inject_rls_sql(
            "SELECT * FROM sales.orders", "postgres", [pred]
        )
        assert "_rls" in sql
        assert "WHERE" in sql
        assert ":p0" in sql or "p0" in str(params)

    def test_no_predicates_passthrough(self):
        sql, params = inject_rls_sql(
            "SELECT * FROM sales.orders", "postgres", []
        )
        assert sql == "SELECT * FROM sales.orders"
        assert params == {}

    def test_multiple_predicates_and(self):
        pred1 = RlsPredicate(
            table="t1", sql_predicate="a = :p0", bound_params={"p0": ["x"]}
        )
        pred2 = RlsPredicate(
            table="t2", sql_predicate="b = :p1", bound_params={"p1": ["y"]}
        )
        sql, params = inject_rls_sql("SELECT * FROM t", "postgres", [pred1, pred2])
        assert "AND" in sql

    def test_no_value_interpolation(self):
        """AC9: crafted values must not appear in SQL text."""
        pred = RlsPredicate(
            table="t",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["'; DROP TABLE users; --"]},
        )
        sql, params = inject_rls_sql("SELECT * FROM t", "postgres", [pred])
        assert "DROP" not in sql
        assert "'; DROP TABLE users; --" not in sql


class TestInjectRlsPostfetch:
    def test_filters_rows(self):
        import pandas as pd
        df = pd.DataFrame({
            "region": ["northeast", "southeast", "west"],
            "amount": [100, 200, 300],
        })
        pred = RlsPredicate(
            table="t",
            sql_predicate="region IN (:p0, :p1)",
            bound_params={"p0": ["northeast"], "p1": ["southeast"]},
        )
        result = inject_rls_postfetch(df, [pred])
        assert len(result) == 2
        assert "west" not in result["region"].values
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` §5.5 for RLS injection details
2. **Check dependencies** — verify TASK-1490 and TASK-1493 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `permanent_filter` attributes on TableSource/QuerySlugSource
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1494-rls-predicate-injection.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-08
**Notes**: Implemented all 5 injection functions: inject_rls_sql (wrap strategy), inject_rls_table_source, inject_rls_query_slug (both extend _permanent_filter), inject_rls_mongo ($and filter), inject_rls_postfetch (pandas row filter). All 11 tests pass including AC9 SQL-injection safety.

**Deviations from spec**: none
