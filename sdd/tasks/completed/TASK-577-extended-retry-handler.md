# TASK-577: Extended RetryHandler — Generalized for Non-SQL Databases

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-569
**Assigned-to**: unassigned

---

## Context

Implements spec Module 10. The current `SQLRetryHandler` is tightly coupled to SQLAlchemy (`sqlalchemy.text`) and SQL-specific error patterns. This task generalizes it by creating a `RetryHandler` base class that any toolkit can subclass, while keeping `SQLRetryHandler` as the SQL-specific implementation.

---

## Scope

- Refactor `retries.py`:
  - Extract `RetryHandler` base class from `SQLRetryHandler`:
    - `__init__(toolkit, config)` — accepts a toolkit reference instead of agent
    - `_is_retryable_error(error) -> bool` — base implementation checks `config.retry_on_errors`
    - `async retry_query(query, error, attempt) -> Optional[str]` — returns corrected query or None
  - `SQLRetryHandler(RetryHandler)` — SQL-specific: `_get_sample_data_for_error()`, `_extract_table_column_from_error()`
  - Add `FluxRetryHandler(RetryHandler)` stub — InfluxDB-specific error patterns (empty implementation for now)
  - Add `DSLRetryHandler(RetryHandler)` stub — Elasticsearch-specific (empty implementation for now)
- Generalize `QueryRetryConfig`:
  - Add optional `database_type: str` field to select appropriate handler
- Write unit tests

**NOT in scope**: Full retry logic for non-SQL databases (just stubs), agent integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/retries.py` | MODIFY | Extract RetryHandler base, keep SQLRetryHandler, add stubs |
| `tests/unit/test_retry_handler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.retries import QueryRetryConfig   # retries.py:6
from parrot.bots.database.retries import SQLRetryHandler     # retries.py:31
```

### Existing Signatures to Use
```python
# parrot/bots/database/retries.py:6
class QueryRetryConfig:
    def __init__(self, max_retries=3, retry_on_errors=None, sample_data_on_error=True, max_sample_rows=3):

# parrot/bots/database/retries.py:31
class SQLRetryHandler:
    def __init__(self, agent, config=None):            # line 34
    def _is_retryable_error(self, error) -> bool:      # line 39
    async def _get_sample_data_for_error(self, schema_name, table_name, column_name) -> str:  # line 50
    def _extract_table_column_from_error(self, sql_query, error) -> Tuple[Optional[str], Optional[str]]:  # line 74
```

### Does NOT Exist
- ~~`RetryHandler`~~ — base class does not exist yet (this task creates it)
- ~~`FluxRetryHandler`~~ — does not exist yet
- ~~`DSLRetryHandler`~~ — does not exist yet
- ~~`QueryRetryConfig.database_type`~~ — field does not exist yet

---

## Acceptance Criteria

- [ ] `RetryHandler` base class exists with `_is_retryable_error()` and `retry_query()`
- [ ] `SQLRetryHandler` inherits from `RetryHandler` and preserves existing behavior
- [ ] `SQLRetryHandler.__init__` accepts toolkit (not agent) — signature change
- [ ] `FluxRetryHandler` and `DSLRetryHandler` stubs exist
- [ ] Existing `QueryRetryConfig` backward compatible
- [ ] All tests pass: `pytest tests/unit/test_retry_handler.py -v`

---

## Test Specification

```python
import pytest
from parrot.bots.database.retries import (
    RetryHandler, SQLRetryHandler, QueryRetryConfig
)


class TestRetryHandler:
    def test_base_retryable_error(self):
        config = QueryRetryConfig(retry_on_errors=["ProgrammingError"])
        handler = RetryHandler(toolkit=None, config=config)
        class FakeError(Exception): pass
        assert not handler._is_retryable_error(FakeError("unknown"))

    def test_sql_retryable_error(self):
        config = QueryRetryConfig()
        handler = SQLRetryHandler(toolkit=None, config=config)
        err = Exception("column does not exist")
        assert handler._is_retryable_error(err)

    def test_sql_non_retryable(self):
        config = QueryRetryConfig()
        handler = SQLRetryHandler(toolkit=None, config=config)
        err = Exception("connection refused")
        assert not handler._is_retryable_error(err)
```

---

## Agent Instructions

When you pick up this task:

1. **Read existing `retries.py`** carefully — refactor, don't rewrite from scratch
2. **Preserve backward compatibility** of `QueryRetryConfig`
3. **Change `SQLRetryHandler.__init__` signature** from `agent` to `toolkit` parameter
4. **Implement**, test, move to completed, update index

---

## Completion Note

*(Agent fills this in when done)*
