# TASK-021: CoordinatorBot

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-017, TASK-018
**Assigned-to**: claude-session

---

## Context

This task implements Module 6 from the spec. The `CoordinatorBot` is a non-agent bot that manages the pinned registry message in the Telegram supergroup. It provides real-time visibility of which agents are online, busy, or offline.

Implements spec Section 3, Module 6.

---

## Scope

- Implement `CoordinatorBot` class
- Implement `start()` — initializes bot, sends initial pinned registry message
- Implement `stop()` — graceful shutdown
- Implement `on_agent_join(card: AgentCard)` — registers agent, updates pinned message
- Implement `on_agent_leave(username: str)` — unregisters agent, updates pinned message
- Implement `on_agent_status_change(username, status, task=None)` — updates status, edits pinned
- Implement `update_registry()` — renders and edits the pinned message (serialized with asyncio.Lock)
- Implement `_render_registry()` — builds the pinned message text from registry

**NOT in scope**: Custom commands (`/list`, `/card`, `/status`), message routing, agent wrapper logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/coordinator.py` | CREATE | CoordinatorBot implementation |
| `tests/test_telegram_crew/test_coordinator.py` | CREATE | Unit tests with mocked Bot |

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import logging
from aiogram import Bot
from .registry import CrewRegistry
from .agent_card import AgentCard

class CoordinatorBot:
    def __init__(self, token: str, group_id: int, registry: CrewRegistry):
        self.bot = Bot(token=token)
        self.group_id = group_id
        self.registry = registry
        self._pinned_message_id: Optional[int] = None
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def update_registry(self) -> None:
        async with self._lock:
            text = self._render_registry()
            if self._pinned_message_id:
                try:
                    await self.bot.edit_message_text(
                        text=text,
                        chat_id=self.group_id,
                        message_id=self._pinned_message_id,
                    )
                except Exception:
                    # "message not modified" — silently ignore
                    pass
```

### Key Constraints
- Use `asyncio.Lock` to serialize pinned message edits (NOT `threading.Lock`)
- Silently ignore Telegram "message not modified" errors
- Rate limiting: 0.3-0.5s sleep between consecutive edits
- Initial pinned message sent on `start()` and pinned via `pin_chat_message()`
- Use aiogram v3 `Bot` class
- Use `logging.getLogger(__name__)`

### References in Codebase
- `parrot/integrations/telegram/bot_manager.py` — existing bot lifecycle patterns
- `parrot/integrations/telegram/handlers/` — handler registration patterns

---

## Acceptance Criteria

- [ ] `_render_registry()` produces correct pinned message text from registry entries
- [ ] `on_agent_join()` registers agent and triggers pinned update (mocked)
- [ ] `on_agent_leave()` unregisters agent and triggers pinned update (mocked)
- [ ] `on_agent_status_change()` updates status and triggers pinned update (mocked)
- [ ] `update_registry()` serializes concurrent edit attempts with asyncio.Lock
- [ ] "message not modified" errors are silently handled
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_coordinator.py -v`
- [ ] Import works: `from parrot.integrations.telegram.crew.coordinator import CoordinatorBot`

---

## Test Specification

```python
# tests/test_telegram_crew/test_coordinator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from parrot.integrations.telegram.crew.coordinator import CoordinatorBot
from parrot.integrations.telegram.crew.registry import CrewRegistry
from parrot.integrations.telegram.crew.agent_card import AgentCard, AgentSkill


@pytest.fixture
def registry():
    return CrewRegistry()


@pytest.fixture
def coordinator(registry):
    with patch("parrot.integrations.telegram.crew.coordinator.Bot") as MockBot:
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
        mock_bot.edit_message_text = AsyncMock()
        mock_bot.pin_chat_message = AsyncMock()
        MockBot.return_value = mock_bot
        coord = CoordinatorBot(
            token="fake:token",
            group_id=-100123,
            registry=registry,
        )
        coord.bot = mock_bot
        yield coord


@pytest.fixture
def sample_card():
    return AgentCard(
        agent_id="agent1",
        agent_name="DataAgent",
        telegram_username="data_bot",
        telegram_user_id=111,
        model="gpt-4",
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


class TestCoordinatorBot:
    def test_render_registry_empty(self, coordinator):
        text = coordinator._render_registry()
        assert isinstance(text, str)

    @pytest.mark.asyncio
    async def test_agent_join_updates_pinned(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        await coordinator.on_agent_join(sample_card)
        coordinator.bot.edit_message_text.assert_called()

    @pytest.mark.asyncio
    async def test_status_change(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        await coordinator.on_agent_join(sample_card)
        await coordinator.on_agent_status_change("data_bot", "busy", "processing Q2")
        assert coordinator.registry.get("data_bot").status == "busy"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-017 and TASK-018 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-021-coordinator-bot.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `CoordinatorBot` with start/stop lifecycle, agent join/leave/status_change handlers, asyncio.Lock-serialized pinned message editing, and _render_registry() for formatted output. Added optional `bot` parameter to constructor to allow dependency injection for testing (avoids aiogram token validation in tests). Silently handles "message not modified" errors. All 15 unit tests pass.

**Deviations from spec**: Added optional `bot` parameter to constructor for testability (not in original spec pattern, but needed for clean testing with aiogram v3 token validation).
