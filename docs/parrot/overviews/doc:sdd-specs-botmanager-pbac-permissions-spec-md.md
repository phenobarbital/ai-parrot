---
type: Wiki Overview
title: 'Feature Specification: BotManager / AgentRegistry PBAC Enforcement via `ai_bots.permissions`'
id: doc:sdd-specs-botmanager-pbac-permissions-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The PBAC/ABAC stack of `ai-parrot` (`PolicyEvaluator`, `PDP`, `Guardian`,
relates_to:
- concept: mod:parrot.auth.models
  rel: mentions
- concept: mod:parrot.handlers.models
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: BotManager / AgentRegistry PBAC Enforcement via `ai_bots.permissions`

**Feature ID**: FEAT-153
**Date**: 2026-05-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

### Problem Statement

The PBAC/ABAC stack of `ai-parrot` (`PolicyEvaluator`, `PDP`, `Guardian`,
`PBACPermissionResolver`) already protects HTTP handlers, tools, and — pending
FEAT-151 — datasets. **It does not protect bot resolution itself.** Any caller
that holds a reference to `BotManager` or `AgentRegistry` can resolve any
registered bot, regardless of identity or group:

- `BotManager.get_bot(name)` (`packages/ai-parrot/src/parrot/manager/manager.py:575`)
  returns the bot from `self._bots` cache or falls through to the registry
  with no authorization check.
- `AgentRegistry.get_instance(name)` (`packages/ai-parrot/src/parrot/registry/registry.py:528`)
  returns the lazily-instantiated bot with no authorization check.

The same registry already loads policies declared via the class attribute
`policy_rules` and via `BotConfig.policies` (YAML) into the shared
`PolicyEvaluator` at startup, through
`AgentRegistry._collect_and_register_policies()`
(`registry.py:337`). Bots that originate from the **database**
(`navigator.ai_bots` rows loaded by `BotManager._load_database_bots()`)
have no equivalent path: their `permissions` JSONB column is read into the
constructor at `manager.py:407` but no consumer of that field exists in the
auth code path.

The `permissions` field on `BotModel` (`bots.py:272-276`) is therefore
dead weight today — the column exists, defaults to `{}`, but is silently
ignored by enforcement.

This spec closes the gap. It defines the schema for the `permissions` JSONB
column, registers DB-loaded policies into the same evaluator that already
serves YAML/code-declared bots, and adds enforcement at both bot-resolution
entry points.

### Goals

- Define and document the JSON shape stored in the `navigator.ai_bots.permissions`
  column.
- Treat **empty** (`{}`, `null`, missing, or `{"permissions": []}`) as
  **public** — every authenticated caller is allowed.
- Treat **non-empty** as **deny-by-default** — only callers matching an
  `effect: allow` rule are permitted; `effect: deny` rules override allows.
- Bots loaded from `navigator.ai_bots` MUST be policy-equivalent to bots
  declared via `@register_agent` or YAML `BotConfig.policies` — same
  evaluator, same dict shape, same priority semantics.
- Add a permission check inside `BotManager.get_bot()` and
  `AgentRegistry.get_instance()` that fails closed (raises) when the caller
  is not allowed.
- Leave `user_bots` resolution untouched. Per-user bots are owner-scoped
  by `(user_id, chatbot_id)` already; they MUST NOT be subjected to the
  new `agent:*` policy check.
- Backwards compatible: existing rows have `permissions = {}` → public →
  no behavior change.

### Non-Goals (explicitly out of scope)

- UI / REST CRUD for editing `ai_bots.permissions`. Editing is done via
  SQL or existing admin tooling.
- New `ResourceType` definitions in `navigator-auth`. The existing
  `agent:<name>` resource pattern (already used by
  `PolicyRuleConfig.to_resource_policy()` at `auth/models.py:108`) is
  reused as-is.
- Any change to the `DatasetManager` enforcement path delivered by FEAT-151.
- Any change to `user_bots` (`navigator.users_bots`) — that table is not
  multi-tenant in the same sense and already has owner-scope enforcement
  via session + `(user_id, chatbot_id)` keying.
- Hot-reload of `ai_bots.permissions` on UPDATE. v1 picks up policies at
  `_load_database_bots()` time. Policy refresh on bot reload is a follow-up.
- Audit pipeline / metrics. Denials are logged at WARNING level (mirrors
  `PBACPermissionResolver` precedent).

---

## 2. Architectural Design

### Overview

A small module (`parrot/auth/agent_guard.py`, new) defines two pieces:

1. A typed parser (`parse_bot_permissions(value: dict | None) -> list[PolicyRuleConfig]`)
   that validates the JSONB shape stored in `ai_bots.permissions` and
   converts it to a list of `PolicyRuleConfig`. Empty / missing input
   returns `[]` (public).
2. An async helper (`enforce_agent_access(evaluator, bot_name, request)
   -> None`) that performs the `check_access(...)` call with
   `resource_type=ResourceType.AGENT`, `action="agent:resolve"`, and
   raises `AgentAccessDenied` when denied. When the evaluator is `None`
   (PBAC not initialized) or no policies are registered for the bot, the
   helper allows.

`AgentRegistry` gains one new public method:

- `register_db_bot_policies(name: str, permissions: dict | list | None) -> int`
  — wraps the existing `self._evaluator.load_policies(...)` plumbing
  (`registry.py:337-415`) so DB-loaded bots produce policies indistinguishable
  from YAML/code-declared ones. Returns the number of policy dicts
  registered (for logging / tests).

`BotManager._load_database_bots()` calls
`self.registry.register_db_bot_policies(bot_model.name, bot_model.permissions)`
right after building `bot_instance` and before storing it in `self._bots`.
This ensures the policies are loaded into the evaluator before any caller
can resolve the bot.

`BotManager.get_bot()` (`manager.py:575`) and
`AgentRegistry.get_instance()` (`registry.py:528`) each invoke
`enforce_agent_access(...)` after they have resolved the bot. The request
object is passed in via a new optional `request` kwarg (default `None`).
When `request is None` (programmatic Python invocation — CLI scripts,
tests, startup, internal crew composition), the helper **allows
unconditionally**, regardless of whether the bot has policies registered.
PBAC enforcement on agent resolution is therefore HTTP-scoped: it only
fires when a request context is present.

`user_bots` flow is left intact: `get_user_bot()` (`manager.py:737`),
`_fetch_user_bot_model()`, and `_build_user_bot_instance()` are not
modified, do not call `enforce_agent_access(...)`, and do not consult
the agent-policy evaluator. They remain owner-scoped by session.

### Component Diagram

```
                   navigator.ai_bots
                          │
                          ▼
        BotManager._load_database_bots()
                          │
        bot_model.permissions ──► AgentRegistry.register_db_bot_policies()
                          │                   │
                          │                   ▼
                          │          PolicyEvaluator  ◄── _collect_and_register_policies()
                          │             (one shared          (YAML BotConfig + class attr)
                          │              instance)
                          ▼
                BotManager._bots[name]

   Caller (handler / crew)
        │
        ▼
   BotManager.get_bot(name, request=req)
        │
        ▼
   enforce_agent_access(evaluator, name, request) ──► PolicyEvaluator.check_access(
        │                                                resource_type=AGENT,
        │  allow                                         resource_name=name,
        ▼                                                action="agent:resolve",
   return bot                                            ctx=user_subject)
        │
        │  deny
        ▼
   raise AgentAccessDenied
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BotModel.permissions` (`handlers/models/bots.py:272`) | re-typed + documented | JSONB shape formalized as `{"permissions": [<rule>, ...]}` |
| `BotManager._load_database_bots` (`manager.py:307`) | extended | calls `registry.register_db_bot_policies(...)` before `add_bot` |
| `BotManager.get_bot` (`manager.py:575`) | extended | accepts `request` kwarg, calls `enforce_agent_access(...)` before return |
| `AgentRegistry._evaluator` (`registry.py:278`) | reused | same evaluator instance used for YAML / class policies |
| `AgentRegistry._collect_and_register_policies` (`registry.py:337`) | precedent | new `register_db_bot_policies` mirrors its dict-shape and `load_policies` call |
| `AgentRegistry.get_instance` (`registry.py:528`) | extended | accepts `request` kwarg, calls `enforce_agent_access(...)` before return |
| `PolicyRuleConfig` (`auth/models.py:32`) | reused | DB rules parse into the same Pydantic model as YAML/code rules |
| `PolicyRuleConfig.to_resource_policy(name)` (`auth/models.py:108`) | reused | produces `resources=["agent:<name>"]`, identical to YAML path |
| `BotManager.get_user_bot` (`manager.py:737`) | **untouched** | user_bots are exempt from agent-policy enforcement |
| Handlers using `@requires_permission(ResourceType.AGENT, ...)` | additive | new check is inside the manager/registry, not a replacement |

### Data Models

```python
# parrot/auth/agent_guard.py — new module

from typing import Optional
from aiohttp import web

from parrot.auth.models import PolicyRuleConfig


class AgentAccessDenied(PermissionError):
    """Raised by enforce_agent_access when PBAC denies bot resolution."""
    bot_name: str
    user_id: Optional[str]
    matched_policy: Optional[str]
    reason: Optional[str]


def parse_bot_permissions(
    value: dict | list | None,
) -> list[PolicyRuleConfig]:
    """Validate and parse the JSONB shape stored in ai_bots.permissions.

    Accepted shapes (all equivalent to "public"):
      - None
      - {}
      - {"permissions": []}

    Accepted shape (deny-by-default with explicit allows):
      - {"permissions": [<PolicyRuleConfig dict>, ...]}

    A bare list is also accepted as a forgiving fallback and treated as
    {"permissions": <list>}. Any other shape raises ValueError so that
    malformed rows fail loudly at load time rather than being silently
    treated as public.

    Returns the parsed PolicyRuleConfig list; empty list means public.
    """


async def enforce_agent_access(
    evaluator: object | None,  # PolicyEvaluator | None
    bot_name: str,
    request: Optional[web.Request],
) -> None:
    """Raise AgentAccessDenied if the request's subject cannot resolve `bot_name`.

    Allow-paths (no exception raised):
      - evaluator is None (PBAC not initialized — backwards compat).
      - request is None (programmatic invocation — Python scripts,
        CLI, tests, internal crew composition). Enforcement is
        HTTP-scoped: no request, no check.
      - no policies registered against resource ``agent:<bot_name>``
        (empty / public).
      - PolicyEvaluator.check_access(...) returns allowed=True.

    Deny-paths (AgentAccessDenied raised):
      - request is provided AND policies are registered AND
        PolicyEvaluator.check_access(...) returns allowed=False.

    The helper logs WARNING on denials, mirroring PBACPermissionResolver.
    """
```

### New Public Interfaces

```python
# parrot/registry/registry.py — additive method on AgentRegistry

class AgentRegistry:
    def register_db_bot_policies(
        self,
        name: str,
        permissions: dict | list | None,
    ) -> int:
        """Register policies for a DB-loaded bot.

        Mirrors ``_collect_and_register_policies`` but takes the raw
        ``permissions`` value read from ``navigator.ai_bots.permissions``.
        Parses it via ``parse_bot_permissions``, converts each entry to a
        policy dict via ``PolicyRuleConfig.to_resource_policy(name)``, and
        loads the result into ``self._evaluator`` via ``load_policies(...)``.

        Returns the count of policy dicts registered (0 means public).
        Raises ValueError if ``permissions`` has a malformed shape.
        """
```

```python
# parrot/manager/manager.py — extended signatures

class BotManager:
    async def get_bot(
        self,
        name: str,
        new: bool = False,
        session_id: str = "",
        request: Optional[web.Request] = None,   # NEW
        **kwargs,
    ) -> AbstractBot:
        """Existing behavior, plus: when policies are registered for `name`,
        validate access against `request` before returning. Raises
        ``AgentAccessDenied`` on deny.
        """

# parrot/registry/registry.py — extended signature

class AgentRegistry:
    async def get_instance(
        self,
        name: str,
        request: Optional[web.Request] = None,   # NEW
        **kwargs,
    ) -> Optional[AbstractBot]:
        """Existing behavior, plus: when policies are registered for `name`,
        validate access against `request` before returning.
        """
```

---

## 3. Module Breakdown

### Module 1: `parrot/auth/agent_guard.py` (new)
- **Path**: `packages/ai-parrot/src/parrot/auth/agent_guard.py`
- **Responsibility**:
  - `AgentAccessDenied` exception class.
  - `parse_bot_permissions(value)` — validate JSONB shape, return
    `list[PolicyRuleConfig]`. Loud failure on malformed input.
  - `enforce_agent_access(evaluator, bot_name, request)` — async
    helper; raises on deny, returns `None` on allow.
- **Depends on**: `parrot/auth/models.py:PolicyRuleConfig`, navigator-auth
  imports done lazily inside the helper (mirror `resolver.py:312-317`).

### Module 2: `BotModel.permissions` schema documentation
- **Path**: `packages/ai-parrot/src/parrot/handlers/models/bots.py:272-276`
- **Responsibility**: Update the `ui_help` docstring on the field to
  describe the accepted JSON shape `{"permissions": [<rule>, ...]}`,
  the empty-means-public rule, and link to `parse_bot_permissions`.
  No DDL change (column is already `JSONB DEFAULT '{}'`).
- **Depends on**: Module 1.

### Module 3: `AgentRegistry.register_db_bot_policies`
- **Path**: `packages/ai-parrot/src/parrot/registry/registry.py` (new
  method on `AgentRegistry`, sibling to `_collect_and_register_policies`
  at line 337).
- **Responsibility**: Public method called by `BotManager` to register
  policies parsed from `ai_bots.permissions`. Reuses
  `self._evaluator.load_policies(...)` plumbing. Logs at INFO with the
  registered count. No-ops cleanly when `self._evaluator is None`.
- **Depends on**: Module 1.

### Module 4: `BotManager._load_database_bots` policy registration
- **Path**: `packages/ai-parrot/src/parrot/manager/manager.py:307-487`
- **Responsibility**: After `bot_instance.configure(app)` succeeds and
  before `add_bot(...)`, call
  `self.registry.register_db_bot_policies(bot_model.name, bot_model.permissions)`.
  A malformed `permissions` raises `ValueError`; the load loop **catches
  it, logs a WARNING, and skips that bot** (the bot is not added to
  `self._bots`). The rest of the load continues — one bad row never
  blocks the whole startup.
- **Depends on**: Modules 1, 3.

### Module 5: `BotManager.get_bot` enforcement
- **Path**: `packages/ai-parrot/src/parrot/manager/manager.py:575-691`
- **Responsibility**: Add `request: Optional[web.Request] = None` kwarg.
  After resolving the bot (both the cache path at `manager.py:670-675`
  and the registry-fallback path at `manager.py:676-690`), call
  `await enforce_agent_access(self.registry._evaluator, name, request)`
  before returning. Let the exception propagate to the caller.
  Existing `new=True` path also goes through enforcement (the new
  instance still represents the same logical bot).
- **Depends on**: Module 1.

### Module 6: `AgentRegistry.get_instance` enforcement
- **Path**: `packages/ai-parrot/src/parrot/registry/registry.py:528-552`
- **Responsibility**: Add `request: Optional[web.Request] = None` kwarg.
  After `metadata.get_instance(**kwargs)` returns, call
  `await enforce_agent_access(self._evaluator, name, request)` before
  returning. Mirror Module 5's exception semantics.
- **Depends on**: Module 1.

### Module 7: `user_bots` exemption — regression test only
- **Path**: tests under
  `packages/ai-parrot/tests/...` (mirror existing test layout for
  `manager`/`registry`).
- **Responsibility**: No code change in the user_bots path. Add a
  regression test that asserts `BotManager.get_user_bot(...)` ignores
  any policies registered against `agent:<chatbot_id>` and returns the
  bot purely on `(user_id, chatbot_id)` match. Document the rationale
  in the test docstring.
- **Depends on**: Modules 4, 5.

### Module 8: Test suite
- **Path**: `packages/ai-parrot/tests/auth/test_agent_guard.py` (new),
  `packages/ai-parrot/tests/manager/test_get_bot_pbac.py` (new),
  `packages/ai-parrot/tests/registry/test_get_instance_pbac.py` (new).
- **Responsibility**: Unit + integration tests covering every acceptance
  criterion in §5.
- **Depends on**: Modules 1–7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_parse_empty_dict_is_public` | M1 | `parse_bot_permissions({})` → `[]` |
| `test_parse_none_is_public` | M1 | `parse_bot_permissions(None)` → `[]` |
| `test_parse_empty_permissions_key_is_public` | M1 | `{"permissions": []}` → `[]` |
| `test_parse_canonical_shape` | M1 | `{"permissions": [{action,...}]}` → list of `PolicyRuleConfig` |
| `test_parse_bare_list_fallback` | M1 | bare `[{...}]` accepted as fallback shape |
| `test_parse_malformed_raises` | M1 | `{"permissions": "not-a-list"}` raises `ValueError` |
| `test_parse_invalid_rule_raises` | M1 | rule missing required `action` raises `ValueError` |
| `test_enforce_no_evaluator_allows` | M1 | `evaluator=None` → no exception (backwards compat) |
| `test_enforce_no_policies_allows` | M1 | bot not registered in evaluator → no exception |
| `test_enforce_no_request_allows_even_with_policies` | M1 | `request=None` + policies registered → no exception (programmatic invocation bypass) |
| `test_enforce_allow_decision` | M1 | evaluator returns allowed=True → no exception |
| `test_enforce_deny_decision_logs_warning` | M1 | evaluator returns allowed=False → `AgentAccessDenied` + WARNING log |
| `test_register_db_bot_policies_loads_into_evaluator` | M3 | DB shape registered → evaluator returns expected policy dict |
| `test_register_db_bot_policies_empty_no_op` | M3 | empty/missing → 0 registered, no evaluator change |
| `test_register_db_bot_policies_no_evaluator_no_op` | M3 | `_evaluator is None` → 0, no error |
| `test_register_db_bot_policies_malformed_raises` | M3 | malformed `permissions` raises `ValueError` |

### Integration Tests
| Test | Description |
|---|---|
| `test_db_bot_policy_parity_with_yaml` | Same `PolicyRuleConfig` registered via DB and via `BotConfig.policies` produces evaluator decisions byte-equal for the same `(user, action)` input. |
| `test_get_bot_empty_permissions_allows_anyone` | DB row with `permissions={}` → `get_bot(name, request=req_user_a)` and `get_bot(name, request=req_user_b)` both succeed. |
| `test_get_bot_allow_by_group` | Rule allows `groups=["engineering"]`; engineering user passes, marketing user gets `AgentAccessDenied`. |
| `test_get_bot_deny_overrides_allow_by_priority` | High-priority deny rule for role `contractors` overrides allow-everyone rule. |
| `test_get_bot_no_request_allows_programmatic_invocation` | Calling `get_bot(name)` without `request` on a non-public bot succeeds — programmatic Python callers are exempt from PBAC. |
| `test_get_instance_mirrors_get_bot` | Same scenario as above through `AgentRegistry.get_instance` produces the SAME decision. |
| `test_db_load_skips_bot_with_malformed_permissions` | Bot row with malformed `permissions` is skipped (not in `self._bots`), a WARNING is logged, and other bots in the same load loop continue to be loaded. |
| `test_user_bot_path_unaffected_by_agent_policies` | Register a deny-all `agent:<chatbot_id>` policy; `BotManager.get_user_bot(request, chatbot_id)` still returns the bot. |

### Test Data / Fixtures

```python
# Shared fixtures

@pytest.fixture
def sample_permissions_public() -> dict:
    return {}

@pytest.fixture
def sample_permissions_engineering() -> dict:
    return {
        "permissions": [
            {"action": "agent:resolve", "effect": "allow",
             "groups": ["engineering"]},
        ],
    }

@pytest.fixture
def sample_permissions_with_deny() -> dict:
    return {
        "permissions": [
            {"action": "agent:resolve", "effect": "allow", "priority": 10,
             "groups": ["engineering", "ops"]},
            {"action": "agent:resolve", "effect": "deny", "priority": 100,
             "roles": ["contractors"]},
        ],
    }

@pytest.fixture
def fake_request_user(group: str, role: str) -> aiohttp.test_utils.make_mocked_request:
    """Mocked aiohttp request whose session resolves to a user with the given group/role."""
    ...
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `parse_bot_permissions(...)` accepts `None`, `{}`, `{"permissions": []}`, `{"permissions": [<rules>]}`, and bare-list fallback; rejects everything else with `ValueError`.
- [ ] A bot row with `permissions = {}` resolves through `BotManager.get_bot(name, request=req)` for **any** authenticated `req` and through `AgentRegistry.get_instance(name, request=req)` for the same `req`.
- [ ] A bot row with non-empty policies denies callers that don't match: `AgentAccessDenied` is raised by both `BotManager.get_bot` and `AgentRegistry.get_instance` for the same `(user, bot)` pair.
- [ ] DB-declared policies and YAML/code-declared policies produce **identical** evaluator decisions for the same input — verified by `test_db_bot_policy_parity_with_yaml`.
- [ ] `BotManager._load_database_bots` calls `register_db_bot_policies` for every loaded bot before `add_bot`. A malformed `permissions` logs WARNING, skips that bot, and lets the load loop continue for the remaining bots — verified by `test_db_load_skips_bot_with_malformed_permissions`.
- [ ] When `request=None` (programmatic Python invocation), both `BotManager.get_bot` and `AgentRegistry.get_instance` succeed for any bot — public or non-public. PBAC enforcement is HTTP-scoped.
- [ ] `BotManager.get_user_bot` (`manager.py:737`) is unchanged and is not affected by any `agent:<name>` policy registered for a same-named user bot — verified by `test_user_bot_path_unaffected_by_agent_policies`.
- [ ] When PBAC is not initialized (`evaluator is None`), all enforcement is no-op (allow). Existing tests / call sites that don't pass `request` keep working.
- [ ] Existing handlers using `@requires_permission(ResourceType.AGENT, ...)` continue to work — the new check is additive, not a replacement.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/auth/test_agent_guard.py -v`).
- [ ] All integration tests pass (`pytest packages/ai-parrot/tests/manager/test_get_bot_pbac.py packages/ai-parrot/tests/registry/test_get_instance_pbac.py -v`).
- [ ] `ruff check` and `mypy` pass on touched files with no new errors.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every reference below was verified by reading the file at the cited
> line at spec time (2026-05-07, branch `dev`). If a number drifts before
> implementation, re-grep before editing.

### Verified Imports

```python
# parrot/auth/agent_guard.py (new) — imports it MUST use
from typing import Optional
from aiohttp import web
from parrot.auth.models import PolicyRuleConfig
# verified: packages/ai-parrot/src/parrot/auth/models.py:32

# Lazy imports (inside enforce_agent_access only, mirror resolver.py:312-317)
from navigator_auth.abac.policies.resources import ResourceType
from navigator_auth.abac.policies.environment import Environment
# Reason: navigator-auth may not be installed — fail open in that case.

# Cross-references already known to work
from parrot.registry import agent_registry, AgentRegistry  # manager.py:53
from parrot.handlers.models import BotModel, UserBotModel  # manager.py:49
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/auth/models.py
class PolicyRuleConfig(BaseModel):                                  # line 32
    action: str                                                      # line 64

…(truncated)…
