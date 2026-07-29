---
type: Wiki Overview
title: 'TASK-1046: DatasetManager policy integration'
id: doc:sdd-tasks-completed-task-1046-datasetmanager-policy-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: '1. Add `policy_guard: Optional["DatasetPolicyGuard"] = None` constructor
  kwarg; store as `self._policy_guard`.'
relates_to:
- concept: mod:parrot.auth.dataset_guard
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

# TASK-1046: DatasetManager policy integration

**Feature**: FEAT-151 — PBAC-Driven DatasetManager Policy Enforcement
**Spec**: `sdd/specs/pbac-datasetmanager-policy.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1044
**Assigned-to**: unassigned

---

## Context

> This task implements Module 3 of the FEAT-151 spec: wiring `DatasetPolicyGuard`
> (created in TASK-1044) into `DatasetManager`. This is the largest task in the
> feature — it touches the main 2k+ line `DatasetManager` class at six enforcement
> points (constructor, `get_tools_filtered`, `list_datasets`/`list_available`/`get_active`,
> `get_metadata`, `fetch_dataset`, and `_pre_execute`).
>
> The guiding principle is drop-silent semantics: the LLM and caller must be unable
> to distinguish "dataset/column never existed" from "dataset/column hidden by policy".
> When `self._policy_guard is None`, every enforcement path short-circuits to "allow"
> — existing behaviour unchanged (opt-in backwards compat).

---

## Scope

- Modify `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`:
  1. Add `policy_guard: Optional["DatasetPolicyGuard"] = None` constructor kwarg; store as `self._policy_guard`.
  2. Override `get_tools_filtered()`: call `super().get_tools_filtered(...)`, then post-filter using `policy_guard.filter_datasets()` to remove tools whose dataset name is denied.
  3. Wrap `list_datasets()`: after building the result list from `self._datasets`, call `policy_guard.filter_datasets()` and remove entries for denied datasets.
  4. `list_available()` already delegates to `list_datasets()` — no separate change needed (verify this).
  5. Wrap `get_active()`: filter the returned list through `policy_guard.filter_datasets()`.
  6. Wrap `get_metadata()`: after `entry.to_info()`, call `policy_guard.filter_columns()` and rebuild `DatasetInfo` with trimmed `columns` and `column_types` in lockstep.
  7. Wrap `fetch_dataset()`: after materialisation, call `policy_guard.filter_columns()` and `df.drop(columns=denied)` before returning.
  8. Implement `_pre_execute()`: read `kwargs.get("_permission_context")`, determine the dataset name from the tool call, call `policy_guard.can_read_dataset()`. If denied, raise or return an appropriate signal so the caller receives a forbidden result.
  9. When `self._policy_guard is None`, every step above short-circuits: existing behaviour unchanged.
- Write unit tests in `packages/ai-parrot/tests/tools/dataset_manager/test_policy_filtering.py`.

**NOT in scope**: creating `DatasetPolicyGuard` (TASK-1044), modifying `setup_pbac` (TASK-1045), sample YAML files or integration tests (TASK-1047).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add `policy_guard` kwarg, override 6 enforcement touchpoints |
| `packages/ai-parrot/tests/tools/dataset_manager/test_policy_filtering.py` | CREATE | Unit tests for all filtering paths |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
# DatasetManager and its data models
from parrot.tools.dataset_manager.tool import (
    DatasetManager,          # packages/.../dataset_manager/tool.py:477
    DatasetEntry,            # packages/.../dataset_manager/tool.py:100
    DatasetInfo,             # packages/.../dataset_manager/tool.py:36
)

# The guard class (created by TASK-1044)
from parrot.auth.dataset_guard import DatasetPolicyGuard

# Identity context (already used by toolkit execution)
from parrot.auth.permission import PermissionContext, UserSession

# Toolkit base
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool
# packages/ai-parrot/src/parrot/tools/toolkit.py:168, :18

# Tool result for forbidden responses
from parrot.tools.abstract import AbstractTool, ToolResult
# packages/ai-parrot/src/parrot/tools/abstract.py:375
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:477
class DatasetManager(AbstractToolkit):
    tool_prefix: str = "dataset"                                     # line 497
    exclude_tools = ("setup", "add_dataset", "list_available")       # line 498

    def __init__(                                                    # line 500
        self,
        df_prefix: str = "df",
        generate_guide: bool = True,
        include_summary_stats: bool = False,
        auto_detect_types: bool = True,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._datasets: Dict[str, DatasetEntry] = {}                 # line 509

    def _resolve_name(self, identifier: str) -> str: ...             # line 576

    async def list_datasets(self) -> List[Dict[str, Any]]: ...       # line 2433
        # Iterates self._datasets, calls entry.to_info(alias=...).model_dump()
        # Returns list of dicts

    async def list_available(self) -> List[Dict[str, Any]]: ...      # line 2506
        # Alias: return await self.list_datasets()

    async def get_active(self) -> List[str]: ...                     # line 2510
        # return [name for name, entry in self._datasets.items() if entry.is_active]

    async def get_metadata(                                          # line 2553
        self, name: str,
        include_eda: bool = False,
        include_samples: bool = True,
        include_column_stats: bool = False,
        include_metrics_guide: bool = False,
        column: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    async def fetch_dataset(                                         # line 2868
        self, name: str,
        sql: Optional[str] = None,
        conditions: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]: ...

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:100
class DatasetEntry:
    name: str                                                        # line 135
    is_active: bool = True                                           # line 121
    async def materialize(self, force: bool = False, **params) -> pd.DataFrame: ...  # line 225
    def to_info(self, alias: Optional[str] = None) -> DatasetInfo: ...               # line 382

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:36
class DatasetInfo(BaseModel):
    name: str
    columns: List[str]
    column_types: Dict[str, str]
    shape: Tuple[int, int]
    is_active: bool
    source_type: str
    usage_do: List[str]                                              # line 90
    usage_dont: List[str]                                            # line 94

# packages/ai-parrot/src/parrot/tools/toolkit.py:382
class AbstractToolkit:
    async def get_tools_filtered(
        self,
        permission_context: "PermissionContext",
        resolver: "AbstractPermissionResolver",
    ) -> List[AbstractTool]:                                         # line 382
        all_tools = self.get_tools()                                 # line 399
        return await resolver.filter_tools(permission_context, all_tools)  # line 400

# Toolkit lifecycle hooks:
# packages/ai-parrot/src/parrot/tools/toolkit.py:261
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        # kwargs includes _permission_context (injected at toolkit.py:155)

# ToolkitTool permission context injection:
# packages/ai-parrot/src/parrot/tools/toolkit.py:151-156
    # pctx = getattr(self, "_current_pctx", None)
    # hook_kwargs["_permission_context"] = pctx
    # await toolkit._pre_execute(self.name, **hook_kwargs)

# AbstractTool forbidden result pattern:
# packages/ai-parrot/src/parrot/tools/abstract.py:402-412
    # return ToolResult(status='forbidden', ...)
```

### Does NOT Exist

- ~~`DatasetManager.policy_guard`~~ — attribute does NOT exist yet; this task adds it.
- ~~`DatasetManager.get_tools_filtered()`~~ — override does NOT exist yet; this task adds it.
- ~~`DatasetManager._pre_execute()`~~ — override does NOT exist yet; this task adds it.
- ~~`AbstractToolkit.filter_tools_by_policy`~~ — no such method; use `get_tools_filtered()`.
- ~~`DatasetEntry.policy_resource`~~ / ~~`DatasetEntry.allowed_users`~~ — not real attributes.
- ~~`ToolkitTool._method_name`~~ — verified at `toolkit.py:376`: `tool._method_name = name`. This IS the attribute that maps a tool back to its toolkit method name. Use it to identify which tools correspond to dataset operations.
- ~~Per-row filtering / WHERE-clause injection~~ — out of scope for v1.
- ~~`DatasetInfo.redacted_columns`~~ / ~~`DatasetInfo.permission_denied`~~ — no such fields. Drop-silent means NO trace of redaction.

---

## Implementation Notes

### Pattern to Follow

```python
# Constructor addition:
def __init__(self, ..., policy_guard=None, **kwargs):
    super().__init__(**kwargs)
    ...
    self._policy_guard = policy_guard  # Optional[DatasetPolicyGuard]

# Helper to get current permission context (used by wrapped methods):
def _get_current_pctx(self) -> Optional[PermissionContext]:
    return getattr(self, "_current_pctx", None)

# get_tools_filtered override pattern:
async def get_tools_filtered(self, permission_context, resolver):
    tools = await super().get_tools_filtered(permission_context, resolver)
    if not self._policy_guard:
        return tools
    allowed_datasets = await self._policy_guard.filter_datasets(
        permission_context, list(self._datasets.keys())
    )
    return [t for t in tools if self._tool_dataset_name(t) in allowed_datasets
            or self._tool_dataset_name(t) is None]

# Column filtering helper (used by get_metadata and fetch_dataset):
async def _filter_dataset_info_columns(self, pctx, info: DatasetInfo) -> DatasetInfo:
    if not self._policy_guard or not pctx:
        return info
    allowed = await self._policy_guard.filter_columns(pctx, info.name, info.columns)
    allowed_set = set(allowed)
    return info.model_copy(update={
        "columns": allowed,
        "column_types": {k: v for k, v in info.column_types.items() if k in allowed_set},
    })
```

### Key Constraints

- **Drop-silent is absolute**: no `permission_denied` field, no debug-mode toggle, no `_redacted` shadow attribute. The LLM cannot distinguish "column never existed" from "column hidden by policy".
- **When `self._policy_guard is None`**: every enforcement path short-circuits. Backwards compat guaranteed.
- **Column filtering in lockstep**: when trimming `DatasetInfo`, ALWAYS trim both `columns` and `column_types` together. Never one without the other.
- **`_pre_execute` Layer-2 check**: read `kwargs.get("_permission_context")`, determine dataset name from `tool_name` or first positional kwarg. If `can_read_dataset()` returns `False`, the method should raise or return early. Determine the exact signal by checking how `AbstractTool.execute` handles forbidden at `abstract.py:402-412`.
- **No new sync I/O**: all filtering happens in already-async paths. No blocking.
- **Preserve `_resolve_name` semantics**: always resolve aliases before checking policies.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:477-518` — DatasetManager constructor.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:382-400` — `get_tools_filtered()` base implementation.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:151-156` — ToolkitTool `_permission_context` injection.
- `packages/ai-parrot/src/parrot/tools/abstract.py:402-412` — ToolResult forbidden pattern.
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:2433-2504` — `list_datasets()` implementation.
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:2553-2579` — `get_metadata()` start.
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:2868-2917` — `fetch_dataset()` start.

---

## Acceptance Criteria

- [ ] `DatasetManager(policy_guard=None)` is behaviourally identical to the pre-feature baseline.
- [ ] `DatasetManager(policy_guard=guard)` honours dataset-level deny: target dataset absent from `get_tools_filtered`, `list_datasets`, `list_available`, `get_active`.
- [ ] `_pre_execute` returns forbidden if `can_read_dataset()` returns False (Layer-2 defence-in-depth).
- [ ] Column-level deny: target columns absent from `DatasetInfo.columns`, `DatasetInfo.column_types`, and the `fetch_dataset` DataFrame columns. Omission is silent.
- [ ] Column filtering trims `columns` and `column_types` in lockstep.
- [ ] `list_available()` delegates to wrapped `list_datasets()` (verify, don't duplicate).
- [ ] When `policy_guard is None`, no calls are made to any guard method.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/dataset_manager/test_policy_filtering.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/dataset_manager/test_policy_filtering.py
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.dataset_guard import DatasetPolicyGuard
from parrot.tools.dataset_manager.tool import DatasetManager, DatasetEntry, DatasetInfo


@pytest.fixture
def mock_guard():
    """Mock DatasetPolicyGuard with configurable allow/deny."""
    guard = MagicMock(spec=DatasetPolicyGuard)
    guard.filter_datasets = AsyncMock()
    guard.filter_columns = AsyncMock()
    guard.can_read_dataset = AsyncMock()
    return guard


@pytest.fixture
def pctx_jleon():
    return PermissionContext(
        session=UserSession(
            user_id="jleon@trocglobal.com",
            tenant_id="troc",
            roles=frozenset(),
            metadata={},
        )
    )


class TestDatasetManagerNoGuard:
    async def test_no_guard_unchanged(self):
        """DatasetManager() without policy_guard behaves identically to baseline."""
        ...


class TestDatasetManagerWithGuard:
    async def test_get_tools_filtered_drops_denied(self, mock_guard, pctx_jleon):
        """Mock guard denies 'financial_data'; get_tools_filtered excludes its tools."""
        ...

    async def test_list_available_drops_denied(self, mock_guard, pctx_jleon):
        """Mock guard denies 'financial_data'; list_available excludes it."""
        ...

    async def test_get_active_drops_denied(self, mock_guard, pctx_jleon):
        """Mock guard denies 'financial_data'; get_active excludes it."""
        ...

    async def test_get_metadata_drops_columns(self, mock_guard, pctx_jleon):
        """Mock guard denies ['profit_margin']; get_metadata excludes from DatasetInfo."""
        ...

    async def test_fetch_dataset_drops_columns(self, mock_guard, pctx_jleon):
        """Mock guard denies ['profit_margin']; fetch_dataset drops from DataFrame."""
        ...

    async def test_pre_execute_denies_forbidden(self, mock_guard, pctx_jleon):
        """Mock guard denies dataset; _pre_execute signals forbidden."""
        ...

    async def test_drop_silent_no_error_signal(self, mock_guard, pctx_jleon):
        """No 'permission_denied' field, no warning, no marker in output."""
        ...

    async def test_column_types_trimmed_in_lockstep(self, mock_guard, pctx_jleon):
        """columns and column_types are filtered together."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pbac-datasetmanager-policy.spec.md` for full context
2. **Check dependencies** — verify TASK-1044 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` around lines 477-518, 2433-2508, 2553-2580, 2868-2920
   - Confirm method signatures match what's listed above
   - Confirm `DatasetPolicyGuard` exists (from TASK-1044)
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/pbac-datasetmanager-policy.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1046-datasetmanager-policy-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Code)
**Date**: 2026-05-07
**Notes**: Added PBAC enforcement to DatasetManager at all six points specified:
constructor kwarg, get_tools_filtered, _pre_execute, list_datasets, get_active,
get_metadata (both loaded and unloaded paths), and fetch_dataset. Fixed a bug in
_pre_execute: AuthorizationRequired was called with wrong kwargs (`user_id`/`reason`)
— corrected to positional `message` arg per exceptions.py contract. Also added
`AbstractPermissionResolver` to the TYPE_CHECKING block (ruff F821) and removed
an unused import from get_tools_filtered. 27 unit tests in 4 test classes, all passing.

**Deviations from spec**: none
