# TASK-216: SQLQuerySource

**Feature**: DatasetManager Lazy Data Sources (FEAT-030)
**Spec**: `sdd/specs/datasetmanager-datasources.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-213
**Assigned-to**: claude-sonnet-4-6

---

## Context

> New source type for user-provided SQL with `{param}` interpolation. Validated by Pydantic
> at fetch time. Uses AsyncDB driver for execution. Credential resolution uses the existing
> helper from `parrot/tools/databasequery.py`.

---

## Scope

Implement `SQLQuerySource` at `parrot/tools/dataset_manager/sources/sql.py`.

### Constructor

```python
class SQLQuerySource(DataSource):
    def __init__(
        self,
        sql: str,
        driver: str,
        dsn: Optional[str] = None,       # resolved via databasequery.py if None
        cache_ttl: int = 3600,
    ) -> None: ...
```

### `cache_key`

`f"sql:{self.driver}:{hashlib.md5(self.sql.encode()).hexdigest()[:8]}"`

### `fetch(**params)`

1. Extract all `{param_name}` placeholders from `self.sql` using regex.
2. Validate that all placeholders are present in `params` — raise `ValueError` with a descriptive message if any are missing.
3. Escape each value to prevent SQL injection (use parameterized approach or whitelist-safe escaping — see notes).
4. Interpolate: `final_sql = self.sql.format(**escaped_params)`.
5. Execute via AsyncDB driver (`self.driver`, `self.dsn`).
6. Return result as `pd.DataFrame`.

### `prefetch_schema()`

Returns `{}` (schema only available after first fetch).

### `describe()`

```
"SQL query via {driver}: {sql[:80]}{'...' if len(sql) > 80 else ''}"
```

### Credential resolution

```python
from parrot.tools.databasequery import get_default_credentials

if dsn is None:
    dsn = get_default_credentials(driver)
```

### SQL injection escaping

For string interpolation, values must be quoted/escaped. Use the following approach:
- Numeric types (int, float): cast to string directly.
- String types: wrap in single quotes, escape internal single quotes by doubling them (`'`→`''`).
- Dates / datetimes: cast to ISO string, then treat as string.
- DO NOT use Python's `str.format()` with raw user input — always escape first.

Export `SQLQuerySource` from `parrot/tools/dataset_manager/sources/__init__.py`.

**NOT in scope**: Changes to `DatasetManager.add_sql_source()` (TASK-219).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/sql.py` | CREATE | SQLQuerySource implementation |
| `parrot/tools/dataset_manager/sources/__init__.py` | MODIFY | Export SQLQuerySource |

---

## Implementation Notes

### AsyncDB execution pattern

Look at how existing code in `parrot/tools/databasequery.py` opens and executes AsyncDB connections. Follow the same pattern for `SQLQuerySource.fetch()`.

### Pydantic validation approach

Rather than a separate Pydantic model, validate inline at fetch time:

```python
import re

def _extract_params(self) -> List[str]:
    return re.findall(r'\{(\w+)\}', self.sql)

async def fetch(self, **params) -> pd.DataFrame:
    required = self._extract_params()
    missing = [p for p in required if p not in params]
    if missing:
        raise ValueError(f"SQLQuerySource missing required params: {missing}")
    ...
```

### References in Codebase
- `parrot/tools/databasequery.py` — `get_default_credentials()` and AsyncDB execution pattern
- `parrot/tools/dataset_manager/tool.py` — any existing SQL execution logic

---

## Acceptance Criteria

- [ ] `SQLQuerySource` at `parrot/tools/dataset_manager/sources/sql.py`
- [ ] `{param}` placeholders validated at `fetch()` time; missing params raise `ValueError`
- [ ] String values are escaped (single quotes doubled) before interpolation
- [ ] `cache_key` format: `sql:{driver}:{md5[:8]}`
- [ ] `prefetch_schema()` returns `{}`
- [ ] `dsn=None` resolves via `get_default_credentials(driver)` from `databasequery.py`
- [ ] `SQLQuerySource` exported from `sources/__init__.py`
- [ ] Unit tests pass: `pytest tests/tools/test_datasources.py::TestSQLQuerySource -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-datasources.spec.md` for full context
2. **Check dependencies** — verify TASK-213 is in `sdd/tasks/completed/`
3. **Read** `parrot/tools/databasequery.py` to understand credential resolution and AsyncDB execution
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-216-sql-query-source.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**: Implemented `SQLQuerySource` in `parrot/tools/dataset_manager/sources/sql.py`.
Added standalone `get_default_credentials(driver)` helper to `parrot/tools/databasequery.py`.
Exported `SQLQuerySource` from `sources/__init__.py`. Added `TestSQLQuerySource` with 28 tests
covering cache_key, describe, prefetch_schema, _escape_value (int/float/str/date/datetime/bool),
fetch validation, fetch execution, and dsn resolution. All 58 tests in test_datasources.py pass.

**Deviations from spec**: `AsyncDB` imported at module level (not inside `fetch()`) to allow
test patching via `patch("...sql.AsyncDB")`. No other deviations.
