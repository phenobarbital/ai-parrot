# TASK-023: TelegramCrewTransport

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-016, TASK-018, TASK-021, TASK-022
**Assigned-to**: claude-session

---

## Context

This task implements Module 8 from the spec. `TelegramCrewTransport` is the top-level orchestrator that manages the full lifecycle of a multi-agent crew in a Telegram supergroup. It initializes all bots, manages the coordinator, and provides the public API for sending messages/documents.

Implements spec Section 3, Module 8.

---

## Scope

- Implement `TelegramCrewTransport` class
- Implement `start()` — initializes coordinator bot, creates CrewAgentWrappers for each agent, registers all agents, starts polling
- Implement `stop()` — graceful shutdown: unregister all agents, stop coordinator, close bot sessions
- Implement `send_message(from_username, mention, text, reply_to_message_id=None)` — sends message from the specified agent bot
- Implement `send_document(from_username, mention, file_path, caption, reply_to_message_id=None)` — sends document from the specified agent bot
- Implement `list_online_agents()` — returns list of active agents from registry
- Implement async context manager (`__aenter__`, `__aexit__`)
- Implement `from_config(config: TelegramCrewConfig)` classmethod
- Integrate with `TelegramBotManager.get_bot()` for agent instance retrieval

**NOT in scope**: Custom coordinator commands, AgentCrew DAG integration, persistent registry.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/transport.py` | CREATE | TelegramCrewTransport implementation |
| `tests/test_telegram_crew/test_transport.py` | CREATE | Unit tests with mocked components |

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from typing import Dict, List, Optional
from .config import TelegramCrewConfig
from .registry import CrewRegistry
from .coordinator import CoordinatorBot
from .crew_wrapper import CrewAgentWrapper

class TelegramCrewTransport:
    def __init__(self, config: TelegramCrewConfig):
        self.config = config
        self.registry = CrewRegistry()
        self.coordinator: Optional[CoordinatorBot] = None
        self._wrappers: Dict[str, CrewAgentWrapper] = {}
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_config(cls, config: TelegramCrewConfig) -> "TelegramCrewTransport":
        return cls(config=config)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.stop()
```

### Key Constraints
- Use `TelegramBotManager.get_bot(chatbot_id)` to retrieve agent instances
- Each agent bot needs its own `aiogram.Bot` instance and `Dispatcher`
- Coordinator bot is separate from agent bots
- Graceful shutdown must: unregister all agents, update pinned, close all bot sessions
- Startup order: coordinator first, then agent wrappers
- Use `logging.getLogger(__name__)`
- Rate limiting between bot startups (0.3-0.5s)

### References in Codebase
- `parrot/integrations/telegram/bot_manager.py` — `TelegramBotManager` and `get_bot()`
- `parrot/integrations/telegram/agent_wrapper.py` — existing wrapper lifecycle patterns

---

## Acceptance Criteria

- [ ] `TelegramCrewTransport` can be constructed from `TelegramCrewConfig`
- [ ] `start()` initializes coordinator and all agent wrappers
- [ ] `stop()` gracefully shuts down all bots
- [ ] `send_message()` delegates to the correct agent wrapper
- [ ] `send_document()` delegates to the correct agent wrapper
- [ ] `list_online_agents()` returns registry contents
- [ ] Async context manager works (`async with TelegramCrewTransport(config) as transport:`)
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_transport.py -v`
- [ ] Import works: `from parrot.integrations.telegram.crew.transport import TelegramCrewTransport`

---

## Test Specification

```python
# tests/test_telegram_crew/test_transport.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.integrations.telegram.crew.transport import TelegramCrewTransport
from parrot.integrations.telegram.crew.config import TelegramCrewConfig, CrewAgentEntry


@pytest.fixture
def crew_config():
    return TelegramCrewConfig(
        group_id=-1001234567890,
        coordinator_token="fake:coordinator_token",
        coordinator_username="test_coordinator_bot",
        hitl_user_ids=[123456789],
        agents={
            "TestAgent": CrewAgentEntry(
                chatbot_id="test_agent",
                bot_token="fake:agent_token",
                username="test_agent_bot",
                tags=["test"],
                skills=[{"name": "echo", "description": "Echoes input"}],
            )
        },
    )


class TestTelegramCrewTransport:
    def test_from_config(self, crew_config):
        transport = TelegramCrewTransport.from_config(crew_config)
        assert transport.config.group_id == -1001234567890

    @pytest.mark.asyncio
    async def test_start_stop(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        # Mock internal components
        transport.coordinator = AsyncMock()
        transport._wrappers = {}
        await transport.stop()
        transport.coordinator.stop.assert_called_once()

    def test_list_online(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        agents = transport.list_online_agents()
        assert isinstance(agents, list)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-016, TASK-018, TASK-021, TASK-022 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-023-crew-transport.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `TelegramCrewTransport` with full lifecycle management. `start()` creates a shared DataPayload, starts CoordinatorBot, then for each configured agent creates an aiogram Bot, builds an AgentCard, creates a CrewAgentWrapper, registers with coordinator, and starts aiogram polling in a background task. `stop()` cancels all polling tasks, unregisters agents, stops coordinator, closes bot sessions, and cleans up temp files. Public API includes `send_message()`, `send_document()`, `list_online_agents()`, `get_wrapper()`, `from_config()` classmethod, and async context manager. All 26 unit tests pass.

**Deviations from spec**: Added optional `bot_manager` parameter to constructor (spec assumed it would use `TelegramBotManager.get_bot()` directly, but DI is cleaner). Added `get_wrapper()` method not in original spec for accessing individual wrappers. Added `_start_agent()` as separate method for per-agent startup with error isolation.
