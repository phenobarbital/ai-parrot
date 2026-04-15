# TASK-708: AbstractBot Policy API — Remove _permissions, Add policy_rules, Rewrite retrieval()

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-707
**Assigned-to**: unassigned

---

## Context

> This is the core task. Removes the legacy `_permissions` RBAC system from AbstractBot
> and replaces `retrieval()` with PBAC delegation. Adds `policy_rules` class attribute
> and `get_policy_rules()` method. Implements Spec Modules 2.

---

## Scope

- Remove `_permissions` initialization (abstract.py:333-337).
- Remove `default_permissions()` method (abstract.py:644-667).
- Remove `permissions()` property (abstract.py:669-670).
- Remove `kwargs.get('permissions', ...)` from `__init__`.
- Add `policy_rules: ClassVar[list[dict]] = []` class attribute on AbstractBot.
- Add `get_policy_rules(self) -> list[dict]` method that returns `self.__class__.policy_rules`.
- Rewrite `retrieval()` (abstract.py:2213-2296) to:
  1. Build `RequestContext` and `RequestBot` wrapper (keep existing).
  2. Get PDP evaluator from `app['abac']._evaluator` (or `request.app['abac']`).
  3. If evaluator is None → allow-all (fail-open, backward compat).
  4. Build `EvalContext` from session (follow `agent.py:_build_eval_context()` pattern).
  5. Call `evaluator.check_access(ctx, ResourceType.AGENT, self.name, "agent:chat")`.
  6. If denied → raise `HTTPUnauthorized` with `result.reason`.
  7. If allowed → yield wrapper with semaphore (keep existing).
- Do NOT hardcode superuser bypass — let `defaults.yaml:allow_superuser_all` handle it.
- Write unit tests for the new retrieval logic.

**NOT in scope**: ChatbotHandler, ToolList, AgentRegistry, BotConfig changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/abstract.py` | MODIFY | Remove _permissions, add policy_rules, rewrite retrieval() |
| `tests/bots/test_abstractbot_policy.py` | CREATE | Unit tests for policy API and retrieval |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# navigator-auth ABAC (verified: parrot/auth/pbac.py:28-31, parrot/handlers/agent.py)
from navigator_auth.abac.policies.resources import ResourceType    # verified
from navigator_auth.abac.policies.evaluator import PolicyEvaluator # verified
from navigator_auth.abac.context import EvalContext                # verified
from navigator_auth.abac.policies.environment import Environment   # verified
from navigator_auth.conf import AUTH_SESSION_OBJECT                # verified

# navigator-session (verified: parrot/handlers/agent.py:356)
from navigator_session import get_session
```

### Existing Signatures to Use
```python
# parrot/bots/abstract.py:92-98
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, ToolInterface, VectorInterface, ABC):
    pass

# parrot/bots/abstract.py:333-337 (TO BE REMOVED)
_default = self.default_permissions()
_permissions = kwargs.get('permissions', _default)
self._permissions = {**_default, **_permissions}

# parrot/bots/abstract.py:644-670 (TO BE REMOVED)
def default_permissions(self) -> dict: ...
def permissions(self): return self._permissions

# parrot/bots/abstract.py:2213-2296 (TO BE REWRITTEN)
@asynccontextmanager
async def retrieval(
    self,
    request: web.Request = None,
    app: Optional[Any] = None,
    llm: Optional[Any] = None,
    **kwargs
) -> AsyncIterator["RequestBot"]:
    # Lines 2236-2242: RequestContext + RequestBot creation (KEEP)
    # Lines 2244-2283: Permission evaluation (REPLACE with PBAC)
    # Lines 2291-2296: Semaphore + yield (KEEP)

# parrot/handlers/agent.py:356-388 — PATTERN TO FOLLOW for EvalContext building
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
```

### Does NOT Exist
- ~~`AbstractBot.policy_rules`~~ — does not exist yet, must be added
- ~~`AbstractBot.get_policy_rules()`~~ — does not exist yet, must be added
- ~~`PolicyEvaluator.add_policy()`~~ — does not exist; use `load_policies(list)`
- ~~`BotManager.set_default_resolver()`~~ — referenced in app.py comment but NOT implemented

---

## Implementation Notes

### Pattern to Follow
```python
# EvalContext building pattern from agent.py:356-388
# Adapt for retrieval() which has request as parameter, not self.request

# Graceful import guard pattern:
try:
    from navigator_auth.abac.policies.resources import ResourceType as _ResourceType
    _PBAC_AVAILABLE = True
except ImportError:
    _ResourceType = None
    _PBAC_AVAILABLE = False
```

### Key Constraints
- `retrieval()` signature MUST NOT change — it's called by many handlers.
- Fail-open when PDP not configured (evaluator is None): allow all.
- Fail-closed when PDP is present and denies: raise HTTPUnauthorized.
- Use `app` parameter (passed to retrieval) or `request.app` to get PDP.
- Superuser bypass: do NOT hardcode — `defaults.yaml:allow_superuser_all` at priority 100 handles it.
- Wrap PBAC check in try/except — if evaluator raises, log warning and allow (fail-open on errors).

---

## Acceptance Criteria

- [ ] `_permissions`, `default_permissions()`, `permissions()` removed from AbstractBot
- [ ] `policy_rules` class attribute exists on AbstractBot
- [ ] `get_policy_rules()` method returns class attribute by default
- [ ] `retrieval()` uses `evaluator.check_access()` instead of inline RBAC
- [ ] `retrieval()` allows all when PDP not configured
- [ ] `retrieval()` raises HTTPUnauthorized when PDP denies
- [ ] Tests pass: `pytest tests/bots/test_abstractbot_policy.py -v`

---

## Test Specification

```python
# tests/bots/test_abstractbot_policy.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAbstractBotPolicyRules:
    def test_policy_rules_class_attr_default_empty(self):
        """AbstractBot.policy_rules defaults to empty list."""

    def test_policy_rules_subclass_override(self):
        """Subclass can declare policy_rules."""

    def test_get_policy_rules_returns_class_attr(self):
        """get_policy_rules() returns the class attribute."""

    def test_get_policy_rules_override(self):
        """Subclass can override get_policy_rules() for dynamic rules."""


class TestRetrievalPBAC:
    async def test_retrieval_allowed_by_evaluator(self):
        """retrieval() yields wrapper when evaluator allows."""

    async def test_retrieval_denied_by_evaluator(self):
        """retrieval() raises HTTPUnauthorized when evaluator denies."""

    async def test_retrieval_no_pdp_allows_all(self):
        """retrieval() allows all when app['abac'] is absent."""

    async def test_retrieval_evaluator_error_fails_open(self):
        """retrieval() allows on evaluator exception (fail-open)."""

    def test_permissions_removed(self):
        """_permissions, default_permissions(), permissions() no longer exist."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md` for full context
2. **Check dependencies** — verify TASK-707 is in `tasks/completed/`
3. **Verify the Codebase Contract** — read `abstract.py` lines 333-337, 644-670, 2213-2296 to confirm still as described
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-708-abstractbot-policy-api.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
