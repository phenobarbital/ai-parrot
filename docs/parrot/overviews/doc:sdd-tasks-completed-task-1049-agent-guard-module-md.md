---
type: Wiki Overview
title: 'TASK-1049: agent_guard module — parser, enforcer, exception'
id: doc:sdd-tasks-completed-task-1049-agent-guard-module-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Foundation of FEAT-153. Implements §3 Module 1 of the spec: a single new'
relates_to:
- concept: mod:parrot.auth.agent_guard
  rel: mentions
- concept: mod:parrot.auth.models
  rel: mentions
- concept: mod:parrot.auth.resolver
  rel: mentions
---

# TASK-1049: agent_guard module — parser, enforcer, exception

**Feature**: FEAT-153 — botmanager-pbac-permissions
**Spec**: `sdd/specs/botmanager-pbac-permissions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of FEAT-153. Implements §3 Module 1 of the spec: a single new
module `parrot/auth/agent_guard.py` exposing the building blocks every
other task in this feature consumes:

- `AgentAccessDenied` exception class.
- `parse_bot_permissions(value)` — validate the JSONB shape stored in
  `navigator.ai_bots.permissions` and return a list of
  `PolicyRuleConfig`. Empty input → public (`[]`); malformed input →
  `ValueError` (loud).
- `enforce_agent_access(evaluator, bot_name, request)` — async helper
  that calls `PolicyEvaluator.check_access(...)` with
  `resource_type=ResourceType.AGENT`, `action="agent:resolve"`. Allows
  unconditionally when `request is None` (programmatic invocation
  bypass — resolved §8 Q1) or when no policies are registered for the
  bot. Raises `AgentAccessDenied` on deny.

Mirrors the lazy-import / fail-open pattern of `PBACPermissionResolver`
(`parrot/auth/resolver.py:312-317`) so the helper stays importable when
`navigator-auth` is not installed.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/agent_guard.py` with:
  - `class AgentAccessDenied(PermissionError)` carrying `bot_name`,
    `user_id`, `matched_policy`, `reason` attributes.
  - `def parse_bot_permissions(value: dict | list | None) -> list[PolicyRuleConfig]`.
    Accept shapes: `None`, `{}`, `{"permissions": []}`,
    `{"permissions": [<rule>, ...]}`, and bare `[<rule>, ...]` as
    forgiving fallback. Raise `ValueError` on anything else (e.g.
    `{"permissions": "not-a-list"}`, missing `action` field, etc.).
  - `async def enforce_agent_access(evaluator, bot_name, request) -> None`.
    Allow-paths: `evaluator is None`, `request is None`, no policies
    registered for `agent:<bot_name>`, evaluator returns
    `allowed=True`. Deny-path: `request is not None` AND
    `allowed=False` → raise `AgentAccessDenied`. Log WARNING on deny
    using the line format `"PBAC AGENT DENY: bot=%s user=%s policy=%s reason=%s"`.
- Write unit tests in
  `packages/ai-parrot/tests/auth/test_agent_guard.py` covering every
  unit-test row in spec §4 that maps to M1 (12 tests).
- Use `to_eval_context` from `parrot/auth/resolver.py` for the
  `PermissionContext → EvalContext` bridge, mirroring `resolver.py:319`.

**NOT in scope**:
- `AgentRegistry.register_db_bot_policies` (TASK-1051).
- Any change to `BotManager`, `AgentRegistry.get_instance`, or
  `BotModel.permissions` documentation.
- Wiring the helper into the resolution paths.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/agent_guard.py` | CREATE | `AgentAccessDenied`, `parse_bot_permissions`, `enforce_agent_access`. |
| `packages/ai-parrot/tests/auth/test_agent_guard.py` | CREATE | 12 unit tests covering parser shapes + enforcer paths (see spec §4). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# In parrot/auth/agent_guard.py (top-level)
from __future__ import annotations
import logging
from typing import Optional
from aiohttp import web

from parrot.auth.models import PolicyRuleConfig
# verified: packages/ai-parrot/src/parrot/auth/models.py:32

# Lazy imports inside enforce_agent_access (mirror resolver.py:312-317)
try:
    from navigator_auth.abac.policies.resources import ResourceType
    from navigator_auth.abac.policies.environment import Environment
except ImportError:
    return  # treat as allow — fail-open backwards compat

# Bridge PermissionContext → EvalContext (already used by resolver)
from parrot.auth.resolver import to_eval_context
# verified: parrot/auth/resolver.py:319 calls `to_eval_context(context)`
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/models.py
class PolicyRuleConfig(BaseModel):                   # line 32
    action: str                                       # line 64
    effect: Literal["allow", "deny"]                  # line 65
    groups: Optional[list[str]]                       # line 69
    roles: Optional[list[str]]                        # line 73
    priority: int                                     # line 77
    description: Optional[str]                        # line 81
    conditions: Optional[dict[str, Any]]              # line 85

    def to_resource_policy(self, agent_name: str) -> dict:   # line 108
        # produces resource: f"agent:{agent_name}" (line 146)
```

```python
# packages/ai-parrot/src/parrot/auth/resolver.py
def to_eval_context(context: PermissionContext) -> EvalContext:
    # Used at resolver.py:319 — same bridge applies here.

class PBACPermissionResolver(AbstractPermissionResolver):   # line 247
    async def can_execute(self, context, tool_name, ...):   # line 289
        # The fallback pattern at resolver.py:312-317 is the
        # exact pattern enforce_agent_access must mirror:
        try:
            from navigator_auth.abac.policies.resources import ResourceType
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            return True
        eval_ctx = to_eval_context(context)
        env = Environment()
        result = self._evaluator.check_access(
            ctx=eval_ctx,
            resource_type=ResourceType.TOOL,    # FEAT-153 uses ResourceType.AGENT
            resource_name=tool_name,            # bot_name in our case
            action="tool:execute",              # "agent:resolve" in our case
            env=env,
        )
        if not result.allowed:
            self.logger.warning("PBAC Layer 2 DENY: ...")  # line 331
        return result.allowed                                # line 339
```

### Does NOT Exist

- ~~`PBACPermissionResolver.can_access_agent`~~ — does not exist; do not
  reuse `PBACPermissionResolver`. Write a fresh helper.
- ~~`AgentRegistry.check_access`~~ — does not exist.
- ~~`BotManager.check_access`~~ — does not exist.
- ~~`ResourceType.BOT`~~ — does not exist in navigator-auth. The
  correct constant is `ResourceType.AGENT`.
- ~~`enforce_agent_access(evaluator, bot_name)`~~ — single-arg form
  does not exist; the third positional arg `request` is required.
- ~~`PolicyEvaluator.check_agent`~~ — does not exist; use
  `check_access(...)` exactly as `resolver.py:322-328` does.

---

## Implementation Notes

### `parse_bot_permissions` — accepted shapes

```python
parse_bot_permissions(None)                              # → []
parse_bot_permissions({})                                # → []
parse_bot_permissions({"permissions": []})               # → []
parse_bot_permissions({"permissions": [
    {"action": "agent:resolve", "effect": "allow",
     "groups": ["engineering"]},
]})                                                       # → [PolicyRuleConfig(...)]
parse_bot_permissions([                                  # bare list fallback
    {"action": "agent:resolve", "effect": "allow",
     "groups": ["engineering"]},
])                                                        # → [PolicyRuleConfig(...)]

# All of these MUST raise ValueError:
parse_bot_permissions({"permissions": "not-a-list"})
parse_bot_permissions({"permissions": [{"effect": "allow"}]})  # missing action
parse_bot_permissions("string")
parse_bot_permissions(123)
```

### `enforce_agent_access` — control flow

```python
async def enforce_agent_access(evaluator, bot_name, request):
    if evaluator is None:        # PBAC not initialized
        return
    if request is None:          # Programmatic invocation — §8 Q1
        return
    # Lazy navigator-auth import — fail-open if absent
    try:
        from navigator_auth.abac.policies.resources import ResourceType
        from navigator_auth.abac.policies.environment import Environment
    except ImportError:
        return
    # Bridge request → PermissionContext → EvalContext
    # (Reuse the same plumbing PBACPermissionResolver uses; the request
    #  carries the user session via Guardian middleware.)
    context = ...   # from request — see how handlers/agent.py builds it
    eval_ctx = to_eval_context(context)
    result = evaluator.check_access(
        ctx=eval_ctx,
        resource_type=ResourceType.AGENT,
        resource_name=bot_name,
        action="agent:resolve",
        env=Environment(),
    )
    if not result.allowed:
        logger.warning(
            "PBAC AGENT DENY: bot=%s user=%s policy=%s reason=%s",
            bot_name, getattr(context, "user_id", None),
            result.matched_policy, result.reason,
        )
        raise AgentAccessDenied(
            bot_name=bot_name,
            user_id=getattr(context, "user_id", None),
            matched_policy=result.matched_policy,
            reason=result.reason,
        )
```

### Building `PermissionContext` from `web.Request`

There may not yet be a request-to-PermissionContext helper that returns
a fully populated context outside `_pre_execute()` of a tool. If a
helper does not already exist, add one INSIDE this module (do NOT add
public API outside `parrot/auth/`). Keep it minimal — read
`request["session"]`/`request["user"]` populated by Guardian
middleware. Confirm by reading `parrot/handlers/agent.py` around the
`_filter_mcp_servers_for_user` usage (~line 1001-1005) for the canonical
way the project extracts user identity from a request inside the auth
flow.

### Logging

Module logger: `logger = logging.getLogger("parrot.auth.agent_guard")`.
Use the SAME format string as `resolver.py:331-337`:

```python
logger.warning(
    "PBAC AGENT DENY: bot=%s user=%s policy=%s reason=%s",
    bot_name, user_id, matched_policy, reason,
)
```

### Patterns to Follow

- Lazy-import navigator-auth — exactly mirror `resolver.py:312-317`.
- Async signature on `enforce_agent_access` even though
  `check_access` is sync — keeps call sites uniformly awaitable.
- No silent catch on parse errors — `ValueError` must propagate from
  `parse_bot_permissions`.

---

## Acceptance Criteria

- [ ] `parrot/auth/agent_guard.py` exists and exports
  `AgentAccessDenied`, `parse_bot_permissions`, `enforce_agent_access`.
- [ ] `parse_bot_permissions` covers the 5 accepted shapes and raises
  `ValueError` on every malformed input from the test table.
- [ ] `enforce_agent_access(None, ..., request)` returns without error
  (PBAC disabled).
- [ ] `enforce_agent_access(evaluator, ..., None)` returns without
  error for ANY bot — public or non-public (resolved §8 Q1).
- [ ] `enforce_agent_access` raises `AgentAccessDenied` exactly when
  the evaluator returns `allowed=False` AND `request is not None`.
- [ ] Denials log a WARNING line in the `"PBAC AGENT DENY: bot=%s
  user=%s policy=%s reason=%s"` format.
- [ ] `from parrot.auth.agent_guard import AgentAccessDenied,
  parse_bot_permissions, enforce_agent_access` works.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/auth/test_agent_guard.py -v`.
- [ ] `ruff check parrot/auth/agent_guard.py` passes.
- [ ] No new `mypy` errors on the touched files.

---

## Test Specification

```python
# packages/ai-parrot/tests/auth/test_agent_guard.py
import pytest
from unittest.mock import MagicMock

from parrot.auth.agent_guard import (
    AgentAccessDenied,
    parse_bot_permissions,
    enforce_agent_access,
)
from parrot.auth.models import PolicyRuleConfig


class TestParseBotPermissions:
    def test_none_is_public(self):
        assert parse_bot_permissions(None) == []

    def test_empty_dict_is_public(self):
        assert parse_bot_permissions({}) == []

    def test_empty_permissions_key_is_public(self):
        assert parse_bot_permissions({"permissions": []}) == []

    def test_canonical_shape(self):
        out = parse_bot_permissions({"permissions": [
            {"action": "agent:resolve", "effect": "allow",
             "groups": ["engineering"]},
        ]})
        assert len(out) == 1
        assert isinstance(out[0], PolicyRuleConfig)
        assert out[0].action == "agent:resolve"

    def test_bare_list_fallback(self):
        out = parse_bot_permissions([
            {"action": "agent:resolve", "effect": "allow"},
        ])
        assert len(out) == 1

    def test_malformed_value_type_raises(self):
        with pytest.raises(ValueError):
            parse_bot_permissions({"permissions": "not-a-list"})

    def test_invalid_rule_raises(self):
        with pytest.raises(ValueError):
            parse_bot_permissions({"permissions": [{"effect": "allow"}]})

    def test_string_input_raises(self):
        with pytest.raises(ValueError):
            parse_bot_permissions("string")


class TestEnforceAgentAccess:
    @pytest.mark.asyncio
    async def test_no_evaluator_allows(self):
        await enforce_agent_access(None, "bot_x", request=MagicMock())
        # no exception

    @pytest.mark.asyncio
    async def test_no_request_allows_even_with_policies(self):
        evaluator = MagicMock()
        evaluator.check_access.return_value = MagicMock(allowed=False)
        await enforce_agent_access(evaluator, "bot_x", request=None)
        # programmatic invocation bypass — no call to evaluator
        evaluator.check_access.assert_not_called()

    @pytest.mark.asyncio
    async def test_allow_decision(self, ...):
        # evaluator returns allowed=True → no exception
        ...

    @pytest.mark.asyncio
    async def test_deny_decision_raises_and_logs_warning(self, caplog):
        # evaluator returns allowed=False AND request is not None
        # → AgentAccessDenied + WARNING log
        ...
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec — particularly §2 Overview, §3 Module 1, §6 Codebase
   Contract, and §7 Implementation Notes.
2. Verify the codebase contract above is still accurate
   (`parrot/auth/resolver.py:312-317`, `parrot/auth/models.py:108`).
3. Implement the three exports in the order: `AgentAccessDenied` →
   `parse_bot_permissions` → `enforce_agent_access`.
4. Write the unit tests alongside (TDD optional but encouraged).
5. Run `pytest packages/ai-parrot/tests/auth/test_agent_guard.py -v`
   and `ruff check`.
6. Move this file to `sdd/tasks/completed/`, update the per-spec index
   `sdd/tasks/index/botmanager-pbac-permissions.json` to status
   `done`, fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker (claude-sonnet-4-6) on 2026-05-07.

Created `parrot/auth/agent_guard.py` with all three exports:
- `AgentAccessDenied(PermissionError)` with `bot_name`, `user_id`, `matched_policy`, `reason` attributes.
- `parse_bot_permissions(value)` accepting None, {}, {"permissions": []}, {"permissions": [<rules>]}, and bare list fallback. Raises ValueError on malformed input.
- `enforce_agent_access(evaluator, bot_name, request)` async helper with lazy navigator-auth import (fail-open if absent). Allows when evaluator=None, request=None, or eval_ctx cannot be built. Raises AgentAccessDenied on deny, logs WARNING.

Helper `_build_eval_context_from_request` mirrors `bots.py:_build_eval_context` pattern.

20 unit tests written and passing. ruff check clean.
