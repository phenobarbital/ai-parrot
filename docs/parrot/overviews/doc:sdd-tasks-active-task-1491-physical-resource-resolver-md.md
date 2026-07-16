---
type: Wiki Overview
title: 'TASK-1491: Physical-Resource Resolver'
id: doc:sdd-tasks-active-task-1491-physical-resource-resolver-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: that inspects a `DataSource` subclass and returns the set of driver + tables
  /
relates_to:
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.dialects
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.memory
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.opaque
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.query_slug
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.resolver
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.sql
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.table
  rel: mentions
---

# TASK-1491: Physical-Resource Resolver

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1490
**Assigned-to**: unassigned

---

## Context

> Spec Module 1. The core of the authorization feature: a pure, side-effect-free
> resolver that maps any `DataSource` to the set of physical resources it will
> touch. Uses sqlglot for SQL sources (table extraction + read-only gate),
> trivial extraction for table/slug sources, and delegates to opaque resolvers
> (TASK-1492) for non-SQL sources. This is the function that makes alias-spoofing
> (B1) impossible.

---

## Scope

- Implement `resolve_physical_resources(source: DataSource) -> PhysicalResources`
  that inspects a `DataSource` subclass and returns the set of driver + tables /
  source identifiers it will touch.
- Implement `physical_tables(sql: str, dialect: str) -> set[str]` using sqlglot:
  parse the SQL, walk the AST for `exp.Table`, exclude CTE aliases.
- Implement the **read-only gate**: if the root AST node is not
  `Select`/`Union`/`Subquery`/`With`, raise `ReadOnlyViolation`.
- Define the `PhysicalResources` Pydantic model and `ReadOnlyViolation` exception.
- Write comprehensive unit tests covering CTEs, subqueries, JOINs, UNIONs,
  DML/DDL rejection, parse failures.

**NOT in scope**: RLS injection (TASK-1494), guard evaluation (TASK-1495),
opaque-source resolution details (TASK-1492 — this task calls into the opaque
module but doesn't implement it), `AuthorizingDataSource` (TASK-1496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/resolver.py` | CREATE | `resolve_physical_resources()`, `physical_tables()`, `PhysicalResources`, `ReadOnlyViolation` |
| `tests/auth/test_physical_resource_resolver.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# DataSource base and subclasses
from parrot.tools.dataset_manager.sources.base import DataSource     # line 23
from parrot.tools.dataset_manager.sources.sql import SQLQuerySource  # line 26 (via __init__.py:26)
from parrot.tools.dataset_manager.sources.table import TableSource   # line 113 (via __init__.py:27)
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource  # line 51 (via __init__.py:25)
from parrot.tools.dataset_manager.sources.memory import InMemorySource       # line 14 (via __init__.py:24)

# Dialect mapping (from TASK-1490)
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect

# sqlglot
import sqlglot
from sqlglot import exp
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/sources/base.py:23
class DataSource(ABC):
    def __init__(self, routing_meta: Dict | None = None) -> None:    # line 46
    async def fetch(self, **params) -> pd.DataFrame:                 # line 69 (abstract)
    def describe(self) -> str:                                        # line 90 (abstract)
    @property
    def has_builtin_cache(self) -> bool:                              # line 102
    @property
    def cache_key(self) -> str:                                       # line 117 (abstract)

# parrot/tools/dataset_manager/sources/sql.py:45
class SQLQuerySource(DataSource):
    def __init__(self, sql: str, driver: str, dsn=None, credentials=None, cache_ttl=3600):
    # Attributes: self._sql, self._driver, self._dsn, self._credentials

# parrot/tools/dataset_manager/sources/table.py:146
class TableSource(DataSource):
    def __init__(self, table: str, driver: str, dsn=None, credentials=None,
                 strict_schema=True, permanent_filter=None, allowed_columns=None):
    # Attributes: self._table, self._driver

# parrot/tools/dataset_manager/sources/query_slug.py:51
class QuerySlugSource(DataSource):
    def __init__(self, slug: str, prefetch_schema_enabled=True, permanent_filter=None):
    # Attributes: self._slug, self._permanent_filter

# parrot/tools/dataset_manager/sources/memory.py:14
class InMemorySource(DataSource):
    def __init__(self, df: pd.DataFrame, name: str):
```

### Does NOT Exist
- ~~`DataSource.driver`~~ — not a base-class attribute; access via subclass-specific `self._driver`
- ~~`DataSource.sql`~~ — not a base-class attribute; only `SQLQuerySource` has `self._sql`
- ~~`DataSource.table`~~ — not a base-class attribute; only `TableSource` has `self._table`
- ~~`ReadOnlyViolation`~~ — does not exist yet (this task creates it)
- ~~`PhysicalResources`~~ — does not exist yet (this task creates it)
- ~~`parrot.tools.dataset_manager.sources.resolver`~~ — does not exist yet (this task creates it)
- ~~`parrot.tools.dataset_manager.sources.opaque`~~ — does not exist yet (TASK-1492 creates it)

---

## Implementation Notes

### Pattern to Follow

The resolver uses `isinstance` checks to dispatch on source type:

```python
from pydantic import BaseModel, Field

class PhysicalResources(BaseModel):
    driver: str | None = None
    tables: set[str] = Field(default_factory=set)
    source_type: str | None = None
    source_id: str | None = None

class ReadOnlyViolation(Exception):
    """Raised when a SQL statement is not read-only (DML/DDL detected)."""

def physical_tables(sql: str, dialect: str) -> set[str]:
    """Extract physical table references from a SQL query using sqlglot."""
    tree = sqlglot.parse_one(sql, dialect=dialect)
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery, exp.With)):
        raise ReadOnlyViolation(f"Statement type {type(tree).__name__} is not read-only")
    cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    tables = set()
    for t in tree.find_all(exp.Table):
        if t.name in cte_names:
            continue
        tables.add(".".join(p for p in (t.catalog, t.db, t.name) if p))
    return tables

def resolve_physical_resources(source: DataSource) -> PhysicalResources:
    """Resolve a DataSource to its physical resource identifiers."""
    if isinstance(source, SQLQuerySource):
        dialect = driver_to_dialect(source._driver)
        if dialect is None:
            return PhysicalResources(driver=source._driver)  # unknown dialect
        tables = physical_tables(source._sql, dialect)
        return PhysicalResources(
            driver=source._driver,
            tables={f"{source._driver}:{t}" for t in tables},
        )
    elif isinstance(source, TableSource):
        return PhysicalResources(
            driver=source._driver,
            tables={f"{source._driver}:{source._table}"},
        )
    elif isinstance(source, QuerySlugSource):
        # Slug resources are declared at registration time — resolver returns
        # minimal info; guard checks dataset-level grants for slugs.
        return PhysicalResources()
    elif isinstance(source, InMemorySource):
        return PhysicalResources()  # no driver touch
    else:
        # Opaque sources — delegate to opaque resolver (TASK-1492)
        try:
            from .opaque import resolve_opaque_source
            return resolve_opaque_source(source)
        except ImportError:
            return PhysicalResources()
```

### Key Constraints
- `physical_tables()` must be a **pure function** — no side effects, no I/O.
- Access source attributes via private attrs (`_driver`, `_sql`, `_table`) since
  `DataSource` has no public driver/sql/table properties.
- sqlglot `parse_one` raises `sqlglot.errors.ParseError` on invalid SQL — let it
  propagate (caller decides fail-open vs fail-closed).
- Table names are prefixed with driver: `"bigquery:schema.table"` to match the
  policy resource format `table:<driver>:<schema>.<table>`.
- The read-only gate checks the top-level node type: `exp.Select`, `exp.Union`,
  `exp.Subquery`, `exp.With` are allowed; everything else (`exp.Drop`,
  `exp.Update`, `exp.Insert`, `exp.Delete`, `exp.Merge`) raises `ReadOnlyViolation`.

### References in Codebase
- `parrot/tools/dataset_manager/sources/sql.py` — `SQLQuerySource` attrs
- `parrot/tools/dataset_manager/sources/table.py` — `TableSource` attrs
- `parrot/tools/dataset_manager/sources/query_slug.py` — `QuerySlugSource` attrs

---

## Acceptance Criteria

- [ ] `physical_tables("SELECT * FROM sales.orders", "postgres")` → `{"sales.orders"}`
- [ ] CTE aliases excluded from result
- [ ] Subquery tables captured
- [ ] UNION branch tables all captured
- [ ] JOIN tables captured
- [ ] `DROP TABLE x` raises `ReadOnlyViolation`
- [ ] `UPDATE x SET ...` raises `ReadOnlyViolation`
- [ ] `INSERT INTO x ...` raises `ReadOnlyViolation`
- [ ] Invalid SQL raises `sqlglot.errors.ParseError`
- [ ] `resolve_physical_resources(SQLQuerySource(...))` returns driver + tables
- [ ] `resolve_physical_resources(TableSource(...))` returns driver + single table
- [ ] `resolve_physical_resources(InMemorySource(...))` returns empty resources
- [ ] All tests pass: `pytest tests/auth/test_physical_resource_resolver.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/sources/resolver.py`

---

## Test Specification

```python
# tests/auth/test_physical_resource_resolver.py
import pytest
import sqlglot
from parrot.tools.dataset_manager.sources.resolver import (
    physical_tables,
    resolve_physical_resources,
    PhysicalResources,
    ReadOnlyViolation,
)


class TestPhysicalTables:
    def test_simple_select(self):
        result = physical_tables("SELECT * FROM sales.orders", "postgres")
        assert result == {"sales.orders"}

    def test_join(self):
        sql = "SELECT a.id FROM sales.orders a JOIN hr.employees b ON a.emp_id = b.id"
        result = physical_tables(sql, "postgres")
        assert result == {"sales.orders", "hr.employees"}

    def test_cte_alias_excluded(self):
        sql = """
        WITH recent AS (SELECT * FROM sales.orders WHERE dt > '2024-01-01')
        SELECT * FROM recent JOIN hr.employees ON recent.emp_id = hr.employees.id
        """
        result = physical_tables(sql, "postgres")
        assert "recent" not in result
        assert "sales.orders" in result
        assert "hr.employees" in result

    def test_subquery(self):
        sql = "SELECT * FROM (SELECT id FROM finance.accounts) sub"
        result = physical_tables(sql, "postgres")
        assert "finance.accounts" in result

    def test_union(self):
        sql = "SELECT id FROM sales.us UNION ALL SELECT id FROM sales.eu"
        result = physical_tables(sql, "postgres")
        assert result == {"sales.us", "sales.eu"}

    def test_drop_raises_read_only(self):
        with pytest.raises(ReadOnlyViolation):
            physical_tables("DROP TABLE sales.orders", "postgres")

    def test_update_raises_read_only(self):
        with pytest.raises(ReadOnlyViolation):
            physical_tables("UPDATE sales.orders SET status = 'x'", "postgres")

    def test_insert_raises_read_only(self):
        with pytest.raises(ReadOnlyViolation):
            physical_tables("INSERT INTO sales.orders VALUES (1)", "postgres")

    def test_invalid_sql_raises_parse_error(self):
        with pytest.raises(sqlglot.errors.ParseError):
            physical_tables("NOT VALID SQL AT ALL !!!", "postgres")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` for full context
2. **Check dependencies** — verify TASK-1490 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm source class attributes still match
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1491-physical-resource-resolver.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —

**Deviations from spec**: none
