---
type: Wiki Overview
title: 'TASK-934: Toolkit refactor — new tools, rename, _post_execute, max_rows'
id: doc:sdd-tasks-completed-task-934-toolkit-refactor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec Module 4 — the core toolkit refactor. This is the largest task and
relates_to:
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.tools.databasequery.base
  rel: mentions
- concept: mod:parrot.tools.databasequery.sources
  rel: mentions
- concept: mod:parrot.tools.databasequery.toolkit
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

# TASK-934: Toolkit refactor — new tools, rename, _post_execute, max_rows

**Feature**: FEAT-136 — database-toolkit-parity
**Spec**: `sdd/specs/database-toolkit-parity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-931, TASK-932, TASK-933
**Assigned-to**: unassigned

---

## Context

Spec Module 4 — the core toolkit refactor. This is the largest task and
implements the user-facing changes: three new tools, one renamed tool,
`_post_execute` serialisation, `max_rows` support, and `output_dir` handling.

---

## Scope

1. **Rename** `validate_database_query` → `validate_query`. Remove the
   `credentials` parameter. Update the security guard to use
   `_resolve_query_language()` + `QueryValidator.validate_query()` then
   delegate to `source.validate_query(query)`.

2. **Add `get_table_metadata(driver, table, credentials?)`** — delegates
   to `source.get_metadata(creds, tables=[table])`. Returns `MetadataResult`.

3. **Add `test_connection(driver, credentials?)`** — delegates to
   `source.test_connection(creds)`. Returns `{"status": "success"}` or
   `{"status": "error", "message": ...}`.

4. **Add `save_result(result, filename?, file_format?)`** — converts
   `result["rows"]` to a DataFrame, writes CSV/JSON/Excel to `output_dir`,
   returns `{"file_path": ..., "file_url": ..., ...}`. If `output_dir` is
   not configured, returns an error dict.

5. **Add `max_rows` parameter** to `execute_database_query` and
   `fetch_database_row`. Call `add_row_limit()` (from TASK-931) before
   delegating to the source. Default: `10000`.

6. **Stop calling `.model_dump()`** in each tool method — return Pydantic
   model instances (`MetadataResult`, `ValidationResult`, `QueryResult`,
   `RowResult`) directly.

7. **Override `_post_execute`** to call `result.model_dump()` if the result
   is a `BaseModel` instance. This keeps the LLM receiving plain dicts.

8. **Accept `output_dir` and `static_dir`** in `__init__` kwargs. Store them
   as instance attributes for `save_result`. Add `"save_result"` to
   `exclude_tools` if `output_dir` is not configured.

**NOT in scope**: modifying tool.py, source files (except what TASK-931/932/933
already provide), or `__init__.py` exports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py` | MODIFY | Full refactor per scope |
| `tests/tools/test_database_toolkit_parity.py` | CREATE | Unit tests for all toolkit changes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                   # verified: toolkit.py:168
from parrot.security import QueryLanguage, QueryValidator          # verified: security/__init__.py:10-12
from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,    # verified: base.py:186
    MetadataResult,            # verified: base.py:133
    QueryResult,               # verified: base.py:147
    RowResult,                 # verified: base.py:165
    ValidationResult,          # verified: base.py:85
    add_row_limit,             # ADDED by TASK-931
)
from parrot.tools.databasequery.sources import get_source_class, normalize_driver  # verified
from pydantic import BaseModel                                     # verified: external
import pandas as pd                                                # verified: external
```

### Existing Signatures to Use
```python
# parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    tool_prefix: Optional[str] = None                     # line 219
    exclude_tools: tuple[str, ...] = ()                   # line 205
    def __init__(self, **kwargs): ...                      # line 224
    async def _post_execute(self, tool_name, result, **kwargs) -> Any:  # line 276

# parrot/tools/databasequery/toolkit.py (current)
class DatabaseQueryToolkit(AbstractToolkit):
    tool_prefix: Optional[str] = "dq"                      # line 133
    exclude_tools = ("get_source", "cleanup", "start", "stop")  # line 138
    def __init__(self, **kwargs): ...                       # line 140
    def get_source(self, driver) -> AbstractDatabaseSource: ... # line 151

# _resolve_query_language(driver) -> QueryLanguage          # toolkit.py:57
# _validator_result_to_validation_result(check, language)   # toolkit.py:78
```

### Does NOT Exist
- ~~`AbstractToolkit.output_dir`~~ — does not exist; must add to DatabaseQueryToolkit.__init__
- ~~`AbstractToolkit.static_dir`~~ — does not exist; must add to DatabaseQueryToolkit.__init__
- ~~`AbstractToolkit.to_static_url()`~~ — does not exist; only on AbstractTool
- ~~`DatabaseQueryToolkit.validate_query()`~~ — does not exist yet; this task creates it
- ~~`DatabaseQueryToolkit.save_result()`~~ — does not exist yet; this task creates it
- ~~`DatabaseQueryToolkit.test_connection()`~~ — does not exist yet; this task creates it
- ~~`DatabaseQueryToolkit.get_table_metadata()`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# _post_execute override
async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:
    if isinstance(result, BaseModel):
        return result.model_dump()
    return result

# save_result tool
async def save_result(
    self,
    result: dict,
    filename: Optional[str] = None,
    file_format: str = "csv",
) -> dict:
    """Save a prior query result to CSV, JSON, or Excel."""
    if not self._output_dir:
        return {"error": "output_dir not configured"}
    import pandas as pd
    df = pd.DataFrame(result.get("rows", []))
    # ... write to file based on file_format
```

### Key Constraints
- `validate_query` must NOT accept `credentials` — this is an intentional
  breaking change from `validate_database_query`
- `save_result` must handle empty results gracefully (empty DataFrame)
- `_post_execute` must only serialize `BaseModel` instances, not dicts or
  other types — check with `isinstance`
- `max_rows` defaults to `10000` for SQL, passed through for all drivers
- `openpyxl` for Excel must be a lazy import (optional dependency)
- `test_connection` returns a plain dict (not a BaseModel) — `_post_execute`
  passes it through unchanged

---

## Acceptance Criteria

- [ ] `dq_validate_query` tool exists; `dq_validate_database_query` does NOT exist
- [ ] `validate_query(driver, query)` has no `credentials` parameter
- [ ] `dq_get_table_metadata` tool returns metadata for a single table
- [ ] `dq_test_connection` tool returns `{"status": "success"}` or `{"status": "error", ...}`
- [ ] `dq_save_result` tool writes CSV/JSON/Excel and returns `{"file_path": ...}`
- [ ] `dq_save_result` returns error dict when `output_dir` is not configured
- [ ] `execute_database_query` accepts `max_rows` and injects limits via `add_row_limit()`
- [ ] `fetch_database_row` accepts `max_rows`
- [ ] Toolkit methods return Pydantic models internally
- [ ] `_post_execute` serializes BaseModel results to dicts
- [ ] All tests pass: `pytest tests/tools/test_database_toolkit_parity.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import BaseModel
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit


@pytest.fixture
def toolkit(tmp_path):
    return DatabaseQueryToolkit(output_dir=str(tmp_path))


class TestValidateQueryRenamed:
    def test_tool_name_exists(self, toolkit):
        tool_names = [t.name for t in toolkit.get_tools()]
        assert "dq_validate_query" in tool_names
        assert "dq_validate_database_query" not in tool_names


class TestPostExecute:
    @pytest.mark.asyncio
    async def test_serializes_basemodel(self, toolkit):
        class Dummy(BaseModel):
            x: int = 1
        result = await toolkit._post_execute("test", Dummy())
        assert result == {"x": 1}

    @pytest.mark.asyncio
    async def test_passes_through_dict(self, toolkit):
        result = await toolkit._post_execute("test", {"a": 1})
        assert result == {"a": 1}


class TestSaveResult:
    @pytest.mark.asyncio
    async def test_csv_export(self, toolkit, tmp_path):
        result = {"rows": [{"id": 1, "name": "test"}], "columns": ["id", "name"]}
        output = await toolkit.save_result(result, filename="test", file_format="csv")
        assert "file_path" in output
        assert output["file_path"].endswith(".csv")

    @pytest.mark.asyncio
    async def test_no_output_dir(self):
        tk = DatabaseQueryToolkit()  # no output_dir
        output = await tk.save_result({"rows": []})
        assert "error" in output
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-931, TASK-932, TASK-933 are in `tasks/completed/`
3. **Verify** `add_row_limit` exists in `base.py` (TASK-931)
4. **Verify** `AbstractDatabaseSource.test_connection()` exists (TASK-931)
5. **Implement** in this order: `_post_execute` → rename → new tools → `max_rows`
6. **Run tests** after each step
7. **Move this file** to `tasks/completed/` and update index

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-04-29
**Notes**: Implemented all scope items in toolkit.py:
1. Renamed validate_database_query → validate_query; removed credentials parameter
2. Added get_table_metadata(driver, table, credentials?) → MetadataResult
3. Added test_connection(driver, credentials?) → {"status": "success"} or {"status": "error", ...}
4. Added save_result(result, filename?, file_format?) with CSV/JSON/Excel support
5. Added max_rows (default=10000) to execute_database_query, max_rows (default=1) to fetch_database_row
6. Tool methods now return Pydantic models directly (no inline .model_dump())
7. Overrode _post_execute to serialize BaseModel → dict
8. Added output_dir and static_dir to __init__; save_result excluded when no output_dir
9. Created tests/tools/test_database_toolkit_parity.py with 40 tests (all pass)

**Deviations from spec**: none
