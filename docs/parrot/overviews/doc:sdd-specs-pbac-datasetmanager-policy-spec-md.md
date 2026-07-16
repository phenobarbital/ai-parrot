---
type: Wiki Overview
title: 'Feature Specification: PBAC-Driven DatasetManager Policy Enforcement'
id: doc:sdd-specs-pbac-datasetmanager-policy-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This is a data-leak vector. Concrete failure case: user `jleon@trocglobal.com`
  opens a chat with a finance-aware agent and the LLM is exposed to a `financial_data`
  dataset that — by HR/compliance policy — that user is not entitled to query. The
  LLM may list it, describe its schem'
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.dataset_guard
  rel: mentions
- concept: mod:parrot.auth.pbac
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.auth.resolver
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: PBAC-Driven DatasetManager Policy Enforcement

**Feature ID**: FEAT-151
**Date**: 2026-05-07
**Author**: Jesus Lara
**Status**: approved
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

…(truncated)…
