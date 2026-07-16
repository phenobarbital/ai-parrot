---
type: Wiki Overview
title: 'TASK-1044: DatasetPolicyGuard class'
id: doc:sdd-tasks-completed-task-1044-dataset-policy-guard-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: from parrot.auth.permission import PermissionContext, UserSession, to_eval_context
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.dataset_guard
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
---

# TASK-1044: DatasetPolicyGuard class

**Feature**: FEAT-151 — PBAC-Driven DatasetManager Policy Enforcement
**Spec**: `sdd/specs/pbac-datasetmanager-policy.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 1 of the FEAT-151 spec: the `DatasetPolicyGuard` class.
> This is the foundational component that wraps `navigator-auth`'s `PolicyEvaluator`
> with dataset-specific resource type and actions. All downstream tasks (DatasetManager
> integration, integration tests) depend on this class.
>
> The class mirrors `PBACPermissionResolver` (`parrot/auth/resolver.py:247`) in shape:
> same lazy-import pattern, same `to_eval_context` bridge, same WARNING-on-deny format,
> same fail-open-on-ImportError for backwards compat.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/dataset_guard.py` with the `DatasetPolicyGuard` class.
- Implement three async methods: `filter_datasets`, `filter_columns`, `can_read_dataset`.
- Use lazy imports for `navigator-auth` types (`ResourceType`, `Environment`) inside each method — NOT at module top.
- Implement fail-closed semantics: any non-`ImportError` exception → DENY + WARNING log.
- Implement fail-open on `ImportError` for `navigator-auth` → return "all allowed" (parity with `PBACPermissionResolver`, `resolver.py:315–317`).
- Fail-closed on missing session: `PermissionContext.session` is None or `user_id` is None → DENY.
- Add `DatasetPolicyGuard` to `parrot/auth/__init__.py` exports.
- Write unit tests in `packages/ai-parrot/tests/auth/test_dataset_guard.py`.

**NOT in scope**: modifying `DatasetManager` (TASK-1046), modifying `setup_pbac` (TASK-1045), integration tests (TASK-1047), sample YAML policies (TASK-1047).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/dataset_guard.py` | CREATE | `DatasetPolicyGuard` class |
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | Add `DatasetPolicyGuard` to exports |
| `packages/ai-parrot/tests/auth/test_dataset_guard.py` | CREATE | Unit tests for `DatasetPolicyGuard` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports

```python
# Identity / context bridge — use these VERBATIM
from parrot.auth.permission import PermissionContext, UserSession, to_eval_context
# packages/ai-parrot/src/parrot/auth/permission.py:80, :20, :160

# Lazy-imported INSIDE async methods (NOT at module top):
from navigator_auth.abac.policies.evaluator import PolicyEvaluator   # used at pbac.py:86
from navigator_auth.abac.policies.resources import ResourceType       # used at resolver.py:313
from navigator_auth.abac.policies.environment import Environment      # used at resolver.py:314

# Standard library
import logging
from typing import Optional
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/permission.py:20
@dataclass(frozen=True)
class UserSession:
    user_id: str                    # line 45
    tenant_id: str                  # line 46
    roles: frozenset[str]           # line 47
    metadata: dict[str, Any]        # line 48

# packages/ai-parrot/src/parrot/auth/permission.py:80
@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    extra: dict = ...

# packages/ai-parrot/src/parrot/auth/permission.py:160
def to_eval_context(context: PermissionContext) -> "EvalContext":
    """Bridges ai-parrot PermissionContext → navigator-auth EvalContext."""

# Pattern to follow — PBACPermissionResolver lazy-import inside methods:
# packages/ai-parrot/src/parrot/auth/resolver.py:312-317
#   try:
#       from navigator_auth.abac.policies.resources import ResourceType
#       from navigator_auth.abac.policies.environment import Environment
#   except ImportError:
#       return <all-allowed>

# PBACPermissionResolver.can_execute uses:
# packages/ai-parrot/src/parrot/auth/resolver.py:322-328
#   result = self._evaluator.check_access(
#       ctx=eval_ctx, resource_type=ResourceType.TOOL,
#       resource_name=tool_name, action="tool:execute", env=Environment()
#   )

# PBACPermissionResolver.filter_tools uses:
# packages/ai-parrot/src/parrot/auth/resolver.py:371-377
#   filtered = self._evaluator.filter_resources(
#       ctx=eval_ctx, resource_type=ResourceType.TOOL,
#       resource_names=[t.name for t in tools],
#       action="tool:execute", env=Environment()
#   )

# WARNING log format from PBACPermissionResolver (resolver.py:331-337):
# self.logger.warning("PBAC deny: user=%s resource=%s ...")
```

### Does NOT Exist

- ~~`parrot.auth.dataset_guard`~~ — module does NOT exist yet; this task creates it.
- ~~`DatasetPolicyGuard`~~ — class does NOT exist yet; this task creates it.
- ~~`ResourceType.DATASET`~~ — enum value does NOT exist on current `navigator-auth` main. **Mock it in unit tests** with `unittest.mock.MagicMock()` until the cross-repo PR lands.
- ~~`@dataset_policy` decorator~~ — no decorator-based policy in `parrot.auth`. Policies are YAML.
- ~~`Guardian.filter_datasets`~~ — `Guardian` only knows about tool resources. Do not call it.
- ~~`contextvars.ContextVar('current_user')`~~ — no ambient user identity. Use explicit `PermissionContext`.
- ~~`DatasetPolicyGuard` subclass of `PBACPermissionResolver`~~ — they are siblings, NOT in an inheritance relationship. Both wrap `PolicyEvaluator` but expose different interfaces.

---

## Implementation Notes

### Pattern to Follow

```python
# Mirror PBACPermissionResolver (parrot/auth/resolver.py:247) structure:
#
# class DatasetPolicyGuard:
#     def __init__(self, evaluator, logger=None):
#         self._evaluator = evaluator
#         self.logger = logger or logging.getLogger(__name__)
#
#     async def filter_datasets(self, context, dataset_names):
#         try:
#             from navigator_auth.abac.policies.resources import ResourceType
#             from navigator_auth.abac.policies.environment import Environment
#         except ImportError:
#             return set(dataset_names)  # fail-open: navigator-auth not installed
#
#         eval_ctx = to_eval_context(context)
#         env = Environment()
#         try:
#             result = self._evaluator.filter_resources(
#                 ctx=eval_ctx,
#                 resource_type=ResourceType.DATASET,
#                 resource_names=list(dataset_names),
#                 action="dataset:read",
#                 env=env,
#             )
#             return set(result.allowed)
#         except Exception as exc:
#             self.logger.warning("PBAC dataset deny (error): user=%s reason=%s", ...)
#             return set()  # fail-closed
```

### Key Constraints

- All three public methods MUST be `async`.
- Lazy-import `ResourceType`, `Environment` inside each method (not at module top).
- `filter_columns` uses composite resource names: `resource_names=[f"{dataset_name}:{c}" for c in columns]` with `action="dataset:column:read"`.
- `filter_columns` MUST preserve the input order of columns (return `[c for c in columns if c in allowed_set]`).
- When `context.session` is `None` or `context.session.user_id` is `None`: DENY everything (fail-closed). Do NOT raise.
- Use `self.logger = logger or logging.getLogger(__name__)`.
- WARNING log on deny must include `user_id` and `resource_name` (mirror `resolver.py:331-337`).

### References in Codebase

- `packages/ai-parrot/src/parrot/auth/resolver.py:247-377` — `PBACPermissionResolver`: the template class to mirror.
- `packages/ai-parrot/src/parrot/auth/permission.py:160` — `to_eval_context()`: the identity bridge.
- `packages/ai-parrot/src/parrot/auth/__init__.py` — current exports to extend.

---

## Acceptance Criteria

- [ ] `DatasetPolicyGuard` can be constructed with a stub `PolicyEvaluator`.
- [ ] `filter_datasets` returns the allowed subset as a `set[str]`.
- [ ] `filter_datasets` with empty input short-circuits to empty set.
- [ ] `filter_columns` returns allowed columns in original input order.
- [ ] `filter_columns` calls `evaluator.filter_resources` with composite `"{dataset}:{column}"` resource names and `action="dataset:column:read"`.
- [ ] `can_read_dataset` returns `bool` using `evaluator.check_access`.
- [ ] `can_read_dataset` logs WARNING on deny with `user_id` and `dataset_name`.
- [ ] On `ImportError` for navigator-auth: all methods return "all allowed" (fail-open).
- [ ] On `RuntimeError` (or any non-`ImportError`) from evaluator: methods return DENY (fail-closed) and log WARNING.
- [ ] On `PermissionContext` with `session=None` or `user_id=None`: methods return DENY.
- [ ] `from parrot.auth import DatasetPolicyGuard` works (export added to `__init__.py`).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/auth/test_dataset_guard.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/auth/dataset_guard.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/auth/test_dataset_guard.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.dataset_guard import DatasetPolicyGuard


@pytest.fixture
def stub_evaluator():
    """Mock PolicyEvaluator with configurable allow/deny."""
    evaluator = MagicMock()
    return evaluator


@pytest.fixture
def pctx_jleon():
    """PermissionContext for jleon@trocglobal.com."""
    return PermissionContext(
        session=UserSession(
            user_id="jleon@trocglobal.com",
            tenant_id="troc",
            roles=frozenset(),
            metadata={},
        )
    )


@pytest.fixture
def guard(stub_evaluator):
    return DatasetPolicyGuard(evaluator=stub_evaluator)


class TestDatasetPolicyGuard:
    def test_init_with_evaluator(self, guard, stub_evaluator):
        """Constructs with a stub evaluator; verifies attribute storage."""
        assert guard._evaluator is stub_evaluator

    @pytest.mark.asyncio
    async def test_filter_datasets_allows_subset(self, guard, pctx_jleon):
        """Stub evaluator returns allowed=['a','c']; guard returns {'a','c'}."""
        ...

    @pytest.mark.asyncio
    async def test_filter_datasets_empty_input(self, guard, pctx_jleon):
        """Empty list short-circuits without evaluator call."""
        result = await guard.filter_datasets(pctx_jleon, [])
        assert result == set()

    @pytest.mark.asyncio
    async def test_filter_columns_preserves_order(self, guard, pctx_jleon):
        """Returns allowed columns in input order, not evaluator order."""
        ...

    @pytest.mark.asyncio
    async def test_filter_columns_composite_resource_name(self, guard, pctx_jleon):
        """Asserts evaluator called with ['sales:c1','sales:c2']."""
        ...

    @pytest.mark.asyncio
    async def test_can_read_dataset_allows(self, guard, pctx_jleon):
        """Stub returns allowed=True; guard returns True."""
        ...

    @pytest.mark.asyncio
    async def test_can_read_dataset_denies_with_warning(self, guard, pctx_jleon):
        """Stub returns allowed=False; guard returns False and logs WARNING."""
        ...

    @pytest.mark.asyncio
    async def test_fail_open_on_importerror(self, pctx_jleon, stub_evaluator):
        """Patches lazy import to raise ImportError; returns all allowed."""
        ...

    @pytest.mark.asyncio
    async def test_fail_closed_on_evaluator_exception(self, guard, pctx_jleon):
        """Stub evaluator raises RuntimeError; guard returns DENY + WARNING."""
        ...

    @pytest.mark.asyncio
    async def test_fail_closed_on_missing_session(self, guard):
        """PermissionContext with session=None → DENY."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pbac-datasetmanager-policy.spec.md` for full context
2. **Check dependencies** — this task has no dependencies; start immediately
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/pbac-datasetmanager-policy.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1044-dataset-policy-guard.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Code)
**Date**: 2026-05-07
**Notes**: Created `parrot/auth/dataset_guard.py` with `DatasetPolicyGuard` class implementing
three async methods: `filter_datasets`, `filter_columns`, `can_read_dataset`. Added export to
`parrot/auth/__init__.py`. Written 22 unit tests, all passing. Mirrors `PBACPermissionResolver`
pattern exactly: lazy imports, fail-open on ImportError, fail-closed on runtime errors,
WARNING-on-deny log format. Column filtering preserves input order; composite resource names
used as specified.

**Deviations from spec**: none
