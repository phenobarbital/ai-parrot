---
type: Wiki Overview
title: 'TASK-1639: Integration Wrapper (MSAgentSDKWrapper)'
id: doc:sdd-tasks-completed-task-1639-msagentsdk-wrapper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates the integration wrapper class that owns the MS SDK
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.agent
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.wrapper
  rel: mentions
---

# TASK-1639: Integration Wrapper (MSAgentSDKWrapper)

**Feature**: FEAT-259 — Microsoft Copilot Agent SDK Integration
**Spec**: `sdd/specs/microsoft-copilot-agent-sdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1637, TASK-1638
**Assigned-to**: unassigned

---

## Context

This task creates the integration wrapper class that owns the MS SDK
`CloudAdapter`, creates the bridge agent, registers the HTTP route on the
aiohttp app, and configures authentication. It follows the standard ai-parrot
integration wrapper pattern.

Implements: Spec §3 Module 3 (Integration Wrapper).

---

## Scope

- Create `wrapper.py` in the `msagentsdk/` package.
- Implement `MSAgentSDKWrapper` class:
  - Constructor receives `agent: AbstractBot`, `config: MSAgentSDKConfig`,
    `app: web.Application`.
  - Creates `ParrotM365Agent` bridge.
  - Creates `CloudAdapter` with auth config (or anonymous).
  - Registers per-bot HTTP route: `/api/msagentsdk/{safe_id}/messages`.
  - Excludes route from auth middleware.
  - Implements `handle_request(request) → web.Response`.
  - Implements `stop()` for graceful shutdown.
- All MS SDK imports must be lazy (inside methods, not module-level).

**NOT in scope**: Manager registration, config dispatch, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py` | CREATE | `MSAgentSDKWrapper` class |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py` | MODIFY | Add `MSAgentSDKWrapper` export |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot  # verified: abstract.py:156
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig  # created in TASK-1637
from parrot.integrations.msagentsdk.agent import ParrotM365Agent    # created in TASK-1638
from navconfig.logging import logging

# MS SDK imports — LAZY ONLY
from microsoft_agents.hosting.aiohttp import CloudAdapter  # from microsoft-agents-hosting-aiohttp

# aiohttp
from aiohttp import web  # verified: used across all wrappers
```

### Existing Signatures to Use

```python
# WhatsApp wrapper pattern (reference for route registration)
# packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py
class WhatsAppAgentWrapper:
    def __init__(self, agent, config, app):
        # ...
        safe_id = self.config.name.replace(" ", "_").lower()
        self.webhook_path = f"/api/whatsapp/{safe_id}/webhooks"
        self.app.router.add_post(self.webhook_path, self.handle_webhook)
        # Auth exclusion:
        if auth := self.app.get("auth"):
            auth.add_exclude_list(self.webhook_path)

# MS Teams wrapper pattern (reference for adapter usage)
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper:
    def __init__(self, agent, config, app, ...):
        self.route = f"/api/teambots/{safe_id}/messages"
        self.app.router.add_post(self.route, self.handle_request)

# CloudAdapter (from microsoft_agents.hosting.aiohttp)
# CloudAdapter.process(request, agent) -> web.Response
# - Takes an aiohttp Request and the Agent protocol implementor
# - Handles JWT validation, Activity parsing, turn execution
```

### Does NOT Exist

- ~~`CloudAdapter(auth_configuration=...)`~~ — verify exact constructor param name in SDK; may be `auth_config` or require `AgentAuthConfiguration`
- ~~`parrot.integrations.base.AbstractWrapper`~~ — no base class; wrapper pattern is implicit
- ~~`self.adapter.run()`~~ — not a method; use `self.adapter.process(request, agent)`

---

## Implementation Notes

### Pattern to Follow

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Optional
from aiohttp import web
from navconfig.logging import logging

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from .models import MSAgentSDKConfig


class MSAgentSDKWrapper:
    """ai-parrot integration wrapper for Microsoft 365 Agents SDK."""
    
    def __init__(
        self,
        agent: AbstractBot,
        config: MSAgentSDKConfig,
        app: web.Application,
    ):
        self.agent = agent
        self.config = config
        self.app = app
        self.logger = logging.getLogger(f"MSAgentSDKWrapper.{config.name}")
        
        # Create bridge agent (lazy import of MS SDK is inside ParrotM365Agent)
        from .agent import ParrotM365Agent
        self.m365_agent = ParrotM365Agent(
            agent,
            welcome_message=config.welcome_message,
        )
        
        # Create CloudAdapter (lazy import)
        from microsoft_agents.hosting.aiohttp import CloudAdapter
        self.adapter = CloudAdapter()  # auth config wired here
        
        # Register per-bot HTTP route
        safe_id = config.name.replace(" ", "_").lower()
        self.route = f"/api/msagentsdk/{safe_id}/messages"
        self.app.router.add_post(self.route, self.handle_request)
        
        # Exclude from auth middleware
        if auth := self.app.get("auth"):
            auth.add_exclude_list(self.route)
        
        self.logger.info("Registered MS Agent SDK route: %s", self.route)
    
    async def handle_request(self, request: web.Request) -> web.Response:
        return await self.adapter.process(request, self.m365_agent)
    
    async def stop(self):
        self.logger.info("Stopping MS Agent SDK wrapper: %s", self.config.name)
```

### Key Constraints

- Use per-bot route pattern: `/api/msagentsdk/{safe_id}/messages`.
- Do NOT register `/api/messages` (per user decision).
- All `microsoft_agents.*` imports MUST be lazy.
- Auth configuration for `CloudAdapter` needs investigation at implementation
  time — the exact constructor parameter for `AgentAuthConfiguration` should
  be verified against the installed SDK version.
- If `config.anonymous_auth` is True, pass None for auth config.

---

## Acceptance Criteria

- [ ] `MSAgentSDKWrapper` registers route at `/api/msagentsdk/{safe_id}/messages`
- [ ] `handle_request()` delegates to `CloudAdapter.process()`
- [ ] Route is excluded from auth middleware when available
- [ ] `stop()` method exists for graceful shutdown
- [ ] All MS SDK imports are lazy
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/`

---

## Test Specification

```python
# tests/integrations/test_msagentsdk/test_wrapper.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web


class TestMSAgentSDKWrapper:
    @pytest.fixture
    def mock_app(self):
        app = web.Application()
        return app
    
    @pytest.fixture
    def mock_config(self):
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
        return MSAgentSDKConfig(
            name="TestBot",
            chatbot_id="test_agent",
            anonymous_auth=True,
        )
    
    def test_route_registered(self, mock_app, mock_config):
        """Wrapper registers the per-bot route on the aiohttp app."""
        mock_bot = AsyncMock()
        from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper
        wrapper = MSAgentSDKWrapper(mock_bot, mock_config, mock_app)
        routes = [r.resource.canonical for r in mock_app.router.routes()]
        assert "/api/msagentsdk/testbot/messages" in routes
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/microsoft-copilot-agent-sdk.spec.md` for full context
2. **Check dependencies** — verify TASK-1637 and TASK-1638 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — check `CloudAdapter` constructor signature in installed SDK
4. **Implement** the wrapper class
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1639-msagentsdk-wrapper.md`
7. **Update index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-25.

Created:
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py` — `MSAgentSDKWrapper` class.

Key implementation decisions:
- `CloudAdapter` is imported lazily inside `__init__` so the class can be imported without the SDK.
- For `anonymous_auth=True`: `CloudAdapter()` is called with no arguments (no JWT validation).
- For `anonymous_auth=False`: tries `AgentAuthConfiguration` first (from `microsoft_agents.hosting.core`); falls back to keyword args if that class isn't available (SDK version variance).
- Route registered as `/api/msagentsdk/{safe_id}/messages` where `safe_id = name.replace(" ", "_").lower()`.
- Auth middleware exclusion pattern matches WhatsApp/MS Teams wrappers.
- `stop()` is a no-op but present for lifecycle symmetry.

All acceptance criteria met. Lint passes.
