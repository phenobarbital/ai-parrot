---
type: feature
base_branch: dev
---

# Feature Specification: PBAC-Driven DatasetManager Policy Enforcement

**Feature ID**: FEAT-151
**Date**: 2026-05-07
**Author**: Jesus Lara
**Status**: draft
**Target version**: TBD (pinned to `navigator-auth` release adding `ResourceType.DATASET`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`DatasetManager` (`parrot.tools.dataset_manager.tool.DatasetManager`, an `AbstractToolkit`) exposes datasets to LLM-driven agents through async tools such as `list_available()`, `get_metadata()`, `fetch_dataset()`, `activate_datasets()`. Today the catalog has only a global `is_active` flag per `DatasetEntry`: every authenticated user that interacts with the agent sees every active dataset, regardless of identity or role.

This is a data-leak vector. Concrete failure case: user `jleon@trocglobal.com` opens a chat with a finance-aware agent and the LLM is exposed to a `financial_data` dataset that — by HR/compliance policy — that user is not entitled to query. The LLM may list it, describe its schema, or fetch its rows.

`navigator-auth` already provides a complete ABAC/PBAC stack (`PolicyEvaluator`, `PolicyDecisionPoint`, YAML-based policies, `Guardian` middleware), and `ai-parrot` already integrates it for **tool-level** enforcement (`PBACPermissionResolver` at `parrot/auth/resolver.py:247`, wired through `AbstractTool.execute()` and `AbstractToolkit.get_tools_filtered()`). What is missing is a **dataset-level** resource model: a way for an admin to author a YAML policy that says "user `jleon@trocglobal.com` cannot see resource `dataset:financial_data` (action `dataset:read`)" and have `DatasetManager` honour that decision both in the catalog the LLM sees and in the data it gets back.

The feature also delivers **column-level** filtering: an admin can hide specific sensitive columns inside an otherwise-visible dataset (e.g. drop `profit_margin` from `sales` for tier-1 reps but keep it for managers).

### Goals

- Add a first-class **dataset resource type** in the PBAC stack (`ResourceType.DATASET`) — coordinated cross-repo PR in `navigator-auth`.
- Author dataset and column policies as YAML in `policies/datasets/*.yml`, loaded by the same `PolicyEvaluator` that already serves `policies/agents/*.yml`.
- Enforce policy at two layers: (1) tool-list visibility via `DatasetManager.get_tools_filtered()`, and (2) schema/metadata + materialised data via dataset/column drop-silent semantics.
- Identify a dataset by `DatasetEntry.name`; identify a column by composite resource name `<dataset>:<column>`.
- Identity flows from the existing `PermissionContext` already carried through `bot.ask`, `ToolManager.execute_tool`, and the toolkit `_pre_execute` hook — no new identity mechanism.
- Fail-closed on policy evaluation errors (deny on exception); allow only when `navigator-auth` itself is not installed (mirrors existing `PBACPermissionResolver` behaviour for backwards compat).
- Backwards compatible: a `DatasetManager` instantiated **without** a `policy_guard` argument keeps its current unrestricted behaviour. Datasets without matching policies remain visible to all users (opt-in).

### Non-Goals (explicitly out of scope)

- **Row-level filtering** (e.g. WHERE injection per user). Brainstorm Round 2 limited v1 granularity to dataset + columns.
- **Action granularity** (read vs. fetch vs. metadata as separate actions). v1 uses `dataset:read` for catalog/listing/fetch and `dataset:column:read` for column-level. Sub-actions deferred.
- **Hot-reload of policy YAML** beyond the evaluator's existing `cache_ttl_seconds=30` window. v1 accepts the 30-second worst-case staleness.
- **OAuth 3LO / per-dataset credential resolution**. Out of scope (the existing `_pre_execute` hook is used only for policy enforcement, not credential negotiation).
- **Default-restrictive (deny-by-omission) backwards-compat mode**. Brainstorm Option B (TOOL-namespace workaround) and Option C (subclass fork) were rejected — see `sdd/proposals/pbac-datasetmanager-policy.brainstorm.md` Recommendation.
- **Audit pipeline / SIEM ingestion / Prometheus metrics**. Logging follows `PBACPermissionResolver` precedent (WARNING line); structured telemetry is a follow-up.
- **Dataset rename validator**. If a dataset is renamed, policies referencing the old name silently no-op. Mitigation deferred (see §8).

---

## 2. Architectural Design

### Overview

A new helper class `DatasetPolicyGuard` (in `parrot/auth/dataset_guard.py`) wraps a shared `navigator-auth` `PolicyEvaluator` and exposes three async methods tailored to dataset semantics: `filter_datasets`, `filter_columns`, `can_read_dataset`. It mirrors `PBACPermissionResolver` (`parrot/auth/resolver.py:247`) in shape, error handling, and lazy-import discipline — but operates against `ResourceType.DATASET` instead of `ResourceType.TOOL`.

`setup_pbac()` (`parrot/auth/pbac.py:35`) is extended to also load `policies/datasets/*.yml` into the same `PolicyEvaluator` instance, alongside the existing `policies/agents/*.yml` glob (`pbac.py:131–149`). One evaluator, one cache, one audit trail.

`DatasetManager` accepts an optional `policy_guard: Optional[DatasetPolicyGuard] = None` constructor kwarg. When `None` (the default), every enforcement path short-circuits to "allow" — this is the opt-in backwards-compat hatch. When set, `DatasetManager`:

- Overrides `get_tools_filtered()` to post-filter dataset-named tools after the base resolver has done the standard tool-level pass.
- Wraps `list_datasets()` / `list_available()` / `get_active()` to drop forbidden datasets from listings.
- Wraps `to_info()` / `get_metadata()` to drop forbidden columns from `DatasetInfo.columns` and `DatasetInfo.column_types` (drop-silent — the LLM never learns the columns existed).
- Wraps `fetch_dataset()` to drop forbidden columns from the materialised `DataFrame` before returning to the caller.
- Implements a `_pre_execute()` hook that reads `_current_pctx` (the `PermissionContext` already injected by `ToolkitTool._execute()` at `parrot/tools/toolkit.py:153–156`) and uses it to call the guard.

User identity already travels through the request pipeline via the existing `PermissionContext` plumbing — no new contextvar, no new identity dataclass.

### Component Diagram

```
                         policies/datasets/*.yml
                                    │
                                    ▼
  setup_pbac(app)  ───────►  PolicyEvaluator  ◄────────── Guardian (handler middleware,
       │                          │                                  unchanged)
       │                          │
       ▼                          ▼
  DatasetPolicyGuard  ─── wraps ── PolicyEvaluator
       │                          (resource_type=ResourceType.DATASET,
       │                           action="dataset:read" | "dataset:column:read")
       │
       │ injected via constructor kwarg
       ▼
  DatasetManager(policy_guard=...)
       │
       ├── get_tools_filtered  ──►  drop dataset-tools the user cannot see
       ├── list_available      ──►  drop forbidden dataset names
       ├── get_metadata        ──►  drop forbidden columns from DatasetInfo
       ├── fetch_dataset       ──►  drop forbidden columns from DataFrame
       └── _pre_execute        ──►  Layer 2 deny if dataset is forbidden
                                    (defence-in-depth; mirrors AbstractTool.execute)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/auth/pbac.py::setup_pbac()` | extends | Add a `policies/datasets/` glob alongside the existing `policies/agents/` glob (`pbac.py:131–149` is the precedent block to copy). Same `PolicyEvaluator`. |
| `parrot/auth/resolver.py::PBACPermissionResolver` | references (template only) | `DatasetPolicyGuard` mirrors its lazy-import pattern (`resolver.py:312–317`), `to_eval_context` bridge (`resolver.py:319`), and WARNING log format (`resolver.py:331–337`). Does NOT subclass it — different interface. |
| `parrot/auth/permission.py::PermissionContext`, `to_eval_context()` | uses | Identity bridge from ai-parrot to navigator-auth's `EvalContext` (`permission.py:160`). Unchanged. |
| `parrot/tools/toolkit.py::AbstractToolkit.get_tools_filtered()` | extends | `DatasetManager` overrides this method; it first delegates to `super().get_tools_filtered(...)`, then post-filters dataset-tools using the guard. |
| `parrot/tools/toolkit.py::ToolkitTool._execute()` (`:127`) and `_pre_execute` hook (`:261`) | uses | The `_permission_context` injection happens at `:153–156`. `DatasetManager._pre_execute()` reads `self._current_pctx` and consults the guard. |
| `parrot/tools/abstract.py::AbstractTool.execute()` (`:375`) | uses (unchanged) | The Layer-2 PBAC check at `:396` continues to gate `tool:execute`; the new dataset guard is an additional Layer-2 gate inside the toolkit method. Both run; both must allow. |
| `parrot/tools/manager.py::ToolManager.execute_tool()` (`:1126`) | uses (unchanged) | Already injects `_permission_context` and `_resolver` into tool execution at `:1174–1178`. |
| `parrot/tools/dataset_manager/tool.py::DatasetManager` (`:477`) | modifies | New constructor kwarg `policy_guard: Optional[DatasetPolicyGuard] = None`; new overrides at the four listed touchpoints. |
| `parrot/tools/dataset_manager/tool.py::DatasetEntry.to_info()` (`:382`) | wraps | Output is post-filtered to drop forbidden columns. The wrapping is done in the `DatasetManager` method that calls `to_info()`, not inside `DatasetEntry` itself (keeps `DatasetEntry` policy-agnostic). |
| `parrot/tools/dataset_manager/tool.py::DatasetEntry.materialize()` (`:225`) | wraps | Same: post-filter columns inside the `DatasetManager.fetch_dataset` flow, not in `DatasetEntry`. |
| `policies/datasets/` directory | creates | New deployment artifact; sample YAML committed alongside spec implementation. |
| `navigator-auth` (external repo) | extends | Parallel PR adds `ResourceType.DATASET` enum value. **Blocking dependency** for any code import. |

### Data Models

```python
# parrot/auth/dataset_guard.py — NEW

class DatasetPolicyGuard:
    """PBAC enforcement for DatasetManager. Wraps PolicyEvaluator with
    dataset-specific resource type and actions.

    Mirrors PBACPermissionResolver (parrot/auth/resolver.py:247) in shape:
    same lazy-import, same to_eval_context bridge, same WARNING-on-deny,
    same fail-open-on-ImportError.

    Constructor:
        evaluator: shared PolicyEvaluator (same instance Guardian uses)
        logger:    optional; defaults to logging.getLogger(__name__)

    Public async methods:
        filter_datasets(context: PermissionContext,
                        dataset_names: list[str]) -> set[str]
            # Returns the subset the user is allowed to see.
            # action="dataset:read", resource_type=ResourceType.DATASET

        filter_columns(context: PermissionContext,
                       dataset_name: str,
                       columns: list[str]) -> list[str]
            # Returns columns in original order, minus those denied.
            # action="dataset:column:read"
            # resource_names=[f"{dataset_name}:{c}" for c in columns]

        can_read_dataset(context: PermissionContext,
                         dataset_name: str) -> bool
            # Single-resource convenience for the _pre_execute Layer-2 check.
            # action="dataset:read", resource_name=dataset_name

    Failure semantics:
        - ImportError on navigator-auth → return all-allowed (preserves
          backwards compat; matches resolver.py:315–317).
        - Any other exception inside filter/check → log WARNING with
          user_id + dataset_name + reason, return DENY for the affected
          subset (fail-closed).
        - context.session is None or user_id is None → DENY for protected
          resources (fail-closed); datasets without policies remain visible.
    """
```

```python
# parrot/tools/dataset_manager/tool.py — MODIFIED constructor

class DatasetManager(AbstractToolkit):
    tool_prefix = "dataset"  # unchanged (line 497)

    def __init__(
        self,
        # ... all existing kwargs ...
        policy_guard: Optional["DatasetPolicyGuard"] = None,  # NEW
        **kwargs,
    ) -> None:
        # ... existing init body ...
        self._policy_guard = policy_guard  # NEW; None means no enforcement
```

No new Pydantic models. `DatasetInfo` (`dataset_manager/tool.py:36`) is reused unchanged — column filtering trims its `columns` and `column_types` post-construction. `PermissionContext` and `UserSession` (`parrot/auth/permission.py:80`, `:20`) are reused unchanged.

### New Public Interfaces

```python
# parrot/auth/dataset_guard.py
class DatasetPolicyGuard:
    def __init__(self, evaluator: "PolicyEvaluator",
                 logger: Optional[logging.Logger] = None) -> None: ...

    async def filter_datasets(self, context: PermissionContext,
                              dataset_names: list[str]) -> set[str]: ...

    async def filter_columns(self, context: PermissionContext,
                             dataset_name: str,
                             columns: list[str]) -> list[str]: ...

    async def can_read_dataset(self, context: PermissionContext,
                               dataset_name: str) -> bool: ...

# parrot/auth/__init__.py — MODIFIED
from parrot.auth.dataset_guard import DatasetPolicyGuard  # add to public exports

# parrot/tools/dataset_manager/tool.py — MODIFIED
class DatasetManager(AbstractToolkit):
    def __init__(self, ..., policy_guard: Optional[DatasetPolicyGuard] = None,
                 **kwargs) -> None: ...
```

YAML policy schema (sample, `policies/datasets/finance.yml`):

```yaml
# Hide the entire 'financial_data' dataset from one user.
- name: deny-financial-data-jleon
  effect: DENY
  subjects:
    users: ["jleon@trocglobal.com"]
  resources:
    - type: DATASET
      name: financial_data
  actions: ["dataset:read"]

# Hide 'profit_margin' column inside 'sales' from tier-1 reps.
- name: deny-sales-profit-margin-tier1
  effect: DENY
  subjects:
    roles: ["tier-1-rep"]
  resources:
    - type: DATASET
      name: "sales:profit_margin"
  actions: ["dataset:column:read"]
```

The exact YAML key names follow `navigator-auth`'s existing storage schema; the implementation task validates the schema against a real `navigator-auth` test fixture before committing the sample.

---

## 3. Module Breakdown

### Module 1: `DatasetPolicyGuard`

- **Path**: `packages/ai-parrot/src/parrot/auth/dataset_guard.py` (new)
- **Responsibility**: Wrap `PolicyEvaluator` with dataset-specific resource type and actions. Provide three async methods: `filter_datasets`, `filter_columns`, `can_read_dataset`. Mirror `PBACPermissionResolver` lazy-import + WARNING-on-deny pattern. Implement fail-closed semantics on runtime errors and fail-open only on `ImportError` for navigator-auth absence.
- **Depends on**: `parrot.auth.permission.PermissionContext`, `to_eval_context`; `navigator_auth.abac.policies.evaluator.PolicyEvaluator`; `navigator_auth.abac.policies.resources.ResourceType.DATASET` (parallel PR — must land first); `navigator_auth.abac.policies.environment.Environment`.

### Module 2: `setup_pbac` extension for `policies/datasets/`

- **Path**: `packages/ai-parrot/src/parrot/auth/pbac.py` (modify)
- **Responsibility**: After the existing `policies/agents/` block (`pbac.py:131–149`), add a `policies/datasets/` block that loads dataset YAMLs into the same `PolicyEvaluator` instance. Use the same exception handling (warn-and-continue on per-subdir failure). Optionally return a `DatasetPolicyGuard` instance pre-bound to the evaluator (deferred; see §8).
- **Depends on**: Module 1 (`DatasetPolicyGuard`) only if the convenience-return is implemented in v1; otherwise no new dependency.

### Module 3: `DatasetManager` policy integration

- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (modify)
- **Responsibility**:
  1. Add `policy_guard: Optional[DatasetPolicyGuard] = None` constructor kwarg; store on `self._policy_guard`.
  2. Override `get_tools_filtered()`: call `super().get_tools_filtered(...)` first, then apply `policy_guard.filter_datasets(ctx, all_dataset_names)` to drop dataset-named tools whose dataset is denied.
  3. Wrap `list_available()` / `get_active()` / `list_datasets()`: read `self._current_pctx`, call `filter_datasets`, return only allowed names.
  4. Wrap `get_metadata()`: after building the `DatasetInfo` via `entry.to_info()`, call `filter_columns(ctx, name, info.columns)` and rebuild `info` with the trimmed `columns` and `column_types`.
  5. Wrap `fetch_dataset()`: after `entry.materialize(...)` returns the `DataFrame`, call `filter_columns` and `df.drop(columns=denied)` before returning.
  6. Implement `_pre_execute()` to call `policy_guard.can_read_dataset(ctx, name)` for any tool whose first arg is a dataset name; return a `ToolResult(status='forbidden', ...)` analogue if denied. (This is Layer-2 defence-in-depth — Layer-1 already removed the tool from the catalogue.)
  7. When `self._policy_guard is None`, every step above short-circuits: existing behaviour unchanged.
- **Depends on**: Module 1.

### Module 4: Sample policies and `policies/datasets/` directory

- **Path**: `policies/datasets/sample.yml` (new — committed as documentation/example, not loaded in production unless deployed)
- **Responsibility**: Demonstrate dataset-level and column-level deny/allow rules in the canonical YAML schema. Used as the fixture for integration tests.
- **Depends on**: agreement with `navigator-auth` maintainer on the final YAML schema (see §8).

### Module 5: Tests

- **Path**: `packages/ai-parrot/tests/auth/test_dataset_guard.py` (new), `packages/ai-parrot/tests/tools/dataset_manager/test_policy_filtering.py` (new)
- **Responsibility**: Unit-test `DatasetPolicyGuard` (filter, can-read, fail-closed, ImportError fail-open). Integration-test `DatasetManager` with a mocked `PolicyEvaluator` to verify dataset and column drop-silent semantics through `list_available`, `get_metadata`, `fetch_dataset`. Regression-test that `DatasetManager(policy_guard=None)` is bit-identical in behaviour to the pre-feature baseline.
- **Depends on**: Modules 1, 3.

### Module 6: navigator-auth `ResourceType.DATASET` (cross-repo, blocking)

- **Path**: external — `navigator-auth/src/navigator_auth/abac/policies/resources.py` (or wherever `ResourceType` is defined in that repo)
- **Responsibility**: Add the `DATASET` enum value. Ship a minor release. This module is **not** part of this spec's git scope; tracked separately. **Blocking** — Modules 1 and 5 cannot import the enum until it lands.
- **Depends on**: nothing in ai-parrot.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_guard_init_with_evaluator` | 1 | Constructs `DatasetPolicyGuard` with a stub evaluator; verifies attribute storage and default logger. |
| `test_filter_datasets_allows_subset` | 1 | Stub evaluator returns `filter_resources` result with `allowed=["a","c"]` for `["a","b","c"]`; verifies guard returns `{"a","c"}`. |
| `test_filter_datasets_empty_input` | 1 | Empty list short-circuits to empty set without evaluator call. |
| `test_filter_columns_preserves_order` | 1 | Stub returns `allowed=["c1","c3"]` for `["c1","c2","c3"]`; guard returns `["c1","c3"]` (input order, not evaluator order). |
| `test_filter_columns_composite_resource_name` | 1 | Asserts `evaluator.filter_resources` was called with `resource_names=["sales:c1","sales:c2"]` and `action="dataset:column:read"`. |
| `test_can_read_dataset_allows` | 1 | Stub returns `result.allowed=True`; guard returns `True`. |
| `test_can_read_dataset_denies_with_warning` | 1 | Stub returns `result.allowed=False`; guard returns `False` and emits a WARNING log line containing `user_id` and `dataset_name`. |
| `test_guard_fail_open_on_navigator_auth_importerror` | 1 | Patches the lazy import to raise `ImportError`; guard returns "all allowed" (preserves resolver.py:315–317 precedent). |
| `test_guard_fail_closed_on_evaluator_exception` | 1 | Stub evaluator raises `RuntimeError`; guard returns empty/False (DENY) and logs WARNING. |
| `test_guard_fail_closed_on_missing_session` | 1 | `PermissionContext` with `session=None` or `user_id=None` returns DENY for all checked resources. |
| `test_setup_pbac_loads_datasets_subdir` | 2 | Creates a temp `policies/datasets/x.yml`; verifies `setup_pbac` logs that N policies were loaded from the datasets subdir and they are present in the evaluator. |
| `test_setup_pbac_continues_when_datasets_subdir_missing` | 2 | Existing behaviour preserved when `policies/datasets/` does not exist. |
| `test_setup_pbac_warn_on_datasets_yaml_parse_error` | 2 | Malformed YAML in `policies/datasets/` logs a WARNING but does not abort; existing `policies/` and `policies/agents/` still load. |
| `test_dataset_manager_no_guard_unchanged` | 3 | `DatasetManager()` (no `policy_guard`) behaves identically to the baseline: `list_available`, `get_metadata`, `fetch_dataset` return current results. |
| `test_dataset_manager_get_tools_filtered_drops_denied_dataset` | 3 | Mock guard denies `financial_data`; `get_tools_filtered` returns no tool whose name resolves to that dataset. |
| `test_dataset_manager_list_available_drops_denied` | 3 | Mock guard denies `financial_data`; `list_available()` does not include it in the returned list. |
| `test_dataset_manager_get_metadata_drops_columns` | 3 | Mock guard denies columns `[profit_margin]` for dataset `sales`; `get_metadata("sales")` returns `DatasetInfo` whose `columns` and `column_types` exclude `profit_margin`. |
| `test_dataset_manager_fetch_dataset_drops_columns` | 3 | Mock guard denies columns `[profit_margin]`; `fetch_dataset("sales")` returns DataFrame whose `.columns` excludes `profit_margin`. |
| `test_dataset_manager_pre_execute_layer2_denies_forbidden_dataset` | 3 | Mock guard denies `financial_data`; calling `fetch_dataset("financial_data")` returns a forbidden ToolResult (defence-in-depth path). |
| `test_dataset_manager_drop_silent_no_error_signal` | 3 | Confirms the LLM/caller cannot distinguish "column never existed" from "column hidden by policy" — no `permission_denied` field, no warning to caller. |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_dataset_policy_via_yaml` | Boot a stub aiohttp app, call `setup_pbac(app, policy_dir=tmp)` where `tmp/datasets/finance.yml` denies `financial_data` to user X. Construct `DatasetManager(policy_guard=DatasetPolicyGuard(evaluator))` with two datasets. Run `get_tools_filtered`, `list_available`, `get_metadata("financial_data")`, `fetch_dataset("financial_data")` with X's `PermissionContext`. Verify all four exhibit drop-silent denial. Repeat with admin Y; verify Y sees everything. |
| `test_end_to_end_column_policy_via_yaml` | YAML denies `sales:profit_margin` for role `tier-1-rep`. `get_metadata("sales")` and `fetch_dataset("sales")` exclude that column for tier-1 users; tier-2 users see it. |
| `test_end_to_end_no_policy_no_enforcement` | YAML directory empty; `policy_guard` constructed with the (effectively empty) evaluator allows everything (opt-in semantics). |
| `test_cache_ttl_30s_window` | Edit YAML mid-test; verify the change is reflected after the 30s cache expiry but not before (matches existing PBAC TTL contract — assert via mocked clock). |

### Test Data / Fixtures

```python
# tests/conftest.py — fixtures (sketch)

@pytest.fixture
def stub_evaluator():
    """Mock PolicyEvaluator with configurable allow/deny per call."""
    ...

@pytest.fixture
def permission_context_user_jleon():
    """PermissionContext for user jleon@trocglobal.com, no roles."""
    return PermissionContext(
        session=UserSession(
            user_id="jleon@trocglobal.com",
            tenant_id="troc",
            roles=frozenset(),
            metadata={},
        )
    )

@pytest.fixture
def permission_context_admin():
    """PermissionContext for an admin user with role 'admin'."""
    ...

@pytest.fixture
def dataset_manager_with_guard(stub_evaluator):
    """DatasetManager preloaded with two DataFrames: 'sales', 'financial_data'."""
    ...

@pytest.fixture
def yaml_policies_tmp_dir(tmp_path):
    """policies/datasets/finance.yml fixture with the sample rules from §2."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/auth/test_dataset_guard.py packages/ai-parrot/tests/tools/dataset_manager/test_policy_filtering.py -v`)
- [ ] All integration tests pass (`pytest packages/ai-parrot/tests/integration/ -v -k "dataset_policy"`)
- [ ] `DatasetManager()` constructed without `policy_guard` is behaviourally identical to the pre-feature baseline (regression test green; opt-in confirmed).
- [ ] `DatasetManager(policy_guard=DatasetPolicyGuard(evaluator))` honours dataset-level deny: target dataset is absent from `get_tools_filtered`, `list_available`, `list_datasets`, `get_active`, and `_pre_execute` returns forbidden if invoked directly.
- [ ] Column-level deny: target columns are absent from `DatasetInfo.columns`, `DatasetInfo.column_types`, and the `fetch_dataset` `DataFrame.columns`. The omission is silent — no warning, no marker, no metadata field exposes the redaction to caller or LLM.
- [ ] Fail-closed on evaluator runtime error: any non-`ImportError` exception inside `DatasetPolicyGuard` results in DENY for the affected resources, with a WARNING log line including `user_id` and the resource name.
- [ ] Fail-open on `ImportError` for `navigator-auth` (parity with `PBACPermissionResolver`, `parrot/auth/resolver.py:315–317`): when the SDK is not installed, the guard returns "allow all".
- [ ] `setup_pbac()` loads `policies/datasets/*.yml` into the same `PolicyEvaluator` as `policies/` and `policies/agents/`. Existing top-level and `agents/` loading paths are unchanged.
- [ ] Sample policy file `policies/datasets/sample.yml` committed and validates against the chosen YAML schema (lint test).
- [ ] No breaking changes to the public API of `DatasetManager`, `AbstractToolkit`, `PermissionContext`, or `setup_pbac`. `policy_guard` is a default-`None` kwarg.
- [ ] Cross-repo dependency satisfied: spec's `Target version` field references the `navigator-auth` release that ships `ResourceType.DATASET`, and `pyproject.toml` pins to that version.
- [ ] Documentation updated: a short README section in `parrot/auth/` (or `docs/sdd/specs/` companion) documents how to author dataset YAML policies and inject `DatasetPolicyGuard` into `DatasetManager` instantiation.
- [ ] Brainstorm referenced in §1 Non-Goals (rejection traceability for Options B and C).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every reference below was verified by reading the source file at the cited line on 2026-05-07.

### Verified Imports

```python
# Identity / context (existing — unchanged)
from parrot.auth.permission import (
    PermissionContext,             # packages/ai-parrot/src/parrot/auth/permission.py:80
    UserSession,                   # packages/ai-parrot/src/parrot/auth/permission.py:20
    to_eval_context,               # packages/ai-parrot/src/parrot/auth/permission.py:160
)

# Existing PBAC integration (template only — DatasetPolicyGuard mirrors but does not subclass)
from parrot.auth.resolver import (
    AbstractPermissionResolver,    # packages/ai-parrot/src/parrot/auth/resolver.py:25
    PBACPermissionResolver,        # packages/ai-parrot/src/parrot/auth/resolver.py:247
)

# Bootstrap (will be extended by Module 2)
from parrot.auth.pbac import setup_pbac
# packages/ai-parrot/src/parrot/auth/pbac.py:35

# Toolkit base classes (unchanged)
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool
# packages/ai-parrot/src/parrot/tools/toolkit.py:168, :18
from parrot.tools.abstract import AbstractTool, ToolResult
# packages/ai-parrot/src/parrot/tools/abstract.py:375 (execute), :402-412 (forbidden)

# DatasetManager and its data models (will be extended by Module 3)
from parrot.tools.dataset_manager.tool import (
    DatasetManager,                # packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:477
    DatasetEntry,                  # packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:100
    DatasetInfo,                   # packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:36
)

# navigator-auth — lazy-imported inside DatasetPolicyGuard methods (mirror resolver.py:312-317)
from navigator_auth.abac.policies.evaluator import PolicyEvaluator        # used at pbac.py:86, resolver.py:22
from navigator_auth.abac.policies.resources import ResourceType            # used at resolver.py:313
from navigator_auth.abac.policies.environment import Environment           # used at resolver.py:314
# AFTER the parallel navigator-auth PR lands:
#   ResourceType.DATASET  ← NEW enum value (does NOT exist on main today)

# To be created by this feature
from parrot.auth.dataset_guard import DatasetPolicyGuard
# packages/ai-parrot/src/parrot/auth/dataset_guard.py — NEW (Module 1)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass(frozen=True)
class UserSession:                                                # line 20
    user_id: str
    tenant_id: Optional[str]
    roles: frozenset[str]
    metadata: dict

@dataclass
class PermissionContext:                                          # line 80
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    extra: dict = ...

def to_eval_context(context: PermissionContext) -> "EvalContext":  # line 160
    """Bridges ai-parrot PermissionContext → navigator-auth EvalContext."""

# packages/ai-parrot/src/parrot/auth/resolver.py
class AbstractPermissionResolver(ABC):                             # line 25
    @abstractmethod
    async def can_execute(self, context: PermissionContext, tool_name: str,
                          required_permissions: set[str]) -> bool: ...
    @abstractmethod
    async def filter_tools(self, context: PermissionContext,
                           tools: list[Any]) -> list[Any]: ...

class PBACPermissionResolver(AbstractPermissionResolver):          # line 247
    def __init__(self, evaluator: "PolicyEvaluator",
                 logger: Optional[logging.Logger] = None) -> None: ...     # line 275
    async def can_execute(self, context, tool_name,
                          required_permissions) -> bool:                   # line 289
        # Internal: evaluator.check_access(
        #   ctx=eval_ctx, resource_type=ResourceType.TOOL,
        #   resource_name=tool_name, action="tool:execute", env=Environment()
        # )                                                                # lines 322-328
        # Logs WARNING on deny.                                            # lines 330-337
    async def filter_tools(self, context, tools) -> list[Any]:             # line 341
        # Internal: evaluator.filter_resources(
        #   ctx=eval_ctx, resource_type=ResourceType.TOOL,
        #   resource_names=[t.name for t in tools],
        #   action="tool:execute", env=Environment()
        # )                                                                # lines 371-377

# packages/ai-parrot/src/parrot/auth/pbac.py
async def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> tuple[Optional["PDP"], Optional["PolicyEvaluator"], Optional["Guardian"]]: ...
# line 35 (signature). Top-level YAML loaded at line 121.
# Per-agent YAML subdir loaded at lines 131-149 — THIS IS THE BLOCK TO MIRROR for datasets/.
# Returns (None, None, None) on any failure (lines 89-94, 98-104, 122-129, 153-159).

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:                                            # line 168
    tool_prefix: Optional[str] = None                             # line 219
    prefix_separator: str = "_"                                   # line 222
    exclude_tools: tuple[str, ...] = ()                           # line 205

    def get_tools(
        self,
        permission_context: Optional["PermissionContext"] = None,
        resolver: Optional["AbstractPermissionResolver"] = None,
    ) -> List[AbstractTool]: ...                                  # line 292

    async def get_tools_filtered(
        self,
        permission_context: "PermissionContext",
        resolver: "AbstractPermissionResolver",
    ) -> List[AbstractTool]: ...                                  # line 382
        # Body (line 399-400):
        #   all_tools = self.get_tools()
        #   return await resolver.filter_tools(permission_context, all_tools)

    # Subclass hooks (overridable):
    async def _pre_execute(self, tool_name: str, **kwargs) -> dict: ...    # line 261
    async def _post_execute(self, tool_name: str, result, **kwargs): ...   # line 280

class ToolkitTool(AbstractTool):                                  # line 18
    async def _execute(self, **kwargs):                           # line 127
        # Reads _current_pctx from parent AbstractTool             # line 153
        # Forwards into self.toolkit._pre_execute(tool_name, **hook_kwargs)  # line 156

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    async def execute(self, **kwargs) -> ToolResult:              # line 375
        # Pops _permission_context (line 391), _resolver (line 392).
        # Stores in self._current_pctx (line 421).
        # Calls resolver.can_execute(...) (line 396).
        # Returns ToolResult(status='forbidden', ...) on deny (lines 402-412).

# packages/ai-parrot/src/parrot/tools/manager.py
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                       permission_context: Optional[PermissionContext] = None
                       ) -> Any:                                  # line 1126
    # Injects _permission_context (line 1174), _resolver (line 1176)
    # into tool.execute(**exec_kwargs) (line 1178).

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetEntry:                                               # line 100
    name: str                                                     # line 135
    is_active: bool = True                                        # line 121
    description: str
    metadata: Dict[str, Any]
    async def materialize(self, **params) -> pd.DataFrame: ...   # line 225
    def to_info(self) -> DatasetInfo: ...                         # line 382

class DatasetInfo(BaseModel):                                     # line 36
    name: str
    columns: List[str]
    column_types: Dict[str, str]
    shape: Tuple[int, int]
    is_active: bool
    source_type: str
    usage_do: List[str]                                           # line 90
    usage_dont: List[str]                                         # line 94

class DatasetManager(AbstractToolkit):                            # line 477
    tool_prefix = "dataset"                                       # line 497
    exclude_tools = ("setup", "add_dataset", "list_available")    # line 498
    _datasets: Dict[str, DatasetEntry]                            # line 509

    async def add_dataframe(self, name: str, df: pd.DataFrame,
                            is_active: bool = True): ...         # line 959
    async def activate(self, names: List[str]): ...              # line 2061
    async def deactivate(self, names: List[str]): ...            # line 2079
    async def list_available(self) -> List[Dict[str, Any]]: ...  # line 2506
    async def get_active(self) -> List[str]: ...                 # line 2510
    async def get_metadata(self, name: str) -> Dict[str, Any]: ...  # line 2553
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DatasetPolicyGuard.filter_datasets` | `PolicyEvaluator.filter_resources` | direct call with `resource_type=ResourceType.DATASET, action="dataset:read"` | mirrors `parrot/auth/resolver.py:371-377` (TOOL variant) |
| `DatasetPolicyGuard.filter_columns` | `PolicyEvaluator.filter_resources` | direct call with `resource_names=[f"{ds}:{c}" for c in cols], action="dataset:column:read"` | new pattern — composite resource name decided in this spec |
| `DatasetPolicyGuard.can_read_dataset` | `PolicyEvaluator.check_access` | direct call with `resource_type=ResourceType.DATASET, action="dataset:read"` | mirrors `parrot/auth/resolver.py:322-328` (TOOL variant) |
| `setup_pbac` (extended) | `PolicyLoader.load_from_directory` | called for `policies/datasets/` after the existing `agents/` block | extends `parrot/auth/pbac.py:131-149` |
| `DatasetManager.__init__` | `DatasetPolicyGuard` instance | constructor kwarg `policy_guard=` (passed in by app bootstrap) | new — `parrot/tools/dataset_manager/tool.py:477` |
| `DatasetManager.get_tools_filtered` | `super().get_tools_filtered`, then `policy_guard.filter_datasets` | overridden method | `parrot/tools/toolkit.py:382` (super) + new |
| `DatasetManager.list_available` / `get_active` | `policy_guard.filter_datasets` | wrapped to drop denied names | `parrot/tools/dataset_manager/tool.py:2506`, `:2510` |
| `DatasetManager.get_metadata` | `policy_guard.filter_columns` (after `entry.to_info()`) | wrapped to trim `DatasetInfo.columns` and `column_types` | `parrot/tools/dataset_manager/tool.py:2553` + `:382` |
| `DatasetManager.fetch_dataset` (and any DataFrame-returning tool) | `policy_guard.filter_columns` (after `entry.materialize`) | wrapped to drop columns from `DataFrame` | `parrot/tools/dataset_manager/tool.py:225` (materialize source) |
| `DatasetManager._pre_execute` | reads `self._current_pctx`, calls `policy_guard.can_read_dataset` | toolkit lifecycle hook | `parrot/tools/toolkit.py:127-156` (injection), `:261` (hook) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.auth.dataset_guard`~~ — module **does not exist yet**; this FEAT creates it.
- ~~`DatasetPolicyGuard`~~ — class **does not exist yet**.
- ~~`navigator_auth.abac.policies.resources.ResourceType.DATASET`~~ — enum value **does not exist on `navigator-auth` main today**. **Cross-repo PR is a hard blocker** for any code path that imports it. Implementation tasks must verify the value exists before merging; tests may use a `unittest.mock.MagicMock()` for `ResourceType.DATASET` only when the cross-repo PR is still pending.
- ~~`DatasetEntry.policy_resource`~~ / ~~`DatasetEntry.required_roles`~~ / ~~`DatasetEntry.allowed_users`~~ — not real attributes. Decision (Round 3): identify by `DatasetEntry.name`, no extra field.
- ~~`@dataset_policy` decorator~~ — no Python decorator-based policy declaration in `parrot.auth`. Policies live in YAML.
- ~~`Guardian.filter_datasets`~~ — `Guardian` (navigator-auth) only supports tool resources today (via `Guardian.filter_resources`). Dataset filtering goes through the new `DatasetPolicyGuard`; the existing `Guardian` middleware is **not** modified by this FEAT.
- ~~`AbstractToolkit.filter_tools_by_policy`~~ — no such method. The existing hook is `get_tools_filtered()` (`toolkit.py:382`).
- ~~`contextvars.ContextVar('current_user')`~~ — no ambient user-identity contextvar. Identity is passed explicitly via `permission_context=` kwargs through `ToolManager.execute_tool` and into `_current_pctx` on the tool.
- ~~`policies/datasets/`~~ — directory **does not yet exist** on disk in any deployment. The implementation creates a sample under `policies/datasets/sample.yml`.
- ~~Per-row filtering / WHERE-clause injection~~ — explicitly out of scope for v1 (see §1 Non-Goals).
- ~~`DatasetPolicyGuard` subclass of `PBACPermissionResolver`~~ — they are **siblings**, not in an inheritance relationship. Both wrap the same `PolicyEvaluator` but expose different interfaces.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first**: every public method on `DatasetPolicyGuard` is `async`; every wrapper inside `DatasetManager` stays `async`. No synchronous wrapping of `PolicyEvaluator` calls.
- **Lazy navigator-auth imports**: imports of `ResourceType`, `Environment` happen *inside* the `DatasetPolicyGuard` async methods, not at module top — matching `parrot/auth/resolver.py:312–317`. This preserves graceful degradation when navigator-auth is absent.
- **Logging**: use `self.logger = logger or logging.getLogger(__name__)` and emit WARNING on deny with the same field set as `PBACPermissionResolver` (`resolver.py:331–337`): `user=%s resource=%s policy=%s reason=%s`. Standardised log shape eases SIEM ingestion later.
- **Pydantic discipline**: any new structured output (none planned — `DatasetInfo` is reused) follows `BaseModel` conventions; `DatasetInfo` is mutated post-build by trimming `columns` and `column_types` in lockstep — never one without the other.
- **Drop-silent semantics are absolute**: no `permission_denied: True` field, no debug-mode toggle that exposes redaction, no `_redacted` shadow attribute. The LLM and the caller must be unable to distinguish "column never existed" from "column hidden by policy" through any tool output.
- **Constructor-injection wiring** (resolved): `DatasetManager(policy_guard=...)` is the only supported wiring. No `app[...]` lookup, no setter. App bootstrap constructs the guard once and passes it explicitly. (Resolved from §8 question — see resolution below.)
- **Composite resource names for columns** (resolved): YAML and runtime use `resource_name=f"{dataset_name}:{column_name}"` with `action="dataset:column:read"`. (Resolved from §8 question — see resolution below.)
- **Cross-repo PR ordering**: the `navigator-auth` PR adding `ResourceType.DATASET` MUST merge first. Do not start Module 1 implementation until the new release is published. Pin `navigator-auth>=<that-release>` in `pyproject.toml` as part of Module 1's task.

### Known Risks / Gotchas

- **Cross-repo blocker**: `ResourceType.DATASET` does not exist on `navigator-auth` main. Any task that imports it will fail until the parallel PR lands. Mitigation: open the navigator-auth PR first, get it merged and released; only then start ai-parrot Module 1.
- **Cache TTL of 30s**: `PolicyEvaluator(cache_ttl_seconds=30)` (`pbac.py:114`) means a YAML edit takes up to 30s to take effect. Acceptable per Round 1 of brainstorm. Document in operator README; surface as an Open Question for ops to confirm in their environment.
- **Column drop-silent leakage**: a malformed YAML schema could accidentally expose redaction (e.g. `action="dataset:column:read"` matching but `effect=ALLOW`). Mitigation: integration test verifies that with a deny rule the column is gone from `DatasetInfo.columns`, `DatasetInfo.column_types`, and `DataFrame.columns` — three independent assertions per test case.
- **Anonymous user**: when `PermissionContext.session.user_id` is None or missing, treat as fully restrictive (deny all policy-protected datasets and columns). Datasets without policies remain visible. This matches the opt-in backwards-compat contract.
- **Performance — column filter cost**: each `get_metadata` and `fetch_dataset` triggers one `filter_resources` call with up to N column resource names. For wide datasets (50+ columns) this is one PolicyEvaluator round-trip. The evaluator's per-policy cache (`cache_ttl_seconds=30`) absorbs repeated calls within a turn. If profiling shows this dominates request time, consider caching per `(user_id, dataset_name)` in `DatasetPolicyGuard` for the request scope — deferred until measured.
- **Dataset rename**: a YAML policy referencing the old name silently no-ops. Mitigation deferred to a startup-time validator (see §8 Open Question).
- **Layer-2 `_pre_execute` interplay with `AbstractTool.execute`**: `AbstractTool.execute()` already runs `resolver.can_execute(...)` for tool-level PBAC at `:396`. Our `_pre_execute` adds a *second* dataset-level check. Both must pass. Order is: tool-level Layer-2 first (because `AbstractTool.execute` runs before `ToolkitTool._execute → toolkit._pre_execute` per `toolkit.py:127–156`), then dataset-level. A `ToolResult(status='forbidden', ...)` shape from either layer is the contract for "denied" — use the same shape, not a custom error.
- **Test isolation**: do NOT import `navigator_auth` directly in unit tests; mock `PolicyEvaluator` and `ResourceType` to keep tests fast and to allow them to run before the cross-repo PR lands. Integration tests may import `navigator_auth` once it's pinned.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | `>=<TBD release with ResourceType.DATASET>` | Provides `PolicyEvaluator`, `ResourceType.DATASET`, `EvalContext`, `Environment`. Cross-repo dependency — pin during Module 1. |
| `pydantic` | (existing) | `DatasetInfo`, `UserSession`, `PermissionContext`. No version bump. |
| `pyyaml` | (transitive via `navigator-auth`) | YAML policy storage. No direct dependency change. |
| `pandas` | (existing) | `DataFrame.drop(columns=...)` for column filtering in `fetch_dataset`. No version bump. |

---

## 8. Open Questions

- [x] **`DatasetPolicyGuard` wiring** — *Resolved during /sdd-spec*: constructor kwarg `DatasetManager(policy_guard=DatasetPolicyGuard(evaluator))`. App bootstrap constructs the guard after `setup_pbac()` and passes it explicitly. No `app[...]` registry lookup, no setter. Reflected in §2 Overview, §2 Data Models, §3 Module 3, §7 Patterns to Follow.

- [x] **Column-policy YAML schema** — *Resolved during /sdd-spec*: composite resource name `<dataset>:<column>` with `action="dataset:column:read"`. The evaluator handles batch column checks via one `filter_resources` call per `get_metadata` / `fetch_dataset`. Reflected in §2 Data Models (sample YAML), §3 Module 4, §6 Integration Points, §7 Patterns to Follow.

- [x] **Resource model — `ResourceType.DATASET`** — *Resolved in brainstorm Round 2*: extend `navigator-auth` with a new `ResourceType.DATASET` enum value (parallel cross-repo PR).

- [x] **Granularity for v1** — *Resolved in brainstorm Round 2*: dataset-entire visibility + column visibility. Row-level and action-granular filtering are out of scope (see §1 Non-Goals).

- [x] **Failure mode** — *Resolved in brainstorm Round 2*: fail-closed on any runtime error (exception during evaluator call). Fail-open only on `ImportError` for `navigator-auth` (parity with existing `PBACPermissionResolver`).

- [x] **Authoring location** — *Resolved in brainstorm Round 2*: YAML in `policies/datasets/`, loaded by an extended `setup_pbac()` (Module 2).

- [x] **Cross-repo strategy** — *Resolved in brainstorm Round 3*: parallel `navigator-auth` PR merges first; this FEAT consumes the resulting release. Pin in `pyproject.toml` during Module 1.

- [x] **Hidden column semantics** — *Resolved in brainstorm Round 3*: drop-silent. The LLM and the caller cannot distinguish "column never existed" from "column hidden by policy".

- [x] **Backwards compat** — *Resolved in brainstorm Round 3*: opt-in. `DatasetManager()` without `policy_guard` is unchanged. Datasets without matching policies remain visible to all users.

- [x] **Dataset identity** — *Resolved in brainstorm Round 3*: `DatasetEntry.name` is the canonical resource identity used by YAML.

- [ ] **Cross-repo version pin** — Which `navigator-auth` release ships `ResourceType.DATASET`? Pin in `pyproject.toml` during Module 1. *Owner: Jesus Lara* (carried from brainstorm Q1).

- [ ] **Convenience return from `setup_pbac`** — Should `setup_pbac()` also return a pre-bound `DatasetPolicyGuard` (e.g. become `(pdp, evaluator, guardian, dataset_guard)` or expose it on `app['dataset_guard']`)? Convenience vs. one extra signature change. Defer to /sdd-task scoping. *Owner: spec author*.

- [ ] **Audit-log format** — Mirror `PBACPermissionResolver`'s WARNING line format verbatim, or emit structured JSON for downstream SIEM? *Owner: ops* (carried from brainstorm Q4).

- [ ] **Hot-reload** — Is the existing 30s `cache_ttl_seconds` sufficient, or do we need a `PolicyEvaluator.invalidate()` call wired to a filesystem watcher? Out of scope for v1 (see §1 Non-Goals); reopen if ops reports the staleness window unacceptable. *Owner: ops* (carried from brainstorm Q5).

- [ ] **Dataset rename validator** — Add a startup-time check that warns about YAML resources whose `name` does not match any registered `DatasetEntry.name`? Helps ops detect orphan rules. *Owner: spec author* (carried from brainstorm Q6).

- [ ] **Telemetry** — Should denials emit a metric (e.g. `parrot_dataset_policy_denied_total{resource,user}`) for dashboarding? Out of scope for v1; tracked here for follow-up. *Owner: ops* (carried from brainstorm Q7).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. All tasks for FEAT-151 run sequentially in a single worktree at `.claude/worktrees/feat-151-pbac-datasetmanager-policy/`.
- **Rationale**: the work concentrates in three files (`parrot/auth/dataset_guard.py` new, `parrot/auth/pbac.py` modify, `parrot/tools/dataset_manager/tool.py` modify) plus tests and a sample YAML. Strict task ordering exists (`navigator-auth` PR → Module 1 → Module 3 wiring → Module 5 tests → Module 4 sample). Splitting between worktrees would add ceremony without paralleling any genuinely independent work.
- **Cross-feature dependencies**:
  - **Hard blocker (cross-repo)**: `navigator-auth` PR adding `ResourceType.DATASET` — must be merged and released before Module 1's import statement is valid. Do not branch the worktree into implementation tasks until the new `navigator-auth` is published. The worktree CAN be created earlier to start Module 4 (YAML sample) and tests against mocked `ResourceType`.
  - **No in-flight ai-parrot conflicts** observed at scoping time. Coordinate with anyone editing `parrot/tools/dataset_manager/tool.py` (it's actively-maintained; `to_info`, `materialize`, `list_available` are the touchpoints).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-07 | Jesus Lara | Initial draft. Carries forward `pbac-datasetmanager-policy.brainstorm.md` (Recommended Option A). Resolves brainstorm Q2 (constructor wiring) and Q3 (composite YAML resource name); 5 brainstorm questions remain open and tracked in §8. |
