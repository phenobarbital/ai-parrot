# TASK-536: PBACPermissionResolver

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-534, TASK-535
**Assigned-to**: unassigned

---

## Context

> Implements the `PBACPermissionResolver` — a thin adapter that implements
> `AbstractPermissionResolver` and delegates to navigator-auth's `PolicyEvaluator`.
> This serves as the Layer 2 safety net in `AbstractTool.execute()`, preserving
> FEAT-014's contract while adding PBAC evaluation.
>
> Implements Spec Module 3.

---

## Scope

- Add `PBACPermissionResolver` class to `parrot/auth/resolver.py`
- Implement `can_execute(context, tool_name, required_permissions)`:
  - Bridge `PermissionContext` to `EvalContext`
  - Delegate to `PolicyEvaluator.check_access(ResourceType.TOOL, tool_name, "tool:execute")`
  - Log denials with tool name, user, and matched policy
  - Return bool
- Implement `filter_tools(context, tools)`:
  - Collect tool names from tool list
  - Delegate to `PolicyEvaluator.filter_resources(ResourceType.TOOL, tool_names, "tool:execute")`
  - Return only tools whose names are in `FilteredResources.allowed`
- Create a bridge function to convert `PermissionContext` → `EvalContext`

**NOT in scope**:
- Handler integration (TASK-537+)
- App startup wiring (TASK-541)
- Guardian.filter_resources() usage in handlers (TASK-538)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/resolver.py` | MODIFY | Add `PBACPermissionResolver` class |
| `parrot/auth/permission.py` | MODIFY | Add `to_eval_context()` bridge function |
| `tests/auth/test_pbac_resolver.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
# Extend existing resolver.py which already has:
# AbstractPermissionResolver, DefaultPermissionResolver, AllowAllResolver, DenyAllResolver

from navigator_auth.abac.policies.evaluator import PolicyEvaluator
from navigator_auth.abac.policies.resources import ResourceType
from navigator_auth.abac.context import EvalContext
from navigator_auth.abac.policies.environment import Environment


class PBACPermissionResolver(AbstractPermissionResolver):
    """PBAC-backed resolver — Layer 2 safety net.

    Primary enforcement happens via Guardian at handler level.
    This resolver provides defense-in-depth by checking PBAC policies
    again at AbstractTool.execute() time.
    """

    def __init__(
        self,
        evaluator: PolicyEvaluator,
        logger: Optional[logging.Logger] = None,
    ):
        self._evaluator = evaluator
        self.logger = logger or logging.getLogger(__name__)

    async def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: set[str],
    ) -> bool:
        eval_ctx = to_eval_context(context)
        env = Environment()
        result = self._evaluator.check_access(
            ctx=eval_ctx,
            resource_type=ResourceType.TOOL,
            resource_name=tool_name,
            action="tool:execute",
            env=env,
        )
        if not result.allowed:
            self.logger.warning(
                "PBAC Layer 2 DENY: tool=%s user=%s policy=%s reason=%s",
                tool_name, context.user_id, result.matched_policy, result.reason,
            )
        return result.allowed
```

### Key Constraints
- Must implement `AbstractPermissionResolver` interface exactly
- Must use the SAME `PolicyEvaluator` instance as Guardian (shared via setup)
- Log denials — this is the Layer 2 safety net, denials here indicate a gap in Layer 1
- `to_eval_context()` must map PermissionContext.session fields to EvalContext userinfo

### References in Codebase
- `parrot/auth/resolver.py` — existing resolvers (DefaultPermissionResolver, AllowAllResolver)
- `parrot/auth/permission.py` — PermissionContext, UserSession
- `navigator_auth/abac/context.py` — EvalContext
- `navigator_auth/abac/policies/evaluator.py` — PolicyEvaluator.check_access(), filter_resources()

---

## Acceptance Criteria

- [ ] `PBACPermissionResolver` implements `AbstractPermissionResolver`
- [ ] `can_execute()` delegates to `PolicyEvaluator.check_access()`
- [ ] `can_execute()` logs denials with tool name, user ID, matched policy
- [ ] `filter_tools()` delegates to `PolicyEvaluator.filter_resources()`
- [ ] `to_eval_context()` correctly bridges PermissionContext → EvalContext
- [ ] Tests pass: `pytest tests/auth/test_pbac_resolver.py -v`
- [ ] Import works: `from parrot.auth.resolver import PBACPermissionResolver`

---

## Test Specification

```python
import pytest
from parrot.auth.resolver import PBACPermissionResolver
from parrot.auth.permission import PermissionContext, UserSession


class TestPBACPermissionResolver:
    async def test_can_execute_allow(self, resolver, engineering_context):
        """Allowed tool returns True."""
        result = await resolver.can_execute(
            engineering_context, "search_tool", set()
        )
        assert result is True

    async def test_can_execute_deny(self, resolver, guest_context):
        """Denied tool returns False and logs."""
        result = await resolver.can_execute(
            guest_context, "admin_tool", set()
        )
        assert result is False

    async def test_filter_tools(self, resolver, engineering_context, sample_tools):
        """Only allowed tools returned."""
        allowed = await resolver.filter_tools(engineering_context, sample_tools)
        allowed_names = [t.name for t in allowed]
        assert "search_tool" in allowed_names
        assert "admin_tool" not in allowed_names

    def test_context_bridge(self):
        """PermissionContext correctly converts to EvalContext."""
        session = UserSession(
            user_id="u1", tenant_id="t1",
            roles=frozenset({"engineer"}),
            metadata={"groups": ["engineering"]}
        )
        ctx = PermissionContext(session=session)
        eval_ctx = to_eval_context(ctx)
        assert eval_ctx.userinfo["username"] == "u1"
        assert "engineering" in eval_ctx.userinfo["groups"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-536-pbac-permission-resolver.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: Added PBACPermissionResolver to resolver.py and to_eval_context() to
permission.py. Tests in tests/auth/test_pbac_resolver.py.

**Deviations from spec**: none
