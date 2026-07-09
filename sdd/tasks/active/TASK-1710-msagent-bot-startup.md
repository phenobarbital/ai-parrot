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
class MSAgentSDKWrapper:
    def __init__(self, agent, config, app, broker=None,
                 identity_mapper=None, agent_class=None):  # line 88
    async def setup(self) -> None:  # starts the MS Agent SDK surface
    async def cleanup(self) -> None:

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

    # Create MS Agent SDK wrapper
    from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper
    wrapper = MSAgentSDKWrapper(
        agent=agent,
        config=sdk_config,
        app=app,
        broker=broker,
    )
    await wrapper.setup()

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

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
