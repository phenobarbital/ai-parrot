---
type: Wiki Overview
title: 'TASK-1638: Bridge Agent (ParrotM365Agent)'
id: doc:sdd-tasks-completed-task-1638-msagentsdk-bridge-agent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates the core bridge class that implements the MS Agent SDK's
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.agent
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1638: Bridge Agent (ParrotM365Agent)

**Feature**: FEAT-259 — Microsoft Copilot Agent SDK Integration
**Spec**: `sdd/specs/microsoft-copilot-agent-sdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1637
**Assigned-to**: unassigned

---

## Context

This task creates the core bridge class that implements the MS Agent SDK's
`Agent` protocol, connecting `TurnContext` activities to ai-parrot's
`AbstractBot.ask()` method. This is the heart of the integration.

Implements: Spec §3 Module 2 (Bridge Agent).

---

## Scope

- Create `agent.py` in the `msagentsdk/` package.
- Implement `ParrotM365Agent` class with `on_turn(context: TurnContext)` method.
- Handle activity types:
  - `message` → call `agent.ask(text, session_id, user_id)` → `context.send_activity(response.content)`
  - `conversationUpdate` (members_added) → send welcome message
  - `typing` → send typing indicator back (or ignore)
  - Unknown types → log and ignore
- Use `navconfig.logging` for logging.
- All MS SDK imports must be lazy (inside the class/methods, not module-level).

**NOT in scope**: HTTP route registration, wrapper class, manager integration, auth config.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` | CREATE | `ParrotM365Agent` bridge class |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py` | MODIFY | Add `ParrotM365Agent` export |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot  # verified: packages/ai-parrot/src/parrot/bots/abstract.py:156
from parrot.models.responses import AIMessage  # verified: packages/ai-parrot/src/parrot/models/responses.py:72
from navconfig.logging import logging          # verified: used throughout integrations

# MS SDK imports — LAZY ONLY (inside methods, not module-level)
from microsoft_agents.hosting.core import TurnContext       # from microsoft-agents-hosting-core
from microsoft_agents.activity import Activity, ActivityTypes  # from microsoft-agents-activity
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:3693
class AbstractBot(...):
    @abstractmethod
    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        # ... many optional params ...
        **kwargs
    ) -> AIMessage:  # line 3713

# packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
    output: Any       # line 79 — the main response content
    @property
    def content(self) -> Any:  # line 227 — alias for self.output
        return self.output

# MS Agent SDK protocol (from microsoft_agents.hosting.core)
class Agent(Protocol):
    async def on_turn(self, context: TurnContext): ...

# TurnContext key attributes/methods:
#   context.activity: Activity          — inbound message
#   context.activity.type: str          — "message", "conversationUpdate", etc.
#   context.activity.text: str          — message text
#   context.activity.from_property: ChannelAccount  — sender (.id, .name)
#   context.activity.conversation: ConversationAccount  — conversation (.id)
#   context.activity.members_added: List[ChannelAccount]
#   await context.send_activity(text_or_activity) — send response
```

### Does NOT Exist

- ~~`AbstractBot.process()`~~ — not a real method; use `ask()`
- ~~`AbstractBot.chat()`~~ — not a real method; use `ask()`
- ~~`AbstractBot.run()`~~ — not a real method; use `ask()`
- ~~`AIMessage.text`~~ — not a real attribute; use `.content` property
- ~~`AIMessage.metadata`~~ — not a real attribute; use `.usage`, `.model`, `.provider`
- ~~`context.activity.from_`~~ — wrong field name; use `context.activity.from_property`
- ~~`from microsoft.agents import Agent`~~ — old namespace; use `microsoft_agents`

---

## Implementation Notes

### Pattern to Follow

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Optional
from navconfig.logging import logging

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot


class ParrotM365Agent:
    """Bridges ai-parrot AbstractBot to the MS 365 Agent protocol."""
    
    def __init__(self, parrot_agent: AbstractBot, welcome_message: Optional[str] = None):
        self.parrot_agent = parrot_agent
        self.welcome_message = welcome_message or "Hello! I'm ready to help."
        self.logger = logging.getLogger(f"ParrotM365Agent.{type(parrot_agent).__name__}")
    
    async def on_turn(self, context):
        """Handle an incoming Activity from the MS Agent SDK."""
        from microsoft_agents.activity import ActivityTypes
        
        activity = context.activity
        
        if activity.type == ActivityTypes.message:
            await self._handle_message(context)
        elif activity.type == ActivityTypes.conversation_update:
            await self._handle_conversation_update(context)
        else:
            self.logger.debug("Ignoring activity type: %s", activity.type)
    
    async def _handle_message(self, context):
        activity = context.activity
        text = activity.text
        if not text or not text.strip():
            return
        
        user_id = activity.from_property.id if activity.from_property else None
        session_id = activity.conversation.id if activity.conversation else None
        
        self.logger.info("Message from user=%s session=%s", user_id, session_id)
        
        response = await self.parrot_agent.ask(
            question=text.strip(),
            session_id=session_id,
            user_id=user_id,
        )
        await context.send_activity(str(response.content))
    
    async def _handle_conversation_update(self, context):
        if context.activity.members_added:
            for member in context.activity.members_added:
                if member.id != context.activity.recipient.id:
                    await context.send_activity(self.welcome_message)
```

### Key Constraints

- All `microsoft_agents.*` imports MUST be inside methods (lazy), not at module level.
- Use `TYPE_CHECKING` guard for `AbstractBot` to avoid circular imports.
- Log at INFO for messages, DEBUG for ignored activity types.
- Handle None/empty text gracefully (don't call `ask()` with empty string).
- Use `str(response.content)` to ensure the response is always a string.

---

## Acceptance Criteria

- [ ] `ParrotM365Agent` implements `on_turn(context)` method
- [ ] Message activities route to `agent.ask()` and response is sent back
- [ ] Conversation updates with new members trigger welcome message
- [ ] Empty/None text is handled gracefully (no crash, no agent call)
- [ ] Unknown activity types are logged and ignored
- [ ] All MS SDK imports are lazy (inside methods)
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/`

---

## Test Specification

```python
# tests/integrations/test_msagentsdk/test_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestParrotM365Agent:
    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.ask = AsyncMock(return_value=MagicMock(content="Hello back!"))
        return bot
    
    @pytest.fixture
    def agent(self, mock_bot):
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent
        return ParrotM365Agent(mock_bot)
    
    @pytest.fixture
    def mock_context(self):
        ctx = AsyncMock()
        ctx.activity = MagicMock()
        ctx.activity.type = "message"
        ctx.activity.text = "Hello, agent!"
        ctx.activity.from_property = MagicMock(id="user-123")
        ctx.activity.conversation = MagicMock(id="conv-456")
        ctx.activity.recipient = MagicMock(id="bot-789")
        ctx.send_activity = AsyncMock()
        return ctx
    
    @pytest.mark.asyncio
    async def test_message_calls_ask(self, agent, mock_context, mock_bot):
        await agent.on_turn(mock_context)
        mock_bot.ask.assert_called_once_with(
            question="Hello, agent!",
            session_id="conv-456",
            user_id="user-123",
        )
        mock_context.send_activity.assert_called_once_with("Hello back!")
    
    @pytest.mark.asyncio
    async def test_empty_text_ignored(self, agent, mock_context, mock_bot):
        mock_context.activity.text = ""
        await agent.on_turn(mock_context)
        mock_bot.ask.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_conversation_update_welcome(self, agent, mock_context):
        mock_context.activity.type = "conversationUpdate"
        member = MagicMock(id="new-user")
        mock_context.activity.members_added = [member]
        await agent.on_turn(mock_context)
        mock_context.send_activity.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/microsoft-copilot-agent-sdk.spec.md` for full context
2. **Check dependencies** — verify TASK-1637 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AbstractBot.ask()` and `AIMessage.content` signatures
4. **Implement** the bridge agent class
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1638-msagentsdk-bridge-agent.md`
7. **Update index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-25.

Created:
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` — `ParrotM365Agent` class with lazy `microsoft_agents.*` imports.

Key implementation decisions:
- `on_turn()` dispatches on `ActivityTypes.message` and `ActivityTypes.conversation_update`; all other types logged at DEBUG and ignored.
- `_handle_message()` returns early on empty/whitespace text without calling `ask()`.
- Uses `activity.from_property` (not `from_`) for sender identity — per Codebase Contract.
- `str(response.content)` ensures the reply is always a string regardless of LLM output type.
- All `microsoft_agents.*` imports are inside methods (lazy).

All acceptance criteria met. Lint passes.
