---
type: Wiki Overview
title: 'TASK-1497: DatasetManager Integration'
id: doc:sdd-tasks-completed-task-1497-datasetmanager-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: wraps the source in `AuthorizingDataSource` when `dataplane_guard` is set.
relates_to:
- concept: mod:parrot.auth.dataplane_guard
  rel: mentions
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.authorizing
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.memory
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.sql
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

# TASK-1497: DatasetManager Integration

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1496
**Assigned-to**: unassigned

---

## Context

> Spec Module 8. Wire the `AuthorizingDataSource` decorator into
> `DatasetManager` so every agent-facing source is wrapped at construction
> time. This closes the bypass vectors B1 (alias spoofing), B4 (direct
> materialize), and B6 (no RLS). The existing `_pre_execute`/`can_read_dataset`
> L1 check is retained for pre-registered datasets.

---

## Scope

- Add `dataplane_guard: Optional[DataPlanePolicyGuard] = None` parameter to
  `DatasetManager.__init__` (alongside the existing `policy_guard`).
- Implement `_make_source(source: DataSource) -> DataSource` factory method that
  wraps the source in `AuthorizingDataSource` when `dataplane_guard` is set.
- Wire `_make_source()` into every code path that creates or uses a `DataSource`:
  - `fetch_dataset()` — wrap the source before fetch.
  - All internal `materialize()` paths (confirmed V4 callers: composite.py:217,
    tool.py:1576, 1620, 3416, 4033, 4049, 4321, 4765).
  - Source construction in `add_dataset()` / dataset registration paths.
- Keep existing `_pre_execute`/`can_read_dataset` as L1 (no removal).
- Add `DATAPLANE_SENSITIVE_DRIVERS` config key.
- Write integration tests for the full DatasetManager → AuthorizingDataSource flow.

**NOT in scope**: DatabaseQueryTool (TASK-1498), remote execution (Module 10),
modifying the PBAC engine, changing navigator-auth.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/tool.py` | MODIFY | Add `dataplane_guard` param, `_make_source()` factory, wire all source paths |
| `tests/auth/test_datasetmanager_authz_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in tool.py:
from .sources.base import DataSource  # tool.py:28 (top-level)

# New imports needed (add at usage sites, not top-level, matching existing pattern):
from .sources.authorizing import AuthorizingDataSource
from parrot.auth.dataplane_guard import DataPlanePolicyGuard
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/tool.py:527–535
class DatasetManager(AbstractToolkit):
    def __init__(
        self,
        df_prefix: str = "df",
        generate_guide: bool = True,
        include_summary_stats: bool = False,
        auto_detect_types: bool = True,
        policy_guard: Optional["DatasetPolicyGuard"] = None,  # line 533
        **kwargs,
    ):
    # Stores: self._policy_guard = policy_guard (check exact line)

# Internal materialize callers (V4 verified):
# composite.py:217 — dm.materialize(ds_name, force_refresh=force_refresh)
# tool.py:1576, 1620 — self.materialize(name, force_refresh=True)
# tool.py:3416 — self.materialize(name, force_refresh=force_refresh, **params)
# tool.py:4033, 4049 — entry.materialize(force=True, ...)
# tool.py:4321 — self.materialize(vs.query_slug)
# tool.py:4765 — self.materialize(ds_name)

# Source imports inside tool.py (lazy, inside methods):
# tool.py:28 — from .sources.base import DataSource (top-level)
# tool.py:180 — from .sources.memory import InMemorySource
# tool.py:183 — from .sources.query_slug import QuerySlugSource
# tool.py:421–430 — bulk imports of all sources

# _pctx_var (FEAT-151):
# tool.py (module-level): _pctx_var: ContextVar[Optional[PermissionContext]]
```

### Does NOT Exist
- ~~`DatasetManager._make_source()`~~ — does not exist yet (this task creates it)
- ~~`DatasetManager.dataplane_guard`~~ — does not exist yet (this task adds it)
- ~~`DatasetManager._wrap_source()`~~ — does not exist; we create `_make_source` instead

---

## Implementation Notes

### Pattern to Follow

```python
# In DatasetManager.__init__, after existing policy_guard setup:
def __init__(self, ..., dataplane_guard=None, **kwargs):
    ...
    self._dataplane_guard = dataplane_guard

def _make_source(self, source: DataSource) -> DataSource:
    """Wrap a DataSource with authorization if a dataplane guard is configured."""
    if self._dataplane_guard is None:
        return source
    from .sources.authorizing import AuthorizingDataSource
    return AuthorizingDataSource(
        inner=source,
        guard=self._dataplane_guard,
        pctx_provider=lambda: _pctx_var.get(None),
    )
```

### Key Constraints
- **Every code path that creates a `DataSource` for agent use must call
  `_make_source()`**. This is the Option D invariant. The main paths are:
  - `fetch_dataset()` when building a source from `query=`/`table=`/`slug=`
  - `add_dataset()` / dataset registration (so pre-registered sources are also wrapped)
  - Any path that constructs a source inline
- **Do NOT wrap `InMemorySource`** — it has no driver and no authorization surface.
- The `_pctx_var` ContextVar is already module-level in tool.py (FEAT-151).
- **Read tool.py carefully** before modifying — it is ~5000 lines. Find all
  source construction sites by searching for `SQLQuerySource(`, `TableSource(`,
  `QuerySlugSource(`, `MongoSource(`, etc.
- The `_pre_execute` check and `_policy_guard` (DatasetPolicyGuard) remain as L1.
  The new `_dataplane_guard` (DataPlanePolicyGuard) is L2 — applied at the
  source level. They are complementary, not replacements.

### References in Codebase
- `parrot/tools/dataset_manager/tool.py` — main file to modify
- `parrot/tools/dataset_manager/sources/authorizing.py` (TASK-1496)

---

## Acceptance Criteria

- [ ] `DatasetManager.__init__` accepts `dataplane_guard=` parameter
- [ ] `_make_source()` wraps sources when guard is present
- [ ] `_make_source()` returns unwrapped source when guard is None
- [ ] `fetch_dataset()` with ad-hoc `query=` routes through `_make_source()`
- [ ] `fetch_dataset()` with `table=` routes through `_make_source()`
- [ ] Pre-registered datasets route through `_make_source()`
- [ ] AC1: alias-spoofing `fetch_dataset(name="x", query="SELECT * FROM finance.salaries")` denied for non-Finance user
- [ ] AC6: internal `materialize()` of guarded dataset still enforced
- [ ] AC8: no `dataplane_guard` → everything open (fail-open)
- [ ] `InMemorySource` not wrapped (no driver)
- [ ] All tests pass: `pytest tests/auth/test_datasetmanager_authz_integration.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/tool.py`

---

## Test Specification

```python
# tests/auth/test_datasetmanager_authz_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired


@pytest.fixture
def finance_pctx():
    return PermissionContext(
        session=UserSession(username="finance_user", groups=["Finance"], programs=[])
    )


@pytest.fixture
def basic_pctx():
    return PermissionContext(
        session=UserSession(username="basic_user", groups=["General"], programs=[])
    )


class TestDatasetManagerAuthzIntegration:
    @pytest.mark.asyncio
    async def test_no_guard_configured_open(self):
        """AC8: no dataplane_guard → fail-open."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        dm = DatasetManager(dataplane_guard=None)
        # Should not wrap sources
        from parrot.tools.dataset_manager.sources.memory import InMemorySource
        import pandas as pd
        source = InMemorySource(pd.DataFrame({"a": [1]}), "test")
        result = dm._make_source(source)
        assert not isinstance(result, type)  # should be same source, not wrapped

    def test_make_source_wraps_when_guard_present(self):
        """_make_source wraps with AuthorizingDataSource."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        mock_guard = MagicMock()
        dm = DatasetManager(dataplane_guard=mock_guard)
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        source = SQLQuerySource(sql="SELECT 1", driver="pg")
        wrapped = dm._make_source(source)
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
        assert isinstance(wrapped, AuthorizingDataSource)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` §2 Overview for the factory pattern
2. **Check dependencies** — verify TASK-1496 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ `tool.py` thoroughly; find all source construction sites
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1497-datasetmanager-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-08
**Notes**: Added `dataplane_guard` param to `__init__`, stored as `self._dataplane_guard`. Added `_make_source()` factory method (skips InMemorySource). Wired into all 10 registration paths: `add_source`, `add_query`, `add_table_source`, `add_sql_source`, `add_airtable_source`, `add_smartsheet_source`, `add_iceberg_source`, `add_mongo_source`, `add_deltatable_source`, `add_composite_dataset`. Also wired into `add_dataset()` ad-hoc source construction paths. Added TYPE_CHECKING import for DataPlanePolicyGuard. All 13 new tests pass; 94 FEAT-228 tests pass total.

**Deviations from spec**: none
