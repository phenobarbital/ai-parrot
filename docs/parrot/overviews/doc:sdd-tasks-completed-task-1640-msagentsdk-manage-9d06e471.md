---
type: Wiki Overview
title: 'TASK-1640: Manager Registration'
id: doc:sdd-tasks-completed-task-1640-msagentsdk-manager-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task wires the new MS Agent SDK integration into the existing
relates_to:
- concept: mod:parrot.integrations.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
---

# TASK-1640: Manager Registration

**Feature**: FEAT-259 — Microsoft Copilot Agent SDK Integration
**Spec**: `sdd/specs/microsoft-copilot-agent-sdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1637, TASK-1639
**Assigned-to**: unassigned

---

## Context

This task wires the new MS Agent SDK integration into the existing
`IntegrationBotManager` lifecycle: config dispatch, bot startup, and shutdown.
It modifies two existing files.

Implements: Spec §3 Module 4 (Manager Registration).

---

## Scope

- Add `MSAgentSDKConfig` import to `models.py` (conditional/lazy).
- Add `kind == 'msagentsdk'` dispatch branch in `IntegrationBotConfig.from_dict()`.
- Add `MSAgentSDKConfig` to the `agents` Union type hint.
- Add `MSAgentSDKConfig` validation in `validate()`.
- Add `msagentsdk_bots: Dict[str, MSAgentSDKWrapper]` attribute to `IntegrationBotManager`.
- Add `isinstance(agent_config, MSAgentSDKConfig)` branch in `startup()`.
- Add `_start_msagentsdk_bot()` method (follow `_start_whatsapp_bot` pattern).
- Add SDK bot cleanup in `shutdown()`.

**NOT in scope**: The wrapper itself (TASK-1639), bridge agent, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/models.py` | MODIFY | Add `MSAgentSDKConfig` import, dispatch, Union type, validation |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Add `msagentsdk_bots`, startup branch, `_start_msagentsdk_bot()`, shutdown cleanup |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# models.py — existing imports (line 6-9)
from .telegram.models import TelegramAgentConfig
from .msteams.models import MSTeamsAgentConfig
from .whatsapp.models import WhatsAppAgentConfig
from .slack.models import SlackAgentConfig
# ADD:
from .msagentsdk.models import MSAgentSDKConfig

# manager.py — existing imports (line 26-31)
from .models import (
    IntegrationBotConfig,
    TelegramAgentConfig,
    MSTeamsAgentConfig,
    WhatsAppAgentConfig,
    SlackAgentConfig,
)
# ADD MSAgentSDKConfig to this import
```

### Existing Signatures to Use

```python
# models.py — IntegrationBotConfig (line 13)
@dataclass
class IntegrationBotConfig:
    agents: Dict[str, Union[TelegramAgentConfig, MSTeamsAgentConfig, WhatsAppAgentConfig, SlackAgentConfig]]  # line 32
    # ADD MSAgentSDKConfig to this Union

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IntegrationBotConfig':  # line 35
        # kind dispatch at lines 46-53
        # ADD: elif kind == 'msagentsdk': agents[name] = MSAgentSDKConfig.from_dict(name, agent_data)

    def validate(self) -> List[str]:  # line 56
        # ADD: elif isinstance(agent_config, MSAgentSDKConfig): validate client_id/secret if not anonymous

# manager.py — IntegrationBotManager (line 45)
class IntegrationBotManager:
    def __init__(self, bot_manager: 'BotManager'):  # line 55
        self.telegram_bots: Dict  # line 60
        self.msteams_bots: Dict   # line 61
        self.whatsapp_bots: Dict  # line 62
        self.slack_bots: Dict     # line 63
        # ADD: self.msagentsdk_bots: Dict[str, 'MSAgentSDKWrapper'] = {}

    async def startup(self, extra_config=None):  # line 126
        # isinstance dispatch at lines 146-153
        # ADD: elif isinstance(agent_config, MSAgentSDKConfig): await self._start_msagentsdk_bot(name, agent_config)

    async def _get_agent(self, chatbot_id, system_prompt_override=None):  # line 114

    # Reference pattern: _start_whatsapp_bot (line 312-325)
    async def _start_whatsapp_bot(self, name: str, config: WhatsAppAgentConfig):
        agent = await self._get_agent(config.chatbot_id, config.system_prompt_override)
        if not agent:
            return
        from .whatsapp.wrapper import WhatsAppAgentWrapper
        wrapper = WhatsAppAgentWrapper(agent=agent, config=config, app=self.bot_manager.get_app())
        self.whatsapp_bots[name] = wrapper
        self.logger.info("Started WhatsApp bot '%s'", name)

    async def shutdown(self):  # line 413
        # ADD cleanup for msagentsdk_bots
```

### Does NOT Exist

- ~~`IntegrationBotManager.register_bot()`~~ — not a real method; bots are added in `_start_*` methods
- ~~`IntegrationBotManager.bots`~~ — no unified bots dict; each platform has its own dict
- ~~`MSAgentSDKConfig.validate()`~~ — validation is in `IntegrationBotConfig.validate()`, not per-config

---

## Implementation Notes

### Config dispatch in models.py

Add after the `elif kind == 'slack':` block (line 53):

```python
elif kind == 'msagentsdk':
    agents[name] = MSAgentSDKConfig.from_dict(name, agent_data)
```

### Validation in models.py

Add after the `elif isinstance(agent_config, SlackAgentConfig):` block:

```python
elif isinstance(agent_config, MSAgentSDKConfig):
    if not agent_config.anonymous_auth:
        if not agent_config.client_id:
            errors.append(f"Agent '{name}': missing client_id (required when anonymous_auth is false)")
        if not agent_config.client_secret:
            errors.append(f"Agent '{name}': missing client_secret (required when anonymous_auth is false)")
```

### Manager startup method

Follow `_start_whatsapp_bot` pattern exactly:

```python
async def _start_msagentsdk_bot(self, name: str, config: MSAgentSDKConfig):
    agent = await self._get_agent(config.chatbot_id, config.system_prompt_override if hasattr(config, "system_prompt_override") else None)
    if not agent:
        return
    from .msagentsdk.wrapper import MSAgentSDKWrapper
    wrapper = MSAgentSDKWrapper(
        agent=agent,
        config=config,
        app=self.bot_manager.get_app(),
    )
    self.msagentsdk_bots[name] = wrapper
    self.logger.info("Started MS Agent SDK bot '%s'", name)
```

### Key Constraints

- Import `MSAgentSDKConfig` at module level in `models.py` (it's a dataclass, no heavy deps).
- In `manager.py`, use TYPE_CHECKING for the wrapper import, lazy import inside `_start_msagentsdk_bot`.
- Keep shutdown simple: call `wrapper.stop()` for each bot, catch exceptions.

---

## Acceptance Criteria

- [ ] `IntegrationBotConfig.from_dict()` handles `kind: msagentsdk`
- [ ] `MSAgentSDKConfig` is in the `agents` Union type hint
- [ ] `validate()` checks `client_id`/`client_secret` when `anonymous_auth` is false
- [ ] `IntegrationBotManager` has `msagentsdk_bots` dict
- [ ] `startup()` dispatches to `_start_msagentsdk_bot()` for `MSAgentSDKConfig`
- [ ] `_start_msagentsdk_bot()` creates wrapper and stores it
- [ ] `shutdown()` stops SDK bots
- [ ] Existing integrations still work (no regressions)
- [ ] No linting errors

---

## Test Specification

```python
# tests/integrations/test_msagentsdk/test_manager_registration.py
import pytest
from parrot.integrations.models import IntegrationBotConfig


class TestMSAgentSDKConfigDispatch:
    def test_from_dict_msagentsdk(self):
        data = {
            "agents": {
                "CopilotBot": {
                    "kind": "msagentsdk",
                    "chatbot_id": "main_agent",
                    "client_id": "app-123",
                    "client_secret": "secret-456",
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert "CopilotBot" in config.agents
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
        assert isinstance(config.agents["CopilotBot"], MSAgentSDKConfig)

    def test_validate_missing_credentials(self):
        data = {
            "agents": {
                "CopilotBot": {
                    "kind": "msagentsdk",
                    "chatbot_id": "main_agent",
                    "anonymous_auth": False,
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        errors = config.validate()
        assert any("client_id" in e for e in errors)

    def test_validate_anonymous_ok(self):
        data = {
            "agents": {
                "CopilotBot": {
                    "kind": "msagentsdk",
                    "chatbot_id": "main_agent",
                    "anonymous_auth": True,
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        errors = config.validate()
        assert not any("client_id" in e for e in errors)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/microsoft-copilot-agent-sdk.spec.md` for full context
2. **Check dependencies** — verify TASK-1637 and TASK-1639 are completed
3. **Verify the Codebase Contract** — read `models.py` and `manager.py` to confirm line numbers
4. **Implement** the changes to both files
5. **Verify** existing integrations still parse correctly (run existing tests)
6. **Move this file** to `sdd/tasks/completed/TASK-1640-msagentsdk-manager-registration.md`
7. **Update index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-25.

Modified:
- `packages/ai-parrot-integrations/src/parrot/integrations/models.py`:
  - Added `from .msagentsdk.models import MSAgentSDKConfig` import at module level.
  - Added `MSAgentSDKConfig` to the `agents` Union type hint.
  - Added `elif kind == 'msagentsdk':` dispatch in `from_dict()`.
  - Added `elif isinstance(agent_config, MSAgentSDKConfig):` validation block in `validate()` that checks `client_id`/`client_secret` when `anonymous_auth` is false.

- `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`:
  - Added `MSAgentSDKConfig` to the models import.
  - Added `from .msagentsdk.wrapper import MSAgentSDKWrapper` to `TYPE_CHECKING` block.
  - Added `self.msagentsdk_bots: Dict[str, 'MSAgentSDKWrapper'] = {}` to `__init__`.
  - Added `elif isinstance(agent_config, MSAgentSDKConfig): await self._start_msagentsdk_bot(...)` dispatch in `startup()`.
  - Added `_start_msagentsdk_bot()` method (follows `_start_whatsapp_bot` pattern exactly).
  - Added SDK bot cleanup loop in `shutdown()`.
  - Added `self.msagentsdk_bots.clear()` at shutdown end.

All acceptance criteria met. Lint passes. Existing integrations unaffected.
