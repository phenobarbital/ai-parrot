# TASK-1047: Sample YAML policies and integration tests

**Feature**: FEAT-151 — PBAC-Driven DatasetManager Policy Enforcement
**Spec**: `sdd/specs/pbac-datasetmanager-policy.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1044, TASK-1045, TASK-1046
**Assigned-to**: unassigned

---

## Context

> This task implements Modules 4 and 5 (integration portion) of the FEAT-151 spec.
> It creates the sample YAML policy file for documentation/fixture purposes and writes
> end-to-end integration tests that wire all three prior tasks together:
> `DatasetPolicyGuard` + extended `setup_pbac` + `DatasetManager` with guard.
>
> The integration tests exercise the full chain: YAML → PolicyEvaluator → DatasetPolicyGuard
> → DatasetManager filtering — for both dataset-level and column-level deny scenarios.

---

## Scope

- Create `policies/datasets/sample.yml` with dataset-level and column-level policy examples.
- Write integration tests in `packages/ai-parrot/tests/integration/test_dataset_policy_integration.py`.
- Integration tests must:
  1. Boot a stub aiohttp app, call `setup_pbac(app, policy_dir=tmp)` with YAML fixtures.
  2. Construct `DatasetManager(policy_guard=DatasetPolicyGuard(evaluator))` with test datasets.
  3. Test dataset-level deny: denied dataset absent from `get_tools_filtered`, `list_available`, `get_metadata`, `fetch_dataset`.
  4. Test column-level deny: denied columns absent from `DatasetInfo.columns`, `DatasetInfo.column_types`, and `DataFrame.columns`.
  5. Test admin user: full visibility (no restrictions).
  6. Test no-policy no-enforcement: empty policies dir → all datasets/columns visible.
  7. Test backwards compat: `DatasetManager(policy_guard=None)` unchanged.

**NOT in scope**: modifying any implementation code (TASK-1044/1045/1046 already shipped). No new classes or production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `policies/datasets/sample.yml` | CREATE | Example dataset and column policy YAML |
| `packages/ai-parrot/tests/integration/test_dataset_policy_integration.py` | CREATE | End-to-end integration tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
# Auth components (all created/modified by prior tasks)
from parrot.auth.dataset_guard import DatasetPolicyGuard
from parrot.auth.pbac import setup_pbac
from parrot.auth.permission import PermissionContext, UserSession

# DatasetManager
from parrot.tools.dataset_manager.tool import DatasetManager, DatasetEntry, DatasetInfo

# Test utilities
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import MagicMock
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/pbac.py:35
def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]":

# packages/ai-parrot/src/parrot/auth/dataset_guard.py (created by TASK-1044)
class DatasetPolicyGuard:
    def __init__(self, evaluator: "PolicyEvaluator",
                 logger: Optional[logging.Logger] = None) -> None: ...
    async def filter_datasets(self, context: PermissionContext,
                              dataset_names: list[str]) -> set[str]: ...
    async def filter_columns(self, context: PermissionContext,
                             dataset_name: str, columns: list[str]) -> list[str]: ...
    async def can_read_dataset(self, context: PermissionContext,
                               dataset_name: str) -> bool: ...

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:477 (modified by TASK-1046)
class DatasetManager(AbstractToolkit):
    def __init__(self, ..., policy_guard: Optional[DatasetPolicyGuard] = None, **kwargs): ...
```

### YAML Policy Schema

```yaml
# navigator-auth YAML policy format (from brainstorm + spec §2):
- name: <rule-name>
  effect: DENY | ALLOW
  subjects:
    users: ["user@example.com"]
    roles: ["role-name"]
  resources:
    - type: DATASET
      name: <dataset-name>                    # for dataset-level rules
    - type: DATASET
      name: "<dataset>:<column>"              # for column-level rules
  actions: ["dataset:read" | "dataset:column:read"]
```

### Does NOT Exist

- ~~`ResourceType.DATASET`~~ in current navigator-auth — the cross-repo PR MUST have landed before these integration tests can run against the real evaluator. If not yet merged, tests must mock the evaluator and are tagged `@pytest.mark.skipif(...)` or similar.
- ~~`policies/datasets/`~~ — directory does NOT exist on disk; this task creates the sample file.
- ~~`DatasetPolicyGuard` subclass of `PBACPermissionResolver`~~ — they are siblings.

---

## Implementation Notes

### Sample YAML Policy

```yaml
# policies/datasets/sample.yml
# Example: hide the 'financial_data' dataset from user jleon@trocglobal.com
- name: deny-financial-data-jleon
  effect: DENY
  subjects:
    users: ["jleon@trocglobal.com"]
  resources:
    - type: DATASET
      name: financial_data
  actions: ["dataset:read"]

# Example: hide 'profit_margin' column inside 'sales' for tier-1 reps
- name: deny-sales-profit-margin-tier1
  effect: DENY
  subjects:
    roles: ["tier-1-rep"]
  resources:
    - type: DATASET
      name: "sales:profit_margin"
  actions: ["dataset:column:read"]
```

### Key Constraints

- Integration tests should use a real `PolicyEvaluator` (from `navigator-auth`) where possible.
- If `navigator-auth` with `ResourceType.DATASET` is not available, fall back to mocked evaluator and document the skip condition.
- Tests must verify drop-silent: no `permission_denied` field, no warning text, no error marker in any output dict or DataFrame.
- Each test must assert all three column touchpoints in lockstep: `DatasetInfo.columns`, `DatasetInfo.column_types`, `DataFrame.columns`.

### References in Codebase

- `packages/ai-parrot/src/parrot/auth/pbac.py` — `setup_pbac` with datasets extension (TASK-1045).
- `packages/ai-parrot/src/parrot/auth/dataset_guard.py` — `DatasetPolicyGuard` (TASK-1044).
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — `DatasetManager` with policy integration (TASK-1046).

---

## Acceptance Criteria

- [ ] `policies/datasets/sample.yml` exists and contains valid YAML with at least one dataset-level and one column-level policy example.
- [ ] Integration test: end-to-end dataset deny via YAML — denied dataset absent from all four query paths.
- [ ] Integration test: end-to-end column deny via YAML — denied column absent from `DatasetInfo.columns`, `column_types`, and `DataFrame.columns`.
- [ ] Integration test: admin user sees everything (no restrictions).
- [ ] Integration test: no policies loaded → all datasets and columns visible (opt-in semantics).
- [ ] Integration test: `DatasetManager(policy_guard=None)` regression — bit-identical to pre-feature baseline.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integration/test_dataset_policy_integration.py -v`
- [ ] Sample YAML validates against the navigator-auth policy schema (no parse errors).

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/test_dataset_policy_integration.py
import pytest
import pandas as pd
from pathlib import Path
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.dataset_guard import DatasetPolicyGuard
from parrot.tools.dataset_manager.tool import DatasetManager


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


@pytest.fixture
def pctx_admin():
    return PermissionContext(
        session=UserSession(
            user_id="admin@trocglobal.com",
            tenant_id="troc",
            roles=frozenset({"admin"}),
            metadata={},
        )
    )


@pytest.fixture
def pctx_tier1_rep():
    return PermissionContext(
        session=UserSession(
            user_id="rep@trocglobal.com",
            tenant_id="troc",
            roles=frozenset({"tier-1-rep"}),
            metadata={},
        )
    )


class TestEndToEndDatasetPolicy:
    @pytest.mark.asyncio
    async def test_dataset_deny_via_yaml(self, pctx_jleon):
        """Denied dataset absent from get_tools_filtered, list_available,
        get_metadata, fetch_dataset."""
        ...

    @pytest.mark.asyncio
    async def test_column_deny_via_yaml(self, pctx_tier1_rep):
        """Denied columns absent from DatasetInfo and DataFrame."""
        ...

    @pytest.mark.asyncio
    async def test_admin_full_visibility(self, pctx_admin):
        """Admin user sees all datasets and all columns."""
        ...

    @pytest.mark.asyncio
    async def test_no_policy_no_enforcement(self):
        """Empty policies dir → all visible."""
        ...

    @pytest.mark.asyncio
    async def test_no_guard_regression(self):
        """DatasetManager(policy_guard=None) is unchanged."""
        ...

    @pytest.mark.asyncio
    async def test_cache_ttl_window(self):
        """Policy change reflected after 30s cache expiry but not before."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pbac-datasetmanager-policy.spec.md` for full context
2. **Check dependencies** — verify TASK-1044, TASK-1045, TASK-1046 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `DatasetPolicyGuard` exists and has the expected interface
   - Confirm `setup_pbac` loads `policies/datasets/` (TASK-1045)
   - Confirm `DatasetManager` accepts `policy_guard` kwarg (TASK-1046)
4. **Update status** in `sdd/tasks/index/pbac-datasetmanager-policy.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1047-sample-policies-integration-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
