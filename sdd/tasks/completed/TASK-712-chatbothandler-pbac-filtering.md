# TASK-712: ChatbotHandler PBAC Filtering

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-708
**Assigned-to**: unassigned

---

## Context

> Adds PBAC-based filtering to ChatbotHandler so users only see agents they're
> authorized to access. `_get_all()` uses batch filtering, `_get_one()` uses
> single check with 403 on denial. Implements Spec Module 6.

---

## Scope

- Add a private `_build_eval_context()` method to ChatbotHandler (following the pattern
  from `agent.py:356-388`). Extracts session from `self.request`, builds `EvalContext`.
- Modify `_get_one(name)` (bots.py:454):
  1. Get evaluator from `self.request.app.get('abac')`.
  2. If evaluator exists, build EvalContext, call `evaluator.check_access(ctx, ResourceType.AGENT, name, "agent:list")`.
  3. If denied → return 403 error response.
  4. If no evaluator → proceed as before (fail-open).
- Modify `_get_all()` (bots.py:475):
  1. Collect all agent names from DB + registry.
  2. If evaluator exists, build EvalContext, call `evaluator.filter_resources(ctx, ResourceType.AGENT, agent_names, "agent:list")`.
  3. Filter the agents list to only include allowed names.
  4. If no evaluator → return all (fail-open).
- Use graceful import guards for navigator-auth imports.
- Write unit tests.

**NOT in scope**: ToolList, retrieval(), AgentRegistry.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/bots.py` | MODIFY | Add PBAC filtering to ChatbotHandler |
| `tests/handlers/test_chatbothandler_pbac.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# navigator-auth (verified: parrot/handlers/agent.py imports)
from navigator_auth.abac.policies.resources import ResourceType
from navigator_auth.abac.context import EvalContext
from navigator_auth.conf import AUTH_SESSION_OBJECT

# navigator-session (verified: parrot/handlers/agent.py)
from navigator_session import get_session
```

### Existing Signatures to Use
```python
# parrot/handlers/bots.py:441-452
async def get(self):
    await self.session()
    agent_name = self._agent_name_from_request()
    if agent_name:
        return await self._get_one(agent_name)
    return await self._get_all()

# parrot/handlers/bots.py:454-473
async def _get_one(self, name: str):
    db_agent = await self._get_db_agent(name)
    # ... returns agent or 404

# parrot/handlers/bots.py:475-498
async def _get_all(self):
    agents = []
    seen_names: set[str] = set()
    db_agents = await self._get_db_agents()
    # ... merges DB + registry agents

# parrot/handlers/agent.py:356-388 — PATTERN TO FOLLOW
async def _build_eval_context(self) -> Any:
    session = self.request.session if hasattr(self.request, 'session') else None
    if session is None:
        session = await get_session(self.request)
    userinfo = session.get(AUTH_SESSION_OBJECT, {})
    return EvalContext(
        username=userinfo.get('username', ''),
        groups=set(userinfo.get('groups', [])),
        roles=set(userinfo.get('roles', [])),
        programs=userinfo.get('programs', []),
    )

# PDP/evaluator access:
# self.request.app.get('abac') → PDP or None
# pdp._evaluator → PolicyEvaluator
# evaluator.check_access(ctx, resource_type, resource_name, action) → EvaluationResult
# evaluator.filter_resources(ctx, resource_type, resource_names, action) → FilterResult
```

### Does NOT Exist
- ~~`ChatbotHandler._is_agent_allowed()`~~ — does not exist (user-provided patch, never merged)
- ~~`ChatbotHandler._build_eval_context()`~~ — does not exist yet, must be created
- ~~`Guardian.filter_tools()`~~ — not implemented in navigator-auth yet
- ~~`self.request.app['abac']._evaluator.filter_agents()`~~ — no such method

---

## Implementation Notes

### Pattern to Follow
```python
# Graceful import at module top:
try:
    from navigator_auth.abac.policies.resources import ResourceType as _ResourceType
    from navigator_auth.abac.context import EvalContext as _EvalContext
    from navigator_auth.conf import AUTH_SESSION_OBJECT as _AUTH_SESSION
    _PBAC_AVAILABLE = True
except ImportError:
    _ResourceType = _EvalContext = _AUTH_SESSION = None
    _PBAC_AVAILABLE = False
```

### Key Constraints
- Fail-open: if PDP not configured or session unavailable, return all agents (no filtering).
- Use `self.error(response={"message": "Access denied"}, status=403)` for denial (not raise).
- Batch filter in `_get_all()` for efficiency — avoid N individual check_access calls.
- Log denials at INFO level for audit.

---

## Acceptance Criteria

- [ ] `_get_one()` returns 403 when PBAC denies agent:list
- [ ] `_get_all()` filters out denied agents
- [ ] Both methods work normally when PDP absent (fail-open)
- [ ] Tests pass: `pytest tests/handlers/test_chatbothandler_pbac.py -v`

---

## Test Specification

```python
# tests/handlers/test_chatbothandler_pbac.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestChatbotHandlerPBAC:
    async def test_get_one_allowed(self):
        """_get_one returns agent when evaluator allows."""

    async def test_get_one_denied(self):
        """_get_one returns 403 when evaluator denies."""

    async def test_get_one_no_pbac(self):
        """_get_one returns agent when PDP absent."""

    async def test_get_all_filters_denied(self):
        """_get_all excludes denied agents from listing."""

    async def test_get_all_no_pbac_returns_all(self):
        """_get_all returns all agents when PDP absent."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md`
2. **Check dependencies** — verify TASK-708 is done
3. **Verify** `_get_one` and `_get_all` are still at bots.py:454 and 475
4. **Implement** the filtering logic
5. **Move** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
