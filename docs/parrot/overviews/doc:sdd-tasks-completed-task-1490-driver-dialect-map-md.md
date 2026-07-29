---
type: Wiki Overview
title: 'TASK-1490: Driver–Dialect Map'
id: doc:sdd-tasks-completed-task-1490-driver-dialect-map-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: driver aliases (as returned by `normalize_driver`) to sqlglot 30.9.0 dialect
relates_to:
- concept: mod:parrot.tools.databasequery.sources
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.dialects
  rel: mentions
---

# TASK-1490: Driver–Dialect Map

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 2. The physical-resource resolver (TASK-1491) needs to know which
> sqlglot dialect corresponds to each ai-parrot driver alias so it can parse SQL
> deterministically. This is a leaf module with no dependencies — it can be
> implemented first and in parallel with other leaf tasks.

---

## Scope

- Implement `driver_to_dialect(driver: str) -> Optional[str]` that maps ai-parrot
  driver aliases (as returned by `normalize_driver`) to sqlglot 30.9.0 dialect
  identifiers.
- Unknown/unmapped drivers return `None` (caller decides fail-open vs fail-closed).
- Write unit tests covering all known aliases and the unknown-driver case.

**NOT in scope**: SQL parsing logic (TASK-1491), resolver logic, guard logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/dialects.py` | CREATE | `driver_to_dialect()` + `_DRIVER_DIALECT_MAP` |
| `tests/auth/test_driver_dialect_map.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.databasequery.sources import normalize_driver
# verified: packages/ai-parrot/src/parrot/tools/databasequery/sources/__init__.py:45
```

### Existing Signatures to Use
```python
# parrot/tools/databasequery/sources/__init__.py:24–34
_DRIVER_ALIASES: dict[str, str] = {
    "postgres": "pg", "postgresql": "pg", "mariadb": "mysql",
    "bq": "bigquery", "sqlserver": "mssql", "influxdb": "influx",
    "mongodb": "mongo", "elasticsearch": "elastic", "opensearch": "elastic",
}

# parrot/tools/databasequery/sources/__init__.py:45
def normalize_driver(driver: str) -> str:
    d = driver.lower().strip()
    return _DRIVER_ALIASES.get(d, d)
```

### Does NOT Exist
- ~~`parrot.tools.dataset_manager.sources.dialects`~~ — does not exist yet (this task creates it)
- ~~`sqlglot.Dialect.get_or_raise`~~ — do not use; just map strings

---

## Implementation Notes

### Pattern to Follow
```python
# Pure mapping module — no classes, no state, no I/O.
import sqlglot

_DRIVER_DIALECT_MAP: dict[str, str] = {
    "pg": "postgres",
    "mysql": "mysql",
    "bigquery": "bigquery",
    "mssql": "tsql",
    "oracle": "oracle",
    "snowflake": "snowflake",
    "redshift": "redshift",
    "clickhouse": "clickhouse",
    "duckdb": "duckdb",
    "sqlite": "sqlite",
    "trino": "trino",
    "presto": "presto",
    "spark": "spark",
    "databricks": "databricks",
}

def driver_to_dialect(driver: str) -> str | None:
    """Map an ai-parrot driver name to a sqlglot dialect identifier.

    Args:
        driver: Raw or normalized driver name.

    Returns:
        sqlglot dialect string, or None if unmapped.
    """
    from parrot.tools.databasequery.sources import normalize_driver
    canonical = normalize_driver(driver)
    return _DRIVER_DIALECT_MAP.get(canonical)
```

### Key Constraints
- The map keys are **canonical** driver names (output of `normalize_driver`),
  NOT the raw aliases.
- sqlglot 30.9.0 dialect ids are confirmed: `postgres`, `mysql`, `bigquery`,
  `tsql`, `oracle`, `snowflake`, `redshift`, `clickhouse`, `duckdb`, `sqlite`,
  `trino`, `presto`, `spark`, `databricks`.
- Do NOT import or depend on navigator-auth.
- No async needed — this is a pure synchronous mapping.

### References in Codebase
- `parrot/tools/databasequery/sources/__init__.py` — `normalize_driver` + `_DRIVER_ALIASES`

---

## Acceptance Criteria

- [ ] `driver_to_dialect("pg")` returns `"postgres"`
- [ ] `driver_to_dialect("postgresql")` returns `"postgres"` (via `normalize_driver`)
- [ ] `driver_to_dialect("bq")` returns `"bigquery"` (via `normalize_driver`)
- [ ] `driver_to_dialect("mssql")` returns `"tsql"`
- [ ] `driver_to_dialect("unknown_driver")` returns `None`
- [ ] All tests pass: `pytest tests/auth/test_driver_dialect_map.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/sources/dialects.py`

---

## Test Specification

```python
# tests/auth/test_driver_dialect_map.py
import pytest
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect


class TestDriverToDialect:
    @pytest.mark.parametrize("driver,expected", [
        ("pg", "postgres"),
        ("postgres", "postgres"),
        ("postgresql", "postgres"),
        ("mysql", "mysql"),
        ("mariadb", "mysql"),
        ("bigquery", "bigquery"),
        ("bq", "bigquery"),
        ("mssql", "tsql"),
        ("sqlserver", "tsql"),
        ("oracle", "oracle"),
        ("snowflake", "snowflake"),
        ("redshift", "redshift"),
        ("clickhouse", "clickhouse"),
        ("duckdb", "duckdb"),
        ("sqlite", "sqlite"),
        ("trino", "trino"),
        ("presto", "presto"),
        ("spark", "spark"),
        ("databricks", "databricks"),
    ])
    def test_known_drivers(self, driver, expected):
        assert driver_to_dialect(driver) == expected

    def test_unknown_driver_returns_none(self):
        assert driver_to_dialect("unknown_db_xyz") is None

    def test_case_insensitive(self):
        assert driver_to_dialect("BIGQUERY") == "bigquery"
        assert driver_to_dialect("Pg") == "postgres"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` for full context
2. **Check dependencies** — this task has none; start immediately
3. **Verify the Codebase Contract** — confirm `normalize_driver` still exists at the listed location
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1490-driver-dialect-map.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-08
**Notes**: Implemented `_DRIVER_DIALECT_MAP` with 14 canonical driver to dialect entries. `driver_to_dialect()` delegates normalisation to `normalize_driver()`. All 21 parametrised tests pass.

**Deviations from spec**: none
