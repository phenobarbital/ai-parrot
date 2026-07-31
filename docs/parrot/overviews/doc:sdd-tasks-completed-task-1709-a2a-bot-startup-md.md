---
type: Wiki Overview
title: 'TASK-1709: A2A Bot Startup + Discovery Registry + Security'
id: doc:sdd-tasks-completed-task-1709-a2a-bot-startup-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This is the core A2A integration task. It implements the `_start_a2a_bot()`
  method in `IntegrationBotManager`, the in-process A2A discovery registry, the `/a2a/directory`
  endpoint, and security middleware wiring. After this task, `kind: a2a` entries in
  the YAML will produce a run'
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.a2a.security
  rel: mentions
- concept: mod:parrot.a2a.server
  rel: mentions
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
---

# TASK-1709: A2A Bot Startup + Discovery Registry + Security

**Feature**: FEAT-271 — MSAgent & A2A YAML Integrations
**Spec**: `sdd/specs/msagent-a2a-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1708
**Assigned-to**: unassigned

---

## Context

This is the core A2A integration task. It implements the `_start_a2a_bot()` method in `IntegrationBotManager`, the in-process A2A discovery registry, the `/a2a/directory` endpoint, and security middleware wiring. After this task, `kind: a2a` entries in the YAML will produce a running A2A service.

Implements spec §3 Modules 4 and 6 (A2A part).

---

## Scope

- Add `self.a2a_bots: Dict[str, Any] = {}` dict to `IntegrationBotManager.__init__()`.
- Implement `_start_a2a_bot(name, config)` async method:
  - Resolve agent via `_get_agent()`.
  - Optionally build `CredentialBroker` from `config.credentials` if `enable_credential_broker`.
  - Create `A2AServer(agent, base_path=..., tags=..., broker=...)`.
  - Call `a2a_server.setup(app, url=config.url)` for shared app.
  - If `config.port` is set, create a dedicated `aiohttp.web.TCPSite`.
  - Register AgentCard in `app["a2a_discovery_registry"]`.
  - Wire `A2ASecurityMiddleware` if any security field is set.
- Implement the discovery registry:
  - Init `app.setdefault("a2a_discovery_registry", {})` during startup.
  - Register `GET /a2a/directory` handler that returns all cards as JSON array.
- Add `isinstance(agent_config, A2AAgentConfig)` branch in `startup()` dispatch.
- Add A2A cleanup to `shutdown()` if one exists.

**NOT in scope**: MSAgent startup (TASK-1710), test files (TASK-1711).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Add `_start_a2a_bot()`, discovery registry, dispatch branch |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.a2a.server import A2AServer                     # packages/ai-parrot-server/src/parrot/a2a/server.py:50
from parrot.a2a.security import A2ASecurityMiddleware        # packages/ai-parrot-server/src/parrot/a2a/security.py:1409
from parrot.a2a.security import SecurityPolicy               # packages/ai-parrot-server/src/parrot/a2a/security.py:218
from parrot.a2a.security import JWTAuthenticator             # packages/ai-parrot-server/src/parrot/a2a/security.py:972
from parrot.a2a.security import MTLSAuthenticator            # packages/ai-parrot-server/src/parrot/a2a/security.py:1206
from parrot.a2a.security import InMemoryCredentialProvider   # packages/ai-parrot-server/src/parrot/a2a/security.py:444
from parrot.auth.broker import CredentialBroker              # packages/ai-parrot/src/parrot/auth/broker.py:326
from parrot.auth.credentials import ProviderCredentialConfig # packages/ai-parrot/src/parrot/auth/credentials.py:46
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/a2a/server.py:50
class A2AServer:
    def __init__(self, agent, *, base_path="/a2a", version="1.0.0",
                 capabilities=None, extra_skills=None, tags=None,
                 broker=None, identity_mapper=None, credential_resolvers=None,
                 suspended_store=None, audit_ledger=None):  # line 84
    def setup(self, app: web.Application, url=None) -> None:  # line 171
    def get_agent_card(self) -> AgentCard:  # line 207

# packages/ai-parrot-server/src/parrot/a2a/security.py:1409
class A2ASecurityMiddleware:
    def __init__(self, *, jwt_authenticator=None, mtls_authenticator=None,
                 credential_provider=None, default_policy=None,
                 skip_paths=None, rate_limiter=None):  # line 1436

# packages/ai-parrot/src/parrot/auth/broker.py:326
class CredentialBroker:
    @classmethod
    def from_config(cls, configs, strict=True, **deps) -> "CredentialBroker":  # line 401

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py:47
class IntegrationBotManager:
    def __init__(self, bot_manager):  # line 58
        # Existing dicts: telegram_bots (63), msteams_bots (64), whatsapp_bots (65),
        #   slack_bots (66), msagentsdk_bots (67)
    async def _get_agent(self, chatbot_id, system_prompt_override=None):  # line 118
    async def startup(self, extra_config=None):  # line 130
        # Dispatch isinstance chain: lines 150-159
```

### Does NOT Exist
- ~~`IntegrationBotManager.a2a_bots`~~ — does not exist yet; this task adds it
- ~~`IntegrationBotManager._start_a2a_bot()`~~ — does not exist yet; this task creates it
- ~~`app["a2a_discovery_registry"]`~~ — not initialized yet; this task sets it up
- ~~`A2AServer.setup_multi()`~~ — no such method; call `setup()` per agent
- ~~`A2ASecurityMiddleware.from_config()`~~ — no such classmethod; construct directly

---

## Implementation Notes

### Pattern to Follow
```python
async def _start_a2a_bot(self, name: str, config: A2AAgentConfig) -> None:
    agent = await self._get_agent(config.chatbot_id, config.system_prompt_override)
    if not agent:
        return

    from parrot.a2a.server import A2AServer

    # Build broker if enabled
    broker = None
    if config.enable_credential_broker and config.credentials:
        from parrot.auth.broker import CredentialBroker
        from parrot.auth.credentials import ProviderCredentialConfig
        configs = [ProviderCredentialConfig(**c) for c in config.credentials]
        broker = CredentialBroker.from_config(configs, strict=False)

    # Create A2A server
    a2a_server = A2AServer(
        agent=agent,
        base_path=config.base_path,
        tags=config.tags,
        broker=broker,
    )

    app = self.bot_manager.get_app()

    # Init discovery registry
    app.setdefault("a2a_discovery_registry", {})

    # Setup routes
    if config.port:
        # Dedicated port: create a sub-app
        sub_app = web.Application()
        a2a_server.setup(sub_app, url=config.url)
        runner = web.AppRunner(sub_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", config.port)
        await site.start()
    else:
        a2a_server.setup(app, url=config.url)

    # Register in discovery
    card = a2a_server.get_agent_card()
    app["a2a_discovery_registry"][name] = card

    # Wire security if configured
    if config.jwt_secret or config.api_key or config.mtls_ca_cert or config.hmac_secret:
        self._wire_a2a_security(app, config)

    self.a2a_bots[name] = a2a_server
    self.logger.info("Started A2A bot '%s' at %s", name, config.base_path)
```

### Key Constraints
- All `parrot.a2a.*` imports must be lazy (inside the method) — `ai-parrot-server` is optional.
- Wrap the entire method body in `try/except ImportError` to handle missing `ai-parrot-server`.
- The `/a2a/directory` route should be registered ONCE (on first A2A bot startup), not per-bot.
- For multi-agent: each A2A agent needs a unique `base_path` (e.g., `/a2a/<name>`). If `base_path` is the default `/a2a` and there are multiple A2A agents, append the agent name.
- `ProviderCredentialConfig(**c)` constructs from the raw YAML dict.
- Use `strict=False` on `CredentialBroker.from_config()` so invalid credentials don't crash startup.

---

## Acceptance Criteria

- [ ] `kind: a2a` starts an `A2AServer` on the shared aiohttp app
- [ ] `kind: a2a` with `port: 8181` starts a dedicated server on port 8181
- [ ] `GET /.well-known/agent.json` returns a valid AgentCard
- [ ] `GET /a2a/directory` returns JSON array of A2A agent cards only
- [ ] Security middleware wired when `jwt_secret` or `api_key` set
- [ ] Credential broker wired when `enable_credential_broker: true` + `credentials` list present
- [ ] Missing `ai-parrot-server` handled gracefully (ImportError logged, agent skipped)
- [ ] `isinstance` dispatch branch added to `startup()`
- [ ] No linting errors

---

## Test Specification

```python
# tests/integrations/test_a2a_startup.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web


class TestA2ABotStartup:
    @pytest.fixture
    def mock_manager(self):
        manager = MagicMock()
        manager.bot_manager.get_app.return_value = web.Application()
        manager.bot_manager.get_bot = AsyncMock(return_value=MagicMock())
        manager.logger = MagicMock()
        return manager

    async def test_start_a2a_bot_shared_app(self, mock_manager):
        """A2A bot mounts routes on shared app."""
        # Test that setup() is called on the shared app
        ...

    async def test_discovery_registry_populated(self, mock_manager):
        """AgentCard registered in discovery registry."""
        ...

    async def test_directory_endpoint_returns_cards(self):
        """GET /a2a/directory returns registered cards."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1708 is completed
3. **Verify the Codebase Contract** — confirm `A2AServer`, `A2ASecurityMiddleware` signatures
4. **Implement** `_start_a2a_bot()` and discovery infrastructure in `manager.py`
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1709-a2a-bot-startup.md`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude)
**Date**: 2026-07-09
**Notes**: Implemented in `manager.py`: `self.a2a_bots` dict + `self._a2a_runners` list (init), module-level `handle_a2a_directory()` handler, `_wire_a2a_security()` helper (builds `JWTAuthenticator`/`MTLSAuthenticator`/`InMemoryCredentialProvider` from whichever config fields are set, appends `A2ASecurityMiddleware` to the target app), and `_start_a2a_bot()` (resolves agent, optional `CredentialBroker.from_config(strict=False)`, `A2AServer` construction, shared-app vs dedicated-port `TCPSite` mounting, `/a2a/directory` route registered once on the shared app regardless of per-agent port, base_path collision avoidance for multiple default-path agents on the shared app, discovery registry population, `OSError` handling for port conflicts). Added `isinstance(agent_config, A2AAgentConfig)` dispatch branch in `startup()` and A2A runner cleanup + dict clearing in `shutdown()`.

One implementation detail not spelled out in the task's Pattern-to-Follow snippet: security middleware wiring for the dedicated-port path had to happen on `target_app` BEFORE `await runner.setup()` — aiohttp freezes `app.middlewares`/`app.router` at that point (confirmed via `AppRunner._make_server()`: `on_startup.freeze(); await app.startup(); app.freeze()`), so appending middleware afterward raises `RuntimeError: Cannot modify frozen list`. Restructured to wire security + call `a2a_server.setup()` before `runner.setup()` for the port case; for the shared-app case this is inherently safe since `_start_a2a_bot()` itself runs from the `on_startup` signal (via `IntegrationBotManager.startup()`), before the app is frozen.

Verified end-to-end with a live aiohttp `TestClient`/`TestServer` (shared app) and a real `TCPSite` on a free port (dedicated port): `/.well-known/agent.json` returns a valid AgentCard, `/a2a/directory` returns only A2A-agent cards, unauthenticated requests to a JWT-protected dedicated-port agent get HTTP 401, multiple shared-app agents get distinct base_paths, and a simulated missing `ai-parrot-server` (patched `builtins.__import__`) degrades gracefully (agent skipped, no crash). `ruff check` passes clean. Pre-existing failures in `tests/integrations/test_msagentsdk/` (14, `importlib.reload` module-identity issue) reproduce identically on unmodified `dev` — unrelated to this task.

**Deviations from spec**: none in scope/files/class names. One implementation refinement beyond the task's illustrative snippet: security middleware for the dedicated-port path is wired before `runner.setup()` (not after, as loosely implied) to avoid the aiohttp frozen-app error described above.
