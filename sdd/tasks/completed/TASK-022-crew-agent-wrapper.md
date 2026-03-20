# TASK-022: CrewAgentWrapper

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-017, TASK-019, TASK-020, TASK-021
**Assigned-to**: claude-session

---

## Context

This task implements Module 7 from the spec. The `CrewAgentWrapper` is the per-agent message handler for crew context. It handles @mention routing, silent tool call execution, @mention-tagged responses, document send/receive, typing indicators, and status updates to the coordinator.

This is the most complex module — it bridges the AI agent with the Telegram crew protocol.

Implements spec Section 3, Module 7.

---

## Scope

- Implement `CrewAgentWrapper` class (composition, NOT inheritance from `TelegramAgentWrapper`)
- Implement handler registration using aiogram Router + `BotMentionedFilter`
- Implement `_handle_mention(message)` — processes @mention messages, routes to agent
- Implement `_handle_document(message)` — downloads document via DataPayload, passes to agent
- Implement response handling:
  - Always include @mention of sender in response
  - Silent tool calls (never published to group)
  - Long message chunking (under 4096 chars)
- Implement typing indicator while agent processes
- Implement status updates to CoordinatorBot (busy/ready transitions)
- Use `OutputMode.TELEGRAM` for `agent.ask()` calls
- Use existing `parse_response()` for unified response parsing

**NOT in scope**: Transport lifecycle (TASK-023), coordinator message management (TASK-021), config loading (TASK-016).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/crew_wrapper.py` | CREATE | CrewAgentWrapper implementation |
| `tests/test_telegram_crew/test_crew_wrapper.py` | CREATE | Unit tests with mocked agent and bot |

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from aiogram import Bot, Router
from aiogram.types import Message
from .agent_card import AgentCard
from .payload import DataPayload
from .mention import mention_from_username, format_reply
from .coordinator import CoordinatorBot

class CrewAgentWrapper:
    def __init__(
        self,
        bot: Bot,
        agent,  # AI-Parrot agent instance
        card: AgentCard,
        group_id: int,
        coordinator: CoordinatorBot,
        config: dict,
    ):
        self.bot = bot
        self.agent = agent
        self.card = card
        self.group_id = group_id
        self.coordinator = coordinator
        self.router = Router()
        self.logger = logging.getLogger(__name__)
        self._register_handlers()
```

### Key Constraints
- **Composition over inheritance**: Do NOT extend `TelegramAgentWrapper`
- Reuse existing `BotMentionedFilter` from `parrot/integrations/telegram/filters.py`
- Reuse existing `extract_query_from_mention` utility
- `agent.ask()` must receive `output_mode=OutputMode.TELEGRAM`
- Typing indicator: use `bot.send_chat_action(chat_id, "typing")` before processing
- Status lifecycle: set "busy" before processing, "ready" after
- Rate limiting: 0.3-0.5s sleep between consecutive messages
- Message chunking: split at 4096 chars preserving word boundaries
- Use `parse_response()` for response parsing (handles text, files, images)

### References in Codebase
- `parrot/integrations/telegram/agent_wrapper.py` — existing wrapper pattern (compose, don't inherit)
- `parrot/integrations/telegram/filters.py` — `BotMentionedFilter`
- `parrot/integrations/telegram/utils.py` — `extract_query_from_mention`, `parse_response`
- `parrot/bots/output.py` — `OutputMode` enum

---

## Acceptance Criteria

- [ ] Handler registered with `BotMentionedFilter` for the agent's bot
- [ ] @mention messages routed to `agent.ask()` correctly
- [ ] Responses always include @mention of the original sender
- [ ] Tool calls during `agent.ask()` are NOT published to the group
- [ ] Typing indicator shows while processing
- [ ] Status updates sent to coordinator (busy → ready)
- [ ] Long messages chunked under 4096 chars
- [ ] Documents handled via DataPayload
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_crew_wrapper.py -v`
- [ ] Import works: `from parrot.integrations.telegram.crew.crew_wrapper import CrewAgentWrapper`

---

## Test Specification

```python
# tests/test_telegram_crew/test_crew_wrapper.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from parrot.integrations.telegram.crew.crew_wrapper import CrewAgentWrapper
from parrot.integrations.telegram.crew.agent_card import AgentCard
from parrot.integrations.telegram.crew.coordinator import CoordinatorBot
from parrot.integrations.telegram.crew.registry import CrewRegistry


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    agent.ask = AsyncMock(return_value="Test response")
    return agent


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.send_document = AsyncMock()
    return bot


@pytest.fixture
def sample_card():
    return AgentCard(
        agent_id="agent1",
        agent_name="TestAgent",
        telegram_username="test_bot",
        telegram_user_id=111,
        model="gpt-4",
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


class TestCrewAgentWrapper:
    def test_sender_mention_extraction(self):
        """Extracts @mention from message.from_user."""
        message = MagicMock()
        message.from_user.username = "jesus"
        # Verify mention extraction logic
        assert message.from_user.username == "jesus"

    @pytest.mark.asyncio
    async def test_parse_response_text(self, mock_agent):
        """Parses string response from agent."""
        mock_agent.ask = AsyncMock(return_value="Simple text response")
        result = await mock_agent.ask("test query")
        assert result == "Simple text response"

    @pytest.mark.asyncio
    async def test_parse_response_with_files(self, mock_agent):
        """Parses response with file attachments."""
        response = MagicMock()
        response.text = "Here is the data"
        response.files = ["/tmp/data.csv"]
        mock_agent.ask = AsyncMock(return_value=response)
        result = await mock_agent.ask("generate report")
        assert hasattr(result, "files")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-017, TASK-019, TASK-020, TASK-021 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-022-crew-agent-wrapper.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `CrewAgentWrapper` with composition pattern (not inheriting from TelegramAgentWrapper). Registers @mention and document handlers via aiogram Router + BotMentionedFilter. Handles typing indicators, busy/ready status updates to CoordinatorBot, message chunking under 4096 chars, document download via DataPayload, and @mention-prefixed responses. Uses `parse_response()` for unified response parsing and `OutputMode.TELEGRAM` for agent.ask() calls. All 24 unit tests pass.

**Deviations from spec**: Added optional `payload` parameter to constructor for DataPayload dependency injection (cleaner than requiring it in config dict). Document handler accepts all documents in the group rather than only @mentioned ones — additional filtering can be added at the transport layer.
