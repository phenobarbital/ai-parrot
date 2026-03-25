# TASK-428: Source Registry & Driver Alias Resolution

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-427
**Assigned-to**: unassigned

---

## Context

The source registry is the lookup mechanism that maps driver strings to their
`AbstractDatabaseSource` implementations. Sources self-register via a decorator,
and the registry supports lazy imports to avoid pulling in heavy driver dependencies
at startup. This also includes the `normalize_driver()` alias resolution function
ported from `DatabaseQueryTool.DriverInfo`.

Implements **Module 2** from the spec.

---

## Scope

- Create `parrot/tools/database/sources/` package.
- Implement `_SOURCE_REGISTRY` dict in `sources/__init__.py`.
- Implement `@register_source(driver)` decorator.
- Implement `get_source_class(driver)` lookup with lazy imports.
- Implement `normalize_driver(driver)` that maps all aliases to canonical names:
  - `postgresql`, `postgres` → `pg`
  - `mariadb` → `mysql`
  - `bq` → `bigquery`
  - `sqlserver` → `mssql`
  - `influxdb` → `influx`
  - `mongodb` → `mongo`
  - `elasticsearch`, `opensearch` → `elastic`

**NOT in scope**: Actual source implementations (those are TASK-429 through TASK-434).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/sources/__init__.py` | CREATE | Registry + normalize_driver |

---

## Implementation Notes

### Pattern to Follow
```python
# sources/__init__.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.tools.database.base import AbstractDatabaseSource

_SOURCE_REGISTRY: dict[str, type[AbstractDatabaseSource]] = {}

_DRIVER_ALIASES: dict[str, str] = {
    "postgres": "pg", "postgresql": "pg",
    "mariadb": "mysql",
    "bq": "bigquery",
    "sqlserver": "mssql",
    "influxdb": "influx",
    "mongodb": "mongo",
    "elasticsearch": "elastic", "opensearch": "elastic",
}

def normalize_driver(driver: str) -> str:
    """Map driver aliases to canonical names."""
    d = driver.lower().strip()
    return _DRIVER_ALIASES.get(d, d)

def register_source(driver: str):
    """Decorator that registers a source class under the given driver string."""
    def decorator(cls):
        _SOURCE_REGISTRY[driver] = cls
        return cls
    return decorator

def get_source_class(driver: str) -> type[AbstractDatabaseSource]:
    canonical = normalize_driver(driver)
    if canonical not in _SOURCE_REGISTRY:
        _ensure_sources_loaded()
        if canonical not in _SOURCE_REGISTRY:
            raise ValueError(
                f"No DatabaseSource registered for driver '{driver}'. "
                f"Available: {list(_SOURCE_REGISTRY.keys())}"
            )
    return _SOURCE_REGISTRY[canonical]
```

### Key Constraints
- Lazy imports: source modules are imported inside `_ensure_sources_loaded()` only
  when `get_source_class` is called for the first time
- `normalize_driver()` must be idempotent: `normalize_driver("pg")` → `"pg"`
- Registry must raise `ValueError` with helpful message for unknown drivers

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` — `DriverInfo.normalize_driver()`
- `parrot/tools/registry.py` — existing tool registry pattern

---

## Acceptance Criteria

- [ ] `@register_source("pg")` decorator registers class in `_SOURCE_REGISTRY`
- [ ] `get_source_class("pg")` returns the registered class
- [ ] `get_source_class("unknown")` raises `ValueError`
- [ ] `normalize_driver("postgresql")` → `"pg"`
- [ ] `normalize_driver("bq")` → `"bigquery"`
- [ ] `normalize_driver("sqlserver")` → `"mssql"`
- [ ] `normalize_driver("opensearch")` → `"elastic"`
- [ ] All aliases from the spec's Driver Alias Resolution table work
- [ ] Import works: `from parrot.tools.database.sources import get_source_class, register_source`

---

## Test Specification

```python
# tests/tools/database/test_registry.py
import pytest
from parrot.tools.database.sources import (
    register_source, get_source_class, normalize_driver,
    _SOURCE_REGISTRY,
)
from parrot.tools.database.base import AbstractDatabaseSource


class TestNormalizeDriver:
    @pytest.mark.parametrize("alias,expected", [
        ("pg", "pg"),
        ("postgres", "pg"),
        ("postgresql", "pg"),
        ("mysql", "mysql"),
        ("mariadb", "mysql"),
        ("bigquery", "bigquery"),
        ("bq", "bigquery"),
        ("mssql", "mssql"),
        ("sqlserver", "mssql"),
        ("influx", "influx"),
        ("influxdb", "influx"),
        ("mongo", "mongo"),
        ("mongodb", "mongo"),
        ("elastic", "elastic"),
        ("elasticsearch", "elastic"),
        ("opensearch", "elastic"),
    ])
    def test_alias_resolution(self, alias, expected):
        assert normalize_driver(alias) == expected


class TestRegistry:
    def test_register_and_retrieve(self):
        @register_source("_test_driver")
        class FakeSource(AbstractDatabaseSource):
            driver = "_test_driver"
            async def get_default_credentials(self): return {}
            async def get_metadata(self, creds, tables=None): ...
            async def query(self, creds, sql, params=None): ...
            async def query_row(self, creds, sql, params=None): ...

        cls = get_source_class("_test_driver")
        assert cls is FakeSource
        # cleanup
        _SOURCE_REGISTRY.pop("_test_driver", None)

    def test_unknown_driver_raises(self):
        with pytest.raises(ValueError, match="No DatabaseSource registered"):
            get_source_class("nonexistent_driver_xyz")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — TASK-427 must be in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-428-dbtoolkit-source-registry.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
