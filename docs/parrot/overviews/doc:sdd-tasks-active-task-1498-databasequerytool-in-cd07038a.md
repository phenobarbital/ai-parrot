---
type: Wiki Overview
title: 'TASK-1498: DatabaseQueryTool Integration'
id: doc:sdd-tasks-active-task-1498-databasequerytool-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: here), remote execution (Module 10).
relates_to:
- concept: mod:parrot.auth.dataplane_guard
  rel: mentions
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.tools.databasequery.tool
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.authorizing
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.sql
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

# TASK-1498: DatabaseQueryTool Integration

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1496
**Assigned-to**: unassigned

---

## Context

> Spec Module 9. `DatabaseQueryTool._execute(driver, query)` is a direct path
> to any database — constrained today only by an LLM system prompt. This task
> wires it through the same `AuthorizingDataSource`/resolver enforcement chain
> used by `DatasetManager`, closing bypass vector B3. Also gates
> `test_connection` and `get_supported_drivers` on `driver:connect`.

---

## Scope

- Modify `DatabaseQueryTool._execute()` to construct a temporary
  `SQLQuerySource` from its `driver`+`query` args, wrap it via
  `AuthorizingDataSource`, and use the authorized/RLS-injected result.
- Add `dataplane_guard: Optional[DataPlanePolicyGuard] = None` parameter to
  `DatabaseQueryTool.__init__`.
- Gate `test_connection(driver)` on `driver:connect` when guard is present.
- Gate `get_supported_drivers()` to filter by `driver:connect` when guard is present.
- Write unit tests verifying the enforcement chain.

**NOT in scope**: DatasetManager wiring (TASK-1497), opaque sources (irrelevant
here), remote execution (Module 10).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/databasequery/tool.py` | MODIFY | Add guard param, wrap `_execute` path, gate `test_connection`/`get_supported_drivers` |
| `tests/auth/test_databasequerytool_authz.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# DatabaseQueryTool
from parrot.tools.databasequery.tool import DatabaseQueryTool
# verified: packages/ai-parrot/src/parrot/tools/databasequery/tool.py

# Source for wrapping
from parrot.tools.dataset_manager.sources.sql import SQLQuerySource  # line 26
from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource  # TASK-1496
from parrot.auth.dataplane_guard import DataPlanePolicyGuard  # TASK-1495
```

### Existing Signatures to Use
```python
# parrot/tools/databasequery/tool.py:245
class DatabaseQueryTool(AbstractToolkit):
    def __init__(self, **kwargs):                     # line 245
        super().__init__(**kwargs)
        self.default_credentials = {}                 # line 248

    async def _execute(                               # line 535
        self,
        driver: str,
        query: str,
        credentials: Optional[Dict[str, Any]] = None,
        dsn: Optional[str] = None,
        output_format: str = "pandas",
        query_timeout: int = 300,
        max_rows: int = 10000,
        **kwargs,
    ) -> Union[pd.DataFrame, str]: ...

    # test_connection and get_supported_drivers — verify exact signatures by reading file
```

### Does NOT Exist
- ~~`DatabaseQueryTool.dataplane_guard`~~ — does not exist yet (this task adds it)
- ~~`DatabaseQueryTool._make_source()`~~ — does not exist; create inline wrapping
- ~~`DatabaseQueryTool._pctx_var`~~ — the ContextVar is on DatasetManager's module, not here; will need to import or use a pctx_provider pattern

---

## Implementation Notes

### Pattern to Follow

```python
# In DatabaseQueryTool.__init__:
def __init__(self, **kwargs):
    self._dataplane_guard = kwargs.pop('dataplane_guard', None)
    super().__init__(**kwargs)
    self.default_credentials = {}

# In DatabaseQueryTool._execute, before the actual query execution:
async def _execute(self, driver, query, **kwargs):
    if self._dataplane_guard is not None:
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        source = SQLQuerySource(sql=query, driver=driver)
        authorized = AuthorizingDataSource(
            inner=source,
            guard=self._dataplane_guard,
            pctx_provider=self._get_pctx,  # need to wire this
        )
        # The fetch() call runs the enforcement chain.
        # If denied, AuthorizationRequired propagates.
        # If RLS applied, we get the rewritten query.
        # ... or just call authorize_source directly and get rewritten SQL
    # proceed with existing execution logic
```

### Key Constraints
- `DatabaseQueryTool` does NOT have access to `_pctx_var` from DatasetManager's
  module. The `pctx_provider` must be wired differently:
  - Option A: Import `_pctx_var` from `parrot.tools.dataset_manager.tool`.
  - Option B: Use `getattr(self, '_current_pctx', None)` which is set by
    `ToolkitTool._execute` (toolkit.py:176) before tool execution.
  - **Prefer Option B** — it matches how DatasetManager accesses the context.
- The guard call must happen BEFORE the actual database query, not after.
- `test_connection(driver)` should call `guard.can_connect_driver(ctx, driver)`
  — if denied, raise `AuthorizationRequired`.
- `get_supported_drivers()` should filter the driver list by `can_connect_driver`
  when a guard and context are available.
- If no guard configured → existing behavior unchanged (fail-open).

### References in Codebase
- `parrot/tools/databasequery/tool.py` — main file to modify
- `parrot/tools/toolkit.py:176` — `_current_pctx` injection point
- `parrot/tools/dataset_manager/sources/authorizing.py` (TASK-1496)

---

## Acceptance Criteria

- [ ] `DatabaseQueryTool.__init__` accepts `dataplane_guard=` parameter
- [ ] AC3: `_execute(driver, query)` with guarded driver/table → denied for
  unauthorized user (same decision as `fetch_dataset`)
- [ ] AC3: `_execute(driver, query)` allowed for authorized user, with RLS applied
- [ ] `test_connection(driver)` gated on `driver:connect` when guard present
- [ ] `get_supported_drivers()` filters by `driver:connect` when guard present
- [ ] No guard configured → existing behavior unchanged
- [ ] AC12: DML/DDL in query → `ReadOnlyViolation` (from resolver, TASK-1491)
- [ ] All tests pass: `pytest tests/auth/test_databasequerytool_authz.py -v`
- [ ] No linting errors: `ruff check parrot/tools/databasequery/tool.py`

---

## Test Specification

```python
# tests/auth/test_databasequerytool_authz.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired


@pytest.fixture
def mock_guard():
    guard = MagicMock()
    guard.is_sensitive_driver.return_value = False
    guard.authorize_source = AsyncMock()
    guard.rls_predicates = AsyncMock(return_value=[])
    guard.can_connect_driver = AsyncMock(return_value=True)
    return guard


@pytest.fixture
def pctx():
    return PermissionContext(
        session=UserSession(username="test", groups=["Finance"], programs=[])
    )


class TestDatabaseQueryToolAuthz:
    @pytest.mark.asyncio
    async def test_guarded_query_denied(self, mock_guard, pctx):
        """AC3: guarded driver+query denied for unauthorized user."""
        mock_guard.authorize_source = AsyncMock(
            side_effect=AuthorizationRequired("denied")
        )
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool(dataplane_guard=mock_guard)
        # Mock _current_pctx
        tool._current_pctx = pctx
        with pytest.raises(AuthorizationRequired):
            await tool._execute(driver="pg", query="SELECT * FROM finance.salaries")

    @pytest.mark.asyncio
    async def test_no_guard_open(self):
        """No guard → existing behavior."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        assert tool._dataplane_guard is None

    @pytest.mark.asyncio
    async def test_test_connection_denied(self, mock_guard, pctx):
        """test_connection gated on driver:connect."""
        mock_guard.can_connect_driver = AsyncMock(return_value=False)
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool(dataplane_guard=mock_guard)
        tool._current_pctx = pctx
        with pytest.raises(AuthorizationRequired):
            await tool.test_connection(driver="bigquery_finance")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` §5.6 for database_query wiring
2. **Check dependencies** — verify TASK-1496 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ `parrot/tools/databasequery/tool.py` to confirm
   `_execute`, `test_connection`, `get_supported_drivers` signatures
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1498-databasequerytool-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —

**Deviations from spec**: none
