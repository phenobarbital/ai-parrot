---
type: Wiki Overview
title: 'TASK-1710: MSAgent Bot Startup + Credential Broker + O365 OAuth + A2A Companion'
id: doc:sdd-tasks-completed-task-1710-msagent-bot-startup-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task implements `_start_msagent_bot()` in `IntegrationBotManager`,
  which brings up a full MS Agent SDK surface from a `kind: msagent` YAML entry. It
  wires the `MSAgentSDKWrapper`, configures the `CredentialBroker` with O365 OAuth
  provider, sets up the identity bridge, and sp'
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
- concept: mod:parrot.auth.oauth2_routes
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.wrapper
  rel: mentions
---

# TASK-1710: MSAgent Bot Startup + Credential Broker + O365 OAuth + A2A Companion

**Feature**: FEAT-271 — MSAgent & A2A YAML Integrations
**Spec**: `sdd/specs/msagent-a2a-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1708, TASK-1709
**Assigned-to**: unassigned

---

## Context

This task implements `_start_msagent_bot()` in `IntegrationBotManager`, which brings up a full MS Agent SDK surface from a `kind: msagent` YAML entry. It wires the `MSAgentSDKWrapper`, configures the `CredentialBroker` with O365 OAuth provider, sets up the identity bridge, and spins up a companion A2A surface (auto-enabled) reusing the A2A infrastructure from TASK-1709.

Implements spec §3 Modules 5 and 6 (MS Agent part).

---

## Scope

- Add `self.msagent_bots: Dict[str, Any] = {}` dict to `IntegrationBotManager.__init__()`.
- Implement `_start_msagent_bot(name, config)` async method:
  - Resolve agent via `_get_agent()`.
  - Convert `config.to_msagentsdk_config()` to get inner `MSAgentSDKConfig`.
  - Build `CredentialBroker` from `config.credentials` if `enable_credential_broker`.
  - Build O365 OAuth provider if `config.o365_client_id` is set.
  - Create `MSAgentSDKWrapper(agent, sdk_config, app, broker=broker)`.
  - Start the MS Agent SDK surface.
  - Spin up companion A2A surface: create `A2AServer` with same agent, register in discovery.
  - Wire `A2ASecurityMiddleware` if `config.jwt_secret` set.
- Add `isinstance(agent_config, MSAgentIntegrationConfig)` branch in `startup()` dispatch.
- Add cleanup to `shutdown()`.

**NOT in scope**: A2A-only startup (TASK-1709), config dispatch (TASK-1708), tests (TASK-1711).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Add `_start_msagent_bot()`, dispatch branch, cleanup |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper  # packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py:63
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig     # packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py:11
from parrot.integrations.msagentsdk.models import MSAgentIntegrationConfig  # TASK-1707 creates this
from parrot.a2a.server import A2AServer                                # packages/ai-parrot-server/src/parrot/a2a/server.py:50
from parrot.a2a.security import A2ASecurityMiddleware                  # packages/ai-parrot-server/src/parrot/a2a/security.py:1409
from parrot.auth.broker import CredentialBroker                        # packages/ai-parrot/src/parrot/auth/broker.py:326
from parrot.auth.credentials import ProviderCredentialConfig           # packages/ai-parrot/src/parrot/auth/credentials.py:46
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py:63
# CONTRACT CORRECTION (verified 2026-07-09, TASK-1710): the wrapper's
# constructor is synchronous and registers the HTTP route(s) directly
# (``self.app.router.add_post(path, self.handle_request)`` at wrapper.py:244)
# — there is NO separate ``async def setup()``/``async def cleanup()`` pair.
# The existing ``_start_msagentsdk_bot()`` (manager.py:357) already reflects
# this: it just constructs ``MSAgentSDKWrapper(...)`` and stores it, with no
# follow-up ``.setup()`` call. Cleanup is ``async def stop(self) -> None``
# (wrapper.py:410), called from ``IntegrationBotManager.shutdown()``.
class MSAgentSDKWrapper:
    def __init__(self, agent, config, app, broker=None,
                 identity_mapper=None, agent_class=None):  # line 88
    async def stop(self) -> None:  # line 410 — graceful shutdown (no-op today, lifecycle symmetry)

# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py (TASK-1707)
class MSAgentIntegrationConfig:
    def to_msagentsdk_config(self) -> MSAgentSDKConfig: ...

# packages/ai-parrot/src/parrot/auth/broker.py:326
class CredentialBroker:
    @classmethod
    def from_config(cls, configs, strict=True, **deps) -> "CredentialBroker":  # line 401

# packages/ai-parrot/src/parrot/auth/credentials.py:46
class ProviderCredentialConfig(BaseModel):
    provider: str
    auth: AuthKind
    options: Dict[str, Any] = {}

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py:47
class IntegrationBotManager:
    # Existing _start_msagentsdk_bot at line 334 — reference pattern
    async def _start_msagentsdk_bot(self, name: str, config: MSAgentSDKConfig) -> None:
```

### Does NOT Exist
- ~~`IntegrationBotManager.msagent_bots`~~ — does not exist yet; this task adds it
- ~~`IntegrationBotManager._start_msagent_bot()`~~ — does not exist yet; this task creates it
- ~~`MSAgentSDKWrapper.from_config()`~~ — no such classmethod; construct directly
- ~~`MSAgentIntegrationConfig.to_wrapper()`~~ — no such method; use `to_msagentsdk_config()` + construct wrapper manually
- ~~`MSAgentSDKWrapper.setup()`~~ / ~~`MSAgentSDKWrapper.cleanup()`~~ — do NOT exist (contract correction above); constructor does the setup work synchronously, `stop()` is the cleanup method
- ~~`MSAgentIntegrationConfig.mtls_ca_cert`~~ / ~~`.hmac_secret`~~ / ~~`.basic_credentials`~~ / ~~`.security_policy`~~ — none of these fields exist on `MSAgentIntegrationConfig` (only `jwt_secret` and `api_key` overlap with `A2AAgentConfig`'s security surface). The existing `_wire_a2a_security()` helper (added in TASK-1709) accesses these attributes directly on an `A2AAgentConfig`-typed `config` param, so calling it as-is with an `MSAgentIntegrationConfig` instance would raise `AttributeError`. **Correction**: `_wire_a2a_security()` must be updated to use `getattr(config, "field", None)` for the fields not common to both configs before this task's companion-A2A code can safely call it.

---

## Implementation Notes

### Pattern to Follow
```python
async def _start_msagent_bot(self, name: str, config: MSAgentIntegrationConfig) -> None:
    agent = await self._get_agent(config.chatbot_id, config.system_prompt_override)
    if not agent:
        return

    # Convert to inner SDK config
    sdk_config = config.to_msagentsdk_config()

    # Build credential broker
    broker = None
    if config.enable_credential_broker and config.credentials:
        from parrot.auth.broker import CredentialBroker
        from parrot.auth.credentials import ProviderCredentialConfig
        configs = [ProviderCredentialConfig(**c) for c in config.credentials]
        broker = CredentialBroker.from_config(configs, strict=False)

    app = self.bot_manager.get_app()

    # Create MS Agent SDK wrapper (constructor registers the HTTP route(s)
    # synchronously — there is no separate async setup() call).
    from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper
    wrapper = MSAgentSDKWrapper(
        agent=agent,
        config=sdk_config,
        app=app,
        broker=broker,
    )

    # Companion A2A surface (always-on)
    try:
        from parrot.a2a.server import A2AServer
        companion_path = f"/a2a/{name.lower()}"
        a2a_server = A2AServer(
            agent=agent,
            base_path=companion_path,
            tags=config.tags,
            broker=broker,
        )
        app.setdefault("a2a_discovery_registry", {})
        a2a_server.setup(app, url=config.url)
        card = a2a_server.get_agent_card()
        app["a2a_discovery_registry"][name] = card

        if config.jwt_secret:
            self._wire_a2a_security(app, config)
    except ImportError:
        self.logger.warning(
            "ai-parrot-server not installed — A2A companion skipped for '%s'", name
        )

    self.msagent_bots[name] = wrapper
    self.logger.info("Started MSAgent bot '%s'", name)
```

### Key Constraints
- Reference `_start_msagentsdk_bot()` (line 334) for the existing pattern — `_start_msagent_bot()` extends it with broker, O365, and companion A2A.
- The companion A2A surface is always-on per spec. Wrap in `try/except ImportError` since `ai-parrot-server` is optional.
- Use `config.to_msagentsdk_config()` to get the inner config — do NOT manually construct `MSAgentSDKConfig`.

### CONTRACT CORRECTION — `O365OAuthManager.setup()` frozen-app gotcha (verified 2026-07-09)
`examples/msagent/server.py`'s `build_o365_infra()` (referenced by this task's
Agent Instructions as "the reference implementation pattern") calls
`O365OAuthManager(...).setup()` **before** the aiohttp app is ever run via
`AppRunner` — i.e. before `app.on_startup` is frozen. That pattern does NOT
transfer directly to `_start_msagent_bot()`: this method runs from
`IntegrationBotManager.startup()`, which in production
(`packages/ai-parrot-server/src/parrot/manager/manager.py:2118`) is itself
invoked from `BotManagerServer.on_startup()` — an `app.on_startup` handler
(registered at `manager.py:1654`). `aiohttp.web.AppRunner._make_server()`
calls `app.on_startup.freeze()` **before** dispatching `on_startup` handlers,
so by the time `_start_msagent_bot()` runs, `app.on_startup` is ALREADY
frozen. `AbstractOAuth2Manager.setup()`
(`packages/ai-parrot/src/parrot/auth/oauth2_base.py:186`) does
`app.on_startup.append(self._on_startup)` as its first mutating step — this
raises `RuntimeError: Cannot modify frozen list` in that context. (Verified
empirically: a minimal aiohttp repro appending to `on_startup` from inside a
running `on_startup` handler raises the same error; `app.middlewares` and
`app.on_cleanup` are NOT frozen at that point, only `on_startup` is.)

**Required workaround**: do not call `manager.setup()` directly from
`_start_msagent_bot()`. Instead replicate its remaining side effects (app
slot, `on_cleanup` hook, callback route via `setup_oauth2_routes()` from
`parrot.auth.oauth2_routes` — `packages/ai-parrot/src/parrot/auth/oauth2_routes.py:279`)
and resolve the Redis client immediately via `await manager._on_startup(app)`
instead of deferring to the (already-fired) `on_startup` signal. See the
corrected `_setup_o365_oauth()` helper in the implementation.
- O365 OAuth setup follows `examples/msagent/server.py` pattern for `redirect_uri` and token endpoints.
- All `parrot.a2a.*` imports must be lazy (inside the method body).

---

## Acceptance Criteria

- [ ] `kind: msagent` starts an `MSAgentSDKWrapper` with correct config
- [ ] Credential broker wired when `enable_credential_broker: true`
- [ ] O365 OAuth routes registered when `o365_client_id` set
- [ ] Companion A2A surface started and registered in discovery
- [ ] Missing `ai-parrot-server` skips A2A companion gracefully
- [ ] `isinstance` dispatch branch added to `startup()`
- [ ] Cleanup shuts down wrapper and companion
- [ ] No linting errors

---

## Test Specification

```python
# tests/integrations/test_msagent_startup.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web


class TestMSAgentBotStartup:
    @pytest.fixture
    def mock_manager(self):
        manager = MagicMock()
        manager.bot_manager.get_app.return_value = web.Application()
        manager.bot_manager.get_bot = AsyncMock(return_value=MagicMock())
        manager.logger = MagicMock()
        return manager

    async def test_start_msagent_bot_basic(self, mock_manager):
        """MSAgent bot creates wrapper with correct SDK config."""
        ...

    async def test_credential_broker_wired(self, mock_manager):
        """Broker constructed from credentials list when enabled."""
        ...

    async def test_companion_a2a_started(self, mock_manager):
        """Companion A2A surface registered in discovery."""
        ...

    async def test_companion_a2a_skipped_without_server(self, mock_manager):
        """Missing ai-parrot-server logs warning, does not crash."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1708 and TASK-1709 are completed
3. **Read `examples/msagent/server.py`** for the reference implementation pattern
4. **Read existing `_start_msagentsdk_bot()`** at manager.py:334 for the base pattern
5. **Implement** `_start_msagent_bot()` in `manager.py`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1710-msagent-bot-startup.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude)
**Date**: 2026-07-09
**Notes**: Implemented `self.msagent_bots` dict (init), `_setup_o365_oauth()` helper, and `_start_msagent_bot()` in `manager.py`: resolves agent, converts config via `to_msagentsdk_config()`, optionally builds `CredentialBroker.from_config(strict=False)`, optionally wires O365 OAuth2 SSO, constructs `MSAgentSDKWrapper` (route registration happens synchronously in its constructor — see contract correction below), and always mounts a companion A2A surface at `/a2a/{name.lower()}` sharing the same broker (registered in the discovery registry, security wired when `jwt_secret` set, guarded by `try/except ImportError` for missing `ai-parrot-server`). Added `isinstance(agent_config, MSAgentIntegrationConfig)` dispatch branch in `startup()` and `msagent_bots` stop-loop + dict clearing in `shutdown()`.

Two Codebase Contract corrections discovered during verification (documented in-file above before implementing, per the anti-hallucination protocol):
1. `MSAgentSDKWrapper.setup()`/`.cleanup()` do NOT exist — the constructor registers HTTP routes synchronously (matching the existing `_start_msagentsdk_bot()` pattern, which never calls a `.setup()`), and cleanup is `async def stop()` (wrapper.py:410).
2. `_wire_a2a_security()` (added in TASK-1709) was typed for `A2AAgentConfig` and accessed `mtls_ca_cert`/`hmac_secret`/`basic_credentials`/`security_policy` directly — attributes `MSAgentIntegrationConfig` does not have. Updated it to read every security field via `getattr(config, "field", None)` so it's safely shared by both config types (this is the only change to previously-completed-task code; done in-file since `manager.py` is this task's own scope).

A third, more consequential issue surfaced only through live testing (not spelled out in the contract): `examples/msagent/server.py`'s `O365OAuthManager(...).setup()` pattern — cited in this task's Agent Instructions as the reference — calls `app.on_startup.append(self._on_startup)` as its first mutating step. That works in the example because `setup()` runs BEFORE the app's `AppRunner` starts. It does NOT work here: `_start_msagent_bot()` runs from `IntegrationBotManager.startup()`, itself invoked from the shared app's own `on_startup` handler (`BotManagerServer.on_startup`, ai-parrot-server manager.py:2118). aiohttp's `AppRunner._make_server()` calls `app.on_startup.freeze()` BEFORE dispatching `on_startup` handlers, so calling `.setup()` from within that dispatch chain raises `RuntimeError: Cannot modify frozen list`. Added `_setup_o365_oauth()`, which tries `manager.setup()` and, on that specific `RuntimeError`, replicates its remaining side effects (app slot, `on_cleanup` hook via `app.on_cleanup.append` — confirmed NOT frozen at this point, only `on_startup` is — and the callback route via `setup_oauth2_routes()`) and resolves the Redis client immediately via `await manager._on_startup(app)` instead of deferring to the already-fired signal. Verified this exact scenario end-to-end: ran `_start_msagent_bot()` with `o365_client_id`/`o365_client_secret` set from inside a real `aiohttp.web.AppRunner`-driven `on_startup` handler (reproducing the production call chain) — the O365 manager's app slot, callback route, and Redis ping all completed successfully with no exception.

Also verified: broker wiring (credential passed into `MSAgentSDKWrapper` constructor kwargs), companion A2A registration (`msagent_bots` + `a2a_bots` + `a2a_discovery_registry` all populated under the same name), and graceful A2A-companion skip when `parrot.a2a.server` import is simulated to fail (wrapper still starts; only the companion is skipped with a warning) — all via ad-hoc aiohttp `TestServer`/`AppRunner` scripts (mocking `parrot.integrations.msagentsdk.wrapper` in `sys.modules`, same pattern as `tests/integrations/test_msagentsdk/test_manager_registration.py`, since the real wrapper needs the optional `microsoft-agents-*` SDK). `ruff check` passes clean; existing `test_manager_registration.py` (10 tests) still passes unchanged.

**Deviations from spec**: none in scope/files/class names/signatures. Two corrections to code from prior tasks were necessary and made within this task's own file scope (`manager.py`): (1) `_wire_a2a_security()` uses `getattr` instead of direct attribute access so it works for both `A2AAgentConfig` and `MSAgentIntegrationConfig`; (2) added `_setup_o365_oauth()` as a helper not explicitly named in the task's Pattern-to-Follow snippet, required to make the O365 acceptance criterion actually functional given the frozen-`on_startup` timing described above.
