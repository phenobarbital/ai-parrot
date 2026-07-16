---
type: Wiki Overview
title: 'TASK-1053: BotManager.get_bot enforcement'
id: doc:sdd-tasks-completed-task-1053-botmanager-get-bot-enforcement-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 5. Adds the actual access check at the primary
relates_to:
- concept: mod:parrot.auth.agent_guard
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
---

# TASK-1053: BotManager.get_bot enforcement

**Feature**: FEAT-153 — botmanager-pbac-permissions
**Spec**: `sdd/specs/botmanager-pbac-permissions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1049
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 5. Adds the actual access check at the primary
bot-resolution entry point. After this task, callers that pass a
`request` will be denied when the request's subject does not match the
bot's policies. Callers that pass `request=None` (programmatic
invocation) keep working unchanged — that is the resolved §8 Q1
behaviour.

The method has up to **three return paths** (`new=True` → fresh
instance; `name in self._bots` → cache hit; `self.registry.has(name)`
→ registry fallback). All three must call `enforce_agent_access(...)`
with the **base** bot name (not the temporary `f"{name}_{session_id}"`
used internally).

---

## Scope

- Modify `BotManager.get_bot()` (`packages/ai-parrot/src/parrot/manager/manager.py:575-691`):
  - Add new optional kwarg `request: Optional[web.Request] = None`.
  - Before each return path, call:
    ```python
    await enforce_agent_access(
        self.registry._evaluator,   # may be None — helper handles it
        name,                        # base bot name, NOT new_name
        request,
    )
    ```
  - Let `AgentAccessDenied` propagate to the caller.
- Identify ALL return paths and gate each one. The three known paths:
  1. `new=True` branch — returns a fresh instance.
  2. Cache-hit at line 670–675 — returns `self._bots[name]`.
  3. Registry-fallback at line 676–690 — returns `bot_instance` from
     `self.registry.get_instance(name)`.
- The `return None` at line 691 (when neither cache nor registry has
  it) does NOT need a check — there is no bot to gate.
- Add integration tests in
  `packages/ai-parrot/tests/manager/test_get_bot_pbac.py`.

**NOT in scope**:
- Changes to `get_user_bot` (it must remain untouched per spec
  §1 Goals).
- `AgentRegistry.get_instance` enforcement (TASK-1054).
- Any change to `_load_database_bots` (TASK-1052 owns that).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Add `request` kwarg to `get_bot`; call `enforce_agent_access` before each return path. |
| `packages/ai-parrot/tests/manager/test_get_bot_pbac.py` | CREATE | 5 integration tests (allow public, deny by group, deny overrides allow, request=None bypass, evaluator=None bypass). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported at parrot/manager/manager.py
from typing import Optional
from aiohttp import web

# New import for this task
from parrot.auth.agent_guard import enforce_agent_access, AgentAccessDenied
# verified: TASK-1049 creates parrot/auth/agent_guard.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:                                    # line 81
    self.registry: AgentRegistry = agent_registry   # line 121

    async def get_bot(                              # line 575
        self,
        name: str,
        new: bool = False,
        session_id: str = "",
        **kwargs,
    ) -> AbstractBot:
        # Three return paths to gate:
        #
        # 1) new=True branch (lines 593-668):
        #    Constructs new_name = f"{name}_{session_id}" or
        #    f"{name}_{int(time.time())}" (line 599) and returns the
        #    fresh instance. Use `name` (the base) for enforcement,
        #    NOT `new_name`.
        #
        # 2) Cache hit (lines 670-675):
        #    if name in self._bots: ... return self._bots[name]
        #
        # 3) Registry fallback (lines 676-690):
        #    if self.registry.has(name):
        #        bot_instance = await self.registry.get_instance(name)
        #        ...
        #        return bot_instance
        #
        # The `return None` at line 691 is the not-found case — no gate.
```

### Does NOT Exist

- ~~`BotManager.can_resolve(name, user)`~~ — does not exist.
- ~~`self.registry.evaluator` (public)~~ — the attribute is private,
  `self.registry._evaluator` (`registry.py:278`). Pass it directly to
  `enforce_agent_access(...)`; the helper accepts `None`.
- ~~Wrapping the whole method body in try/except for `AgentAccessDenied`~~
  — let it propagate. The HTTP layer already handles `PermissionError`
  subclasses.

---

## Implementation Notes

### Signature change

```python
async def get_bot(
    self,
    name: str,
    new: bool = False,
    session_id: str = "",
    request: Optional[web.Request] = None,   # NEW
    **kwargs,
) -> AbstractBot:
```

Keeping the kwarg as keyword-only-default-None keeps every existing
call site working without modification.

### Where to insert the check

For each return path, the gate goes right BEFORE the `return`, after
the bot has been fully prepared:

```python
# Path 1: new=True
new_bot = ...    # build fresh instance (lines 593-668)
await enforce_agent_access(self.registry._evaluator, name, request)
return new_bot

# Path 2: cache hit (around line 675)
if name in self._bots:
    _bot = self._bots[name]
    if not getattr(_bot, "is_configured", False):
        await _bot.configure(self.app)
    await enforce_agent_access(self.registry._evaluator, name, request)
    return self._bots[name]

# Path 3: registry fallback (around line 686)
if self.registry.has(name):
    try:
        bot_instance = await self.registry.get_instance(name)
        if bot_instance:
            if not getattr(bot_instance, "is_configured", False):
                await bot_instance.configure(self.app)
            self.add_bot(bot_instance)
            await enforce_agent_access(self.registry._evaluator, name, request)
            return bot_instance
    except Exception as e:
        self.logger.error(f"Failed to get bot instance from registry: {e}")
return None
```

Note in Path 3: the existing try/except wraps only the
`registry.get_instance(...) → configure → add_bot` chain. Place the
`enforce_agent_access` call OUTSIDE the existing try/except — we want
`AgentAccessDenied` to propagate, not be swallowed by the broad
`except Exception` and logged as "Failed to get bot instance".

### Identity propagation

`enforce_agent_access` extracts identity from `request`. Per TASK-1049
the helper handles `request=None` by allowing. No need to build a
context here — pass the request through.

### Patterns to Follow

- Async/await throughout (already async).
- Use `self.registry._evaluator` directly. The leading underscore is
  intentional; we already access it elsewhere in the auth code.
- Don't catch `AgentAccessDenied` here — let the HTTP layer turn it
  into a 403.

---

## Acceptance Criteria

- [ ] `get_bot(name, request=req)` denies callers whose subject does
  not match registered policies — `AgentAccessDenied` raised.
- [ ] `get_bot(name, request=req)` allows callers whose subject
  matches an allow rule.
- [ ] `get_bot(name)` (no request) allows for ANY bot — public or not
  — confirming the §8 Q1 programmatic-invocation bypass.
- [ ] When PBAC is not initialized (`_evaluator is None`),
  `get_bot(name, request=req)` allows unconditionally.
- [ ] All three return paths (`new=True`, cache-hit, registry-fallback)
  call the enforcement helper.
- [ ] `enforce_agent_access` receives the **base** `name`, not the
  `new_name` constructed inside the `new=True` branch.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/manager/test_get_bot_pbac.py -v`.
- [ ] `ruff check` passes on `parrot/manager/manager.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/manager/test_get_bot_pbac.py
import pytest
from unittest.mock import MagicMock

from parrot.manager.manager import BotManager
from parrot.auth.agent_guard import AgentAccessDenied


@pytest.mark.asyncio
async def test_get_bot_empty_permissions_allows_anyone():
    """permissions={} → any request resolves the bot."""
    ...

@pytest.mark.asyncio
async def test_get_bot_allow_by_group():
    """Engineering user passes an allow-engineering rule; marketing
    user gets AgentAccessDenied."""
    ...

@pytest.mark.asyncio
async def test_get_bot_deny_overrides_allow_by_priority():
    """High-priority deny rule for role 'contractors' wins over
    allow-everyone rule."""
    ...

@pytest.mark.asyncio
async def test_get_bot_no_request_allows_programmatic_invocation():
    """get_bot(name) without request resolves a bot with non-empty
    policies — programmatic Python callers are exempt."""
    ...

@pytest.mark.asyncio
async def test_get_bot_no_evaluator_allows():
    """When self.registry._evaluator is None, get_bot resolves
    regardless of policies in the JSONB."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. Confirm TASK-1049 is done.
2. Read `manager.py:575-691` to make sure you can identify all three
   return paths.
3. Add the `request` kwarg and the three `enforce_agent_access` calls.
4. Pay special attention to passing `name` (not `new_name`) in the
   `new=True` branch.
5. Write the 5 integration tests.
6. Run pytest + ruff.
7. Move this file to `sdd/tasks/completed/`, update the per-spec
   index, fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker (claude-sonnet-4-6) on 2026-05-07.

Added `request: Optional[web.Request] = None` kwarg to `get_bot` signature.
Added `await enforce_agent_access(self.registry._evaluator, name, request)` before
each of the 3 return paths:
  1. `new=True` path (fresh instance)
  2. Cache-hit path (`name in self._bots`)
  3. Registry-fallback path (restructured to place enforcement OUTSIDE the
     existing `try/except Exception` so `AgentAccessDenied` is not swallowed)

Added top-level import: `from ..auth.agent_guard import enforce_agent_access, AgentAccessDenied`

6 integration tests created in `test_get_bot_pbac.py` covering:
  - allow when evaluator has no policies
  - allow when request=None (programmatic bypass)
  - allow when evaluator is None
  - deny raises AgentAccessDenied (with navigator-auth present)
  - cache-hit path enforces
  - request=None skips evaluator call even when evaluator denies

All 6 tests pass. ruff reports no errors on `manager.py`.
