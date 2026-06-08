# TASK-1495: DataPlanePolicyGuard

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1493
**Assigned-to**: unassigned

---

## Context

> Spec Module 6. The central guard class — sibling of `DatasetPolicyGuard` — that
> evaluates `driver:connect`, `table:read`, and `source:read` actions against the
> shared `PolicyEvaluator`. Also collects RLS predicates from the registry and
> manages the `sensitive` driver class pre-check. This is the authorization
> decision point.

---

## Scope

- Implement `DataPlanePolicyGuard` with:
  - `can_connect_driver(ctx, driver) -> bool` — evaluate `driver:connect`.
  - `filter_tables(ctx, driver, tables) -> set[str]` — batch `table:read` filter.
  - `authorize_source(ctx, resources: PhysicalResources) -> None` — full chain:
    driver gate → table/source gate. Raises `AuthorizationRequired` on denial.
  - `rls_predicates(ctx, resources) -> list[RlsPredicate]` — collect from registry.
  - `is_sensitive_driver(driver) -> bool` — check the driver-class config.
- Lazy-import navigator-auth (matches `DatasetPolicyGuard` pattern).
- Fail-open when no `PermissionContext` is available (FEAT-151 parity).
- Fail-closed on evaluator errors for guarded drivers.
- Write unit tests with mocked `PolicyEvaluator`.

**NOT in scope**: Physical resource resolution (TASK-1491), RLS injection
(TASK-1494), `AuthorizingDataSource` wiring (TASK-1496), DatasetManager
integration (TASK-1497).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/dataplane_guard.py` | CREATE | `DataPlanePolicyGuard` class |
| `parrot/auth/__init__.py` | MODIFY | Export `DataPlanePolicyGuard` |
| `tests/auth/test_dataplane_guard.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Auth layer
from parrot.auth.permission import PermissionContext, UserSession  # verified: __init__.py
from parrot.auth.permission import to_eval_context                 # verified: permission.py:166
from parrot.auth.exceptions import AuthorizationRequired           # verified: exceptions.py:12
from parrot.auth.rls_registry import RlsRegistry, RlsPredicate    # from TASK-1493

# navigator-auth (lazy import)
# navigator_auth.abac.policies.evaluator.PolicyEvaluator
#   .check_access(ctx, resource_type, resource_name, action, env) -> result with .allowed
#   .filter_resources(ctx, resource_type, resource_names, action, env) -> result with .allowed (list)
```

### Existing Signatures to Use
```python
# parrot/auth/dataset_guard.py — PATTERN TO FOLLOW
class DatasetPolicyGuard:
    def __init__(self, evaluator: "PolicyEvaluator", logger=None) -> None:  # line ~56
    # Uses: self._evaluator, self._logger
    # Lazy imports navigator-auth inside methods
    # Uses to_eval_context(ctx) to bridge PermissionContext → EvalContext
    # Returns results based on evaluator.check_access().allowed

# parrot/auth/permission.py:80
@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    # ...

# parrot/auth/permission.py:166
def to_eval_context(context: PermissionContext) -> "EvalContext":
    # Module-level function, not a method on PermissionContext

# parrot/auth/exceptions.py:12
class AuthorizationRequired(Exception): ...

# parrot/auth/__init__.py:59–91 — __all__ list
# Add DataPlanePolicyGuard to this list
```

### Does NOT Exist
- ~~`parrot.auth.dataplane_guard`~~ — does not exist yet (this task creates it)
- ~~`DataPlanePolicyGuard`~~ — does not exist yet
- ~~`PermissionContext.to_eval_context()`~~ — it is a MODULE-LEVEL function `to_eval_context(ctx)`, NOT a method
- ~~`PolicyEvaluator.check_driver()`~~ — not a real method; use `check_access(ctx, "driver", name, "driver:connect")`
- ~~`PolicyEvaluator.check_table()`~~ — not a real method; use `check_access(ctx, "table", name, "table:read")`

---

## Implementation Notes

### Pattern to Follow

Follow `DatasetPolicyGuard` structure exactly:

```python
import logging
from typing import Optional, TYPE_CHECKING

from parrot.auth.permission import PermissionContext, to_eval_context
from parrot.auth.exceptions import AuthorizationRequired

if TYPE_CHECKING:
    from parrot.auth.rls_registry import RlsRegistry, RlsPredicate

class DataPlanePolicyGuard:
    """Data-plane authorization guard for driver/table/source resources.

    Sibling of DatasetPolicyGuard — shares the same PolicyEvaluator.
    """

    def __init__(
        self,
        evaluator: "PolicyEvaluator",
        rls_registry: "RlsRegistry",
        sensitive_drivers: frozenset[str] = frozenset(),
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._evaluator = evaluator
        self._rls_registry = rls_registry
        self._sensitive_drivers = sensitive_drivers
        self._logger = logger or logging.getLogger(__name__)

    def is_sensitive_driver(self, driver: str) -> bool:
        return driver in self._sensitive_drivers

    async def can_connect_driver(self, ctx: PermissionContext, driver: str) -> bool:
        eval_ctx = to_eval_context(ctx)
        result = self._evaluator.check_access(
            eval_ctx, "driver", driver, "driver:connect"
        )
        return result.allowed

    async def authorize_source(self, ctx, resources) -> None:
        # 1. driver:connect gate
        # 2. table:read / source:read gate per resource
        # Raise AuthorizationRequired on any denial
        ...
```

### Key Constraints
- **String resource types**: pass `"driver"`, `"table"`, `"source"` as plain
  strings to `PolicyEvaluator.check_access()` — not enum values.
- **Fail-open on missing context**: if `ctx` is `None`, return without checking
  (matches FEAT-151 backwards-compat semantics).
- **Fail-closed on evaluator errors**: catch exceptions from the evaluator and
  treat as DENY for guarded drivers. Log a warning.
- navigator-auth may not be installed — guard against `ImportError` at the class
  level (lazy import in `__init__` or methods).
- `sensitive_drivers` is a `frozenset[str]` loaded from config at construction
  time (not from policy).

### References in Codebase
- `parrot/auth/dataset_guard.py` — structural pattern (follow this closely)
- `parrot/auth/permission.py` — `to_eval_context`, `PermissionContext`
- `parrot/auth/exceptions.py` — `AuthorizationRequired`

---

## Acceptance Criteria

- [ ] `can_connect_driver()` returns True/False based on `PolicyEvaluator`
- [ ] `filter_tables()` returns only allowed tables from input set
- [ ] `authorize_source()` raises `AuthorizationRequired` when driver denied
- [ ] `authorize_source()` raises `AuthorizationRequired` when any table denied
- [ ] `authorize_source()` succeeds when all resources allowed
- [ ] `is_sensitive_driver()` correctly checks the configured set
- [ ] `rls_predicates()` returns predicates from the registry
- [ ] `ctx=None` → no enforcement (fail-open, FEAT-151 parity)
- [ ] Evaluator error on guarded driver → DENY (fail-closed)
- [ ] `DataPlanePolicyGuard` exported from `parrot.auth`
- [ ] All tests pass: `pytest tests/auth/test_dataplane_guard.py -v`
- [ ] No linting errors: `ruff check parrot/auth/dataplane_guard.py`

---

## Test Specification

```python
# tests/auth/test_dataplane_guard.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.auth.dataplane_guard import DataPlanePolicyGuard
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.rls_registry import RlsRegistry


@pytest.fixture
def mock_evaluator():
    ev = MagicMock()
    # Default: allow everything
    result = MagicMock(allowed=True)
    ev.check_access = MagicMock(return_value=result)
    filter_result = MagicMock(allowed=["pg:sales.orders"])
    ev.filter_resources = MagicMock(return_value=filter_result)
    return ev


@pytest.fixture
def guard(mock_evaluator):
    return DataPlanePolicyGuard(
        evaluator=mock_evaluator,
        rls_registry=RlsRegistry(),
        sensitive_drivers=frozenset({"bigquery_finance"}),
    )


@pytest.fixture
def pctx():
    return PermissionContext(
        session=UserSession(username="test", groups=["Finance"], programs=[])
    )


class TestDataPlanePolicyGuard:
    @pytest.mark.asyncio
    async def test_can_connect_allowed(self, guard, pctx):
        assert await guard.can_connect_driver(pctx, "pg") is True

    @pytest.mark.asyncio
    async def test_can_connect_denied(self, guard, pctx, mock_evaluator):
        mock_evaluator.check_access.return_value = MagicMock(allowed=False)
        assert await guard.can_connect_driver(pctx, "pg") is False

    @pytest.mark.asyncio
    async def test_authorize_source_denied_raises(self, guard, pctx, mock_evaluator):
        mock_evaluator.check_access.return_value = MagicMock(allowed=False)
        from parrot.tools.dataset_manager.sources.resolver import PhysicalResources
        resources = PhysicalResources(driver="pg", tables={"pg:finance.salaries"})
        with pytest.raises(AuthorizationRequired):
            await guard.authorize_source(pctx, resources)

    @pytest.mark.asyncio
    async def test_none_context_failopen(self, guard):
        from parrot.tools.dataset_manager.sources.resolver import PhysicalResources
        resources = PhysicalResources(driver="pg", tables={"pg:finance.salaries"})
        # Should not raise — fail-open
        await guard.authorize_source(None, resources)

    def test_is_sensitive_driver(self, guard):
        assert guard.is_sensitive_driver("bigquery_finance") is True
        assert guard.is_sensitive_driver("pg") is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` §5.3–§5.4 for guard design
2. **Check dependencies** — verify TASK-1493 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `parrot/auth/dataset_guard.py` for structural pattern
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1495-dataplane-policy-guard.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —

**Deviations from spec**: none
