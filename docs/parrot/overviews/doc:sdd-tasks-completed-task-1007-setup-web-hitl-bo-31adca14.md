---
type: Wiki Overview
title: 'TASK-1007: Implement setup_web_hitl bootstrap'
id: doc:sdd-tasks-completed-task-1007-setup-web-hitl-bootstrap-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the `setup_web_hitl(app)` bootstrap function that ensures
  a process-wide `HumanInteractionManager` and `WebHumanChannel` are available at
  app startup (§3 Module 4 in the spec). The bootstrap is idempotent and integrates
  with the BotManager (called from TASK-1
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.user
  rel: mentions
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels.web
  rel: mentions
---

# TASK-1007: Implement setup_web_hitl bootstrap

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-1003, TASK-1006
**Assigned-to**: unassigned

---

## Context

This task implements the `setup_web_hitl(app)` bootstrap function that ensures a process-wide `HumanInteractionManager` and `WebHumanChannel` are available at app startup (§3 Module 4 in the spec). The bootstrap is idempotent and integrates with the BotManager (called from TASK-1009).

Without this bootstrap, web-only deployments (without Telegram or other integrations) would have no HITL manager. The bootstrap also registers the response handler route.

---

## Scope

- Implement `setup_web_hitl(app: web.Application) -> None` function in `parrot/handlers/web_hitl.py`.
- Function logic:
  1. If `get_default_human_manager()` returns a manager, skip creating a new one.
  2. Check if a `"web"` channel is already registered on the manager; if yes, skip registration.
  3. If no manager exists:
     - Create `HumanInteractionManager(redis_url=REDIS_URL)`.
     - Register `WebHumanChannel(socket_manager=app['user_socket_manager'])` under name `"web"`.
     - Call `set_default_human_manager(manager)`.
     - Append `app.on_startup` hook to call `manager.startup()`.
  4. If `app['user_socket_manager']` does not exist, log a WARNING but do not raise — allow the bootstrap to complete with a degraded state.
- Add Google-style docstring.

**NOT in scope**:
- Route registration — belongs to TASK-1009.
- Integration with `app.py:setup_app` — handled by BotManager.setup call.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/web_hitl.py` | MODIFY | Add `setup_web_hitl` function. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from aiohttp import web                                                         # stdlib
from parrot.human import (                                                      # parrot/human/__init__.py:9-43
    HumanInteractionManager,
    get_default_human_manager,
    set_default_human_manager,
)
from parrot.human.channels.web import WebHumanChannel                           # parrot/human/channels/web.py (created in TASK-1003)
from parrot.handlers.user import UserSocketManager                              # parrot/handlers/user.py:27
from parrot.conf import REDIS_URL                                               # parrot/conf.py:271
import logging
```

### Existing Signatures to Use

```python
# parrot/conf.py
REDIS_URL: str = ...  # line 271

# parrot/human/manager.py:34
class HumanInteractionManager:
    def __init__(
        self,
        channels: Optional[Dict[str, HumanChannel]] = None,
        redis_url: Optional[str] = None,
    ) -> None: ...

    def register_channel(self, name: str, channel: HumanChannel) -> None:      # line 144
    async def startup(self) -> None: ...                                        # line 148

# parrot/human/__init__.py
def get_default_human_manager() -> Optional[HumanInteractionManager]: ...
def set_default_human_manager(manager: HumanInteractionManager) -> None: ...

# aiohttp
app.on_startup: list[Callable]  # list of coroutines to run at startup
app.on_startup.append(coroutine)
```

### Does NOT Exist

- ~~`setup_web_hitl` function~~ — to be created.
- ~~`AgentTalk.on_startup` hook~~ — does not exist (AgentTalk is per-request); use `app.on_startup` instead.

---

## Implementation Notes

### Pattern to Follow

Mirror the bootstrap pattern from `parrot/integrations/manager.py:_ensure_human_manager` (line 154):
- Check if a manager already exists (`get_default_human_manager()`).
- Create if not; register the channel under a unique name.
- Append the startup hook via `app.on_startup.append(...)`.
- Log at INFO level on successful setup, WARNING if socket manager is missing.

### Key Constraints

- Function is NOT async (it sets up hooks, not coroutines directly).
- The `app.on_startup` hook is where `manager.startup()` is called (which IS async).
- If `app['user_socket_manager']` is missing, log a WARNING and continue — do not raise.
- Idempotent: safe to call multiple times.

---

## Acceptance Criteria

- [ ] `setup_web_hitl(app)` function exists in `parrot/handlers/web_hitl.py`.
- [ ] Function creates `HumanInteractionManager` only if one does not already exist.
- [ ] Function registers `WebHumanChannel` under name `"web"`.
- [ ] Function calls `set_default_human_manager(manager)`.
- [ ] Function appends `manager.startup()` to `app.on_startup`.
- [ ] Function logs WARNING if `app['user_socket_manager']` is missing, but does not raise.
- [ ] Function is idempotent (can be called twice safely).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/handlers/test_web_hitl.py::test_setup_web_hitl -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/handlers/web_hitl.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_web_hitl.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from aiohttp import web
from parrot.handlers.web_hitl import setup_web_hitl
from parrot.human import get_default_human_manager, set_default_human_manager


@pytest.fixture
def app():
    """Mock aiohttp Application."""
    app = web.Application()
    app['user_socket_manager'] = MagicMock()
    app.on_startup = []
    return app


@pytest.fixture(autouse=True)
def reset_default_manager():
    """Reset the default manager before/after each test."""
    original = get_default_human_manager()
    yield
    if original:
        set_default_human_manager(original)
    else:
        set_default_human_manager(None)


class TestSetupWebHitl:
    def test_setup_web_hitl_idempotent(self, app):
        """Calling setup_web_hitl twice does not create two managers."""
        setup_web_hitl(app)
        manager1 = get_default_human_manager()
        
        setup_web_hitl(app)
        manager2 = get_default_human_manager()
        
        assert manager1 is manager2
        assert len(app.on_startup) == 1  # startup hook appended only once

    def test_setup_web_hitl_skips_when_no_socket_manager(self, app):
        """setup_web_hitl logs warning and continues if socket manager missing."""
        del app['user_socket_manager']
        # Should not raise
        setup_web_hitl(app)
        # Manager should still be created
        manager = get_default_human_manager()
        assert manager is not None

    def test_setup_web_hitl_registers_channel(self, app):
        """setup_web_hitl registers WebHumanChannel under 'web'."""
        setup_web_hitl(app)
        manager = get_default_human_manager()
        # Check that a channel named 'web' is registered
        assert 'web' in manager.channels

    def test_setup_web_hitl_appends_startup_hook(self, app):
        """setup_web_hitl appends manager.startup to app.on_startup."""
        setup_web_hitl(app)
        assert len(app.on_startup) == 1
        # The appended item should be a coroutine function (manager.startup)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — verify TASK-1003 and TASK-1006 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `HumanInteractionManager` constructor, `get/set_default_human_manager` signatures, and `parrot/integrations/manager.py` pattern
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1007-setup-web-hitl-bootstrap.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
