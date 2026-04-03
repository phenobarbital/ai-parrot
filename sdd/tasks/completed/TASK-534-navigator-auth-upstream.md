# TASK-534: navigator-auth Upstream Changes

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the prerequisite task for the entire FEAT-077. navigator-auth's ABAC module
> needs four additive changes before ai-parrot can integrate. This task is done in the
> **navigator-auth repository** (`/home/jesuslara/proyectos/navigator/navigator-auth`),
> not in ai-parrot.
>
> Implements Spec Module 1.

---

## Scope

- Add `DATASET = "dataset"` to `ResourceType` enum in `navigator_auth/abac/policies/resources.py`
- Add `Guardian.filter_resources()` generic method to `navigator_auth/abac/guardian.py`:
  - Follows the `filter_files()` pattern (extract session, build EvalContext, evaluate)
  - Accepts `resources: list[str]`, `request: web.Request`, `resource_type: ResourceType`,
    `action: str` parameters
  - Returns `FilteredResources(allowed, denied, policies_applied)`
  - Can supersede `filter_files()` internally (filter_files calls filter_resources with ResourceType.URI or similar)
- Add programs/tenants as condition attribute support in `ResourcePolicy.evaluate_conditions()`
  and `EvalContext` (programs from session accessible as condition key)
- Support configurable `cache_ttl_seconds` in `PolicyEvaluator.__init__()` (already exists
  as parameter — verify it's properly used and document short-TTL use case)

**NOT in scope**:
- Any changes to ai-parrot codebase
- New policy types or storage backends
- Breaking changes to existing navigator-auth API

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `navigator_auth/abac/policies/resources.py` | MODIFY | Add `ResourceType.DATASET` |
| `navigator_auth/abac/guardian.py` | MODIFY | Add `filter_resources()` method |
| `navigator_auth/abac/context.py` | MODIFY | Ensure programs accessible from session |
| `navigator_auth/abac/policies/resource_policy.py` | MODIFY | Support programs in conditions |
| `tests/test_guardian_filter_resources.py` | CREATE | Tests for new filter_resources method |

---

## Implementation Notes

### Pattern to Follow
```python
# Existing filter_files() pattern in Guardian:
async def filter_files(self, files, request):
    user, session = await self.get_user(request)
    ctx = EvalContext(request=request, user=user, session=session, ...)
    env = Environment()
    # ... evaluate policies and return filtered list

# New filter_resources() should follow same pattern:
async def filter_resources(
    self,
    resources: list[str],
    request: web.Request,
    resource_type: ResourceType = ResourceType.TOOL,
    action: str = "tool:execute",
) -> FilteredResources:
    user, session = await self.get_user(request)
    ctx = EvalContext(request=request, user=user, session=session, ...)
    env = Environment()
    return self.pdp._evaluator.filter_resources(
        ctx=ctx, resource_type=resource_type,
        resource_names=resources, action=action, env=env
    )
```

### Key Constraints
- All changes must be backward-compatible
- `filter_resources()` must be async
- Programs come from session userinfo — map to EvalContext attribute
- Short TTL (30s) for time-dependent policies — verify PolicyEvaluator respects `cache_ttl_seconds`

### References in Codebase
- `navigator_auth/abac/guardian.py` — `filter_files()` method (pattern to follow)
- `navigator_auth/abac/policies/evaluator.py` — `PolicyEvaluator.filter_resources()` (delegate)
- `navigator_auth/abac/policies/resources.py` — `ResourceType` enum
- `navigator_auth/abac/policies/resource_policy.py` — `evaluate_conditions()`

---

## Acceptance Criteria

- [ ] `ResourceType.DATASET` exists and works in policy matching
- [ ] `Guardian.filter_resources()` returns `FilteredResources` with allowed/denied lists
- [ ] `Guardian.filter_resources()` works for all ResourceTypes (TOOL, AGENT, MCP, DATASET, KB)
- [ ] Programs/tenants can be used as condition attributes in YAML policies
- [ ] `PolicyEvaluator(cache_ttl_seconds=30)` correctly expires cache entries after 30s
- [ ] All existing tests still pass
- [ ] New tests pass for `filter_resources()`
- [ ] No breaking changes to existing API

---

## Test Specification

```python
import pytest
from navigator_auth.abac.guardian import Guardian
from navigator_auth.abac.policies.resources import ResourceType

class TestGuardianFilterResources:
    async def test_filter_resources_tool(self, guardian, mock_request):
        """Filter tools returns only allowed tools."""
        result = await guardian.filter_resources(
            resources=["jira_create", "admin_delete", "search"],
            request=mock_request,
            resource_type=ResourceType.TOOL,
            action="tool:execute"
        )
        assert "search" in result.allowed
        assert "admin_delete" in result.denied

    async def test_filter_resources_dataset(self, guardian, mock_request):
        """Filter datasets using new ResourceType.DATASET."""
        result = await guardian.filter_resources(
            resources=["sales_data", "hr_confidential"],
            request=mock_request,
            resource_type=ResourceType.DATASET,
            action="dataset:query"
        )
        assert isinstance(result.allowed, list)

    async def test_programs_condition(self, guardian, mock_request_with_programs):
        """Policies with program conditions match correctly."""
        result = await guardian.filter_resources(
            resources=["agent_a"],
            request=mock_request_with_programs,
            resource_type=ResourceType.AGENT,
            action="agent:chat"
        )
        assert "agent_a" in result.allowed
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-534-navigator-auth-upstream.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: ResourceType.DATASET already existed in navigator-auth. Added Guardian.filter_resources()
following the filter_files() pattern. Added tests/test_guardian_filter_resources.py.
Changes committed to navigator-auth repo at commit 757b51e.

**Deviations from spec**: none
