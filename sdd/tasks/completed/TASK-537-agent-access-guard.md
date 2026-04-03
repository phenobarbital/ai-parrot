# TASK-537: Agent Access Guard

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-535
**Assigned-to**: unassigned

---

## Context

> Adds PBAC-backed agent access control to `AgentTalk` and `ChatHandler` using
> navigator-auth's `@requires_permission` decorator. This enforces real-time policy
> evaluation (business hours, groups, programs) before any agent interaction.
>
> Implements Spec Module 4.

---

## Scope

- Add `@requires_permission(resource_type=ResourceType.AGENT, action="agent:chat",
  resource_name_param="agent_id")` decorator to `AgentTalk` POST and PATCH handlers
- Add same decorator to `ChatHandler` POST handler
- Ensure 403 response includes `EvaluationResult.reason` for clear error messages
- Verify that the decorator correctly extracts `agent_id` from the request URL
  (route parameter) and uses it as `resource_name`

**NOT in scope**:
- Tool filtering (TASK-538)
- Dataset filtering (TASK-539)
- MCP filtering (TASK-540)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/agent.py` | MODIFY | Add `@requires_permission` to AgentTalk POST/PATCH |
| `parrot/handlers/chat.py` | MODIFY | Add `@requires_permission` to ChatHandler POST |
| `tests/auth/test_agent_guard.py` | CREATE | Tests for agent access guard |

---

## Implementation Notes

### Pattern to Follow
```python
# In parrot/handlers/agent.py
from navigator_auth.abac.decorators import requires_permission
from navigator_auth.abac.policies.resources import ResourceType

@is_authenticated()
@user_session()
class AgentTalk(BaseView):

    @requires_permission(
        resource_type=ResourceType.AGENT,
        action="agent:chat",
        resource_name_param="agent_id",
    )
    async def post(self):
        """Main chat endpoint — now PBAC-guarded."""
        ...

    @requires_permission(
        resource_type=ResourceType.AGENT,
        action="agent:configure",
        resource_name_param="agent_id",
    )
    async def patch(self):
        """Configure tools/MCP servers — now PBAC-guarded."""
        ...
```

### Key Constraints
- `@requires_permission` must come AFTER `@is_authenticated()` / `@user_session()`
  (session must be resolved before PBAC can evaluate)
- The decorator extracts `agent_id` from request match_info (URL route parameter)
- 403 response must include reason text from EvaluationResult
- If PBAC is not initialized (no policies), the decorator should allow access (graceful degradation)
- PATCH uses `action="agent:configure"` (stricter than chat)

### References in Codebase
- `parrot/handlers/agent.py` — `AgentTalk` class (lines with POST/PATCH)
- `parrot/handlers/chat.py` — `ChatHandler` class
- `navigator_auth/abac/decorators.py` — `@requires_permission` decorator implementation

---

## Acceptance Criteria

- [ ] `AgentTalk.post()` guarded by `@requires_permission(ResourceType.AGENT, "agent:chat")`
- [ ] `AgentTalk.patch()` guarded by `@requires_permission(ResourceType.AGENT, "agent:configure")`
- [ ] `ChatHandler.post()` guarded by `@requires_permission(ResourceType.AGENT, "agent:chat")`
- [ ] 403 response includes policy denial reason
- [ ] Agent access allowed for authorized user/group
- [ ] Agent access denied outside business hours (when policy configured)
- [ ] Agent access denied for wrong group
- [ ] Graceful degradation: no PBAC → access allowed (backward compatible)
- [ ] Tests pass: `pytest tests/auth/test_agent_guard.py -v`

---

## Test Specification

```python
import pytest
from aiohttp import web
from parrot.handlers.agent import AgentTalk


class TestAgentAccessGuard:
    async def test_agent_access_allowed(self, client, auth_headers_engineering):
        """Engineering user can access agent during business hours."""
        resp = await client.post(
            "/api/v1/agents/chat/test_agent",
            headers=auth_headers_engineering,
            json={"message": "hello"},
        )
        assert resp.status != 403

    async def test_agent_access_denied_group(self, client, auth_headers_guest):
        """Guest user denied access to restricted agent."""
        resp = await client.post(
            "/api/v1/agents/chat/restricted_agent",
            headers=auth_headers_guest,
            json={"message": "hello"},
        )
        assert resp.status == 403

    async def test_agent_configure_denied(self, client, auth_headers_engineering):
        """Engineering user denied configure action (only execute allowed)."""
        resp = await client.patch(
            "/api/v1/agents/chat/test_agent",
            headers=auth_headers_engineering,
            json={"tools": []},
        )
        # Depends on policy: engineering may have execute but not configure
        assert resp.status in (200, 403)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-537-agent-access-guard.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: Added _check_pbac_agent_access() helper to AgentTalk (agent:chat in post(),
agent:configure in patch()). Added _check_pbac_chatbot_access() to ChatHandler post().
All methods fail-open when PBAC is not configured.

**Deviations from spec**: Used inline PolicyEvaluator.check_access() calls instead of
@requires_permission decorator because navigator-auth 0.18.5 decorator requires EvalContext
injection. Import of requires_permission included for forward compatibility.
