---
type: Wiki Overview
title: 'TASK-1054: AgentRegistry.get_instance enforcement'
id: doc:sdd-tasks-completed-task-1054-agentregistry-get-instance-enforcement-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 6. Mirror of TASK-1053 for the second
relates_to:
- concept: mod:parrot.auth.agent_guard
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

# TASK-1054: AgentRegistry.get_instance enforcement

**Feature**: FEAT-153 — botmanager-pbac-permissions
**Spec**: `sdd/specs/botmanager-pbac-permissions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1049
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 6. Mirror of TASK-1053 for the second
bot-resolution entry point. `AgentRegistry.get_instance(name)` is
called both directly (e.g. by `BotManager.get_bot` registry-fallback
path) and indirectly through other code that holds a registry
reference. After this task, both entry points (`BotManager.get_bot`
and `AgentRegistry.get_instance`) share the SAME enforcement
behaviour for the SAME `(user, bot)` pair — that is the parity
acceptance criterion in spec §5.

This task is smaller than TASK-1053 because the method has only one
return path and the helper is the same.

---

## Scope

- Modify `AgentRegistry.get_instance()` (`packages/ai-parrot/src/parrot/registry/registry.py:528-552`):
  - Add new optional kwarg `request: Optional[web.Request] = None`.
  - After `metadata.get_instance(**kwargs)` returns the instance
    (line 547), call:
    ```python
    await enforce_agent_access(self._evaluator, name, request)
    ```
  - Let `AgentAccessDenied` propagate to the caller. The existing
    `try/except Exception` at lines 546–552 must NOT swallow it —
    place the enforcement call outside that try block.
- Add integration tests in
  `packages/ai-parrot/tests/registry/test_get_instance_pbac.py`.

**NOT in scope**:
- Any other change to `AgentRegistry`.
- Updating `BotManager.get_bot` to forward the `request` to its
  registry-fallback call to `get_instance` — that is part of TASK-1053
  (the `enforce_agent_access` in `get_bot` already covers that path
  before returning, so forwarding `request` to `get_instance` is
  optional and not required for correctness).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | Add `request` kwarg to `get_instance`; call `enforce_agent_access` before return. |
| `packages/ai-parrot/tests/registry/test_get_instance_pbac.py` | CREATE | 4 integration tests mirroring the get_bot suite (allow public, deny by group, no-request bypass, no-evaluator bypass). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present at parrot/registry/registry.py
from typing import Any, Dict, List, Optional

# New imports for this task
from aiohttp import web
from parrot.auth.agent_guard import enforce_agent_access, AgentAccessDenied
# verified: TASK-1049 creates parrot/auth/agent_guard.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:                                   # line 226
    self._evaluator: Any = None                        # line 278
    self._registered_agents: Dict[str, BotMetadata]    # set elsewhere

    async def get_instance(                            # line 528
        self,
        name: str,
        **kwargs,
    ) -> Optional[AbstractBot]:
        if name not in self._registered_agents:        # line 541
            self.logger.warning(...)
            return None
        metadata = self._registered_agents[name]
        try:
            instance = await metadata.get_instance(**kwargs)   # line 547
            self.logger.debug(...)
            return instance                                      # line 549
        except Exception as e:
            self.logger.error(...)
            return None                                          # line 552
```

### Does NOT Exist

- ~~`AgentRegistry.resolve(name, request)`~~ — does not exist.
- ~~`metadata.get_instance(request=request)`~~ — `metadata.get_instance`
  signature is unrelated; it does NOT take a request kwarg. Pass
  request only to `enforce_agent_access`.

---

## Implementation Notes

### Signature change

```python
async def get_instance(
    self,
    name: str,
    request: Optional[web.Request] = None,   # NEW — keyword-only-default
    **kwargs,
) -> Optional[AbstractBot]:
```

### Where to insert the check

```python
async def get_instance(
    self,
    name: str,
    request: Optional[web.Request] = None,
    **kwargs,
) -> Optional[AbstractBot]:
    if name not in self._registered_agents:
        self.logger.warning(f"Bot {name} not found in registry")
        return None

    metadata = self._registered_agents[name]
    try:
        instance = await metadata.get_instance(**kwargs)
        self.logger.debug(f"Retrieved instance for bot: {name}")
    except Exception as e:
        self.logger.error(f"Failed to instantiate bot {name}: {e}")
        return None

    # Enforcement runs AFTER the instance is built but OUTSIDE the
    # try/except above — AgentAccessDenied must propagate to the
    # caller, not be logged as "Failed to instantiate".
    await enforce_agent_access(self._evaluator, name, request)
    return instance
```

### Why split the try/except

The original code (`registry.py:546-552`) wraps both
`metadata.get_instance(**kwargs)` and the `return instance` line in
one try/except, swallowing any exception as "Failed to instantiate
bot". If we placed `enforce_agent_access` inside that try block,
denials would be logged as instantiation errors and the caller would
get `None` instead of an exception — breaking parity with
`BotManager.get_bot` which lets `AgentAccessDenied` propagate.

### Patterns to Follow

- Mirror TASK-1053 (`BotManager.get_bot`) — same helper, same
  semantics. Test names in `test_get_instance_pbac.py` should mirror
  those in `test_get_bot_pbac.py` so a parity reader can compare them
  side by side.

---

## Acceptance Criteria

- [ ] `get_instance(name, request=req)` denies non-matching subjects
  with `AgentAccessDenied`.
- [ ] `get_instance(name, request=req)` allows matching subjects.
- [ ] `get_instance(name)` (no request) allows for ANY bot — public or
  not.
- [ ] When `self._evaluator is None`, `get_instance(name, request=req)`
  allows unconditionally.
- [ ] `AgentAccessDenied` propagates — does NOT get swallowed by the
  existing `except Exception → return None` path.
- [ ] `BotManager.get_bot(name, request=req)` and
  `AgentRegistry.get_instance(name, request=req)` produce IDENTICAL
  decisions for the same `(user, bot)` pair.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/registry/test_get_instance_pbac.py -v`.
- [ ] `ruff check` passes on `parrot/registry/registry.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/registry/test_get_instance_pbac.py
import pytest
from unittest.mock import MagicMock

from parrot.registry.registry import AgentRegistry
from parrot.auth.agent_guard import AgentAccessDenied


@pytest.mark.asyncio
async def test_get_instance_empty_permissions_allows_anyone():
    ...

@pytest.mark.asyncio
async def test_get_instance_allow_by_group():
    ...

@pytest.mark.asyncio
async def test_get_instance_no_request_allows_programmatic_invocation():
    ...

@pytest.mark.asyncio
async def test_get_instance_no_evaluator_allows():
    ...

@pytest.mark.asyncio
async def test_get_instance_propagates_access_denied():
    """AgentAccessDenied must NOT be swallowed by the existing
    try/except → return None path."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. Confirm TASK-1049 is done.
2. Read `registry.py:528-552` carefully — note the `try/except` that
   wraps the existing return.
3. Restructure so `enforce_agent_access` runs OUTSIDE the existing
   try/except.
4. Add the `request` kwarg.
5. Write the 5 integration tests, mirroring the names from TASK-1053.
6. Run pytest + ruff.
7. Move this file to `sdd/tasks/completed/`, update the per-spec
   index, fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker (claude-sonnet-4-6) on 2026-05-07.

Added top-level imports to `registry.py`:
  - `from aiohttp import web`
  - `from ..auth.agent_guard import enforce_agent_access, AgentAccessDenied  # noqa: F401`

Modified `get_instance` signature to add `request: Optional[web.Request] = None`.
Restructured the method to place `enforce_agent_access` OUTSIDE the existing
`try/except Exception to return None` block, ensuring `AgentAccessDenied` propagates.

5 integration tests created in `test_get_instance_pbac.py`:
  - no-evaluator allows
  - no-request allows (programmatic bypass), evaluator not called
  - evaluator allows → instance returned
  - evaluator denies → AgentAccessDenied raised (navigator-auth-dependent)
  - AgentAccessDenied propagates (not swallowed by existing try/except)

All 5 tests pass. ruff shows 1 pre-existing F841 (not introduced by this task).
