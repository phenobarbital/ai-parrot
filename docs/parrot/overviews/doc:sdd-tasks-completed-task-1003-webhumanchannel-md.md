---
type: Wiki Overview
title: 'TASK-1003: Implement WebHumanChannel'
id: doc:sdd-tasks-completed-task-1003-webhumanchannel-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the `WebHumanChannel` that bridges the HITL (`HumanInteractionManager`)
  with web users via the existing `UserSocketManager` WebSocket infrastructure. It
  is the first module in the web HITL stack (§3 Module 1 in the spec).
relates_to:
- concept: mod:parrot.handlers.user
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
- concept: mod:parrot.human.channels.web
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

# TASK-1003: Implement WebHumanChannel

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements the `WebHumanChannel` that bridges the HITL (`HumanInteractionManager`) with web users via the existing `UserSocketManager` WebSocket infrastructure. It is the first module in the web HITL stack (§3 Module 1 in the spec).

The channel translates internal `HumanInteraction` objects into JSON payloads and delivers them over WebSocket channels named after the user's session ID. This is the foundational piece on which `WebHumanTool` and the response handler depend.

---

## Scope

- Implement `WebHumanChannel` class in `packages/ai-parrot/src/parrot/human/channels/web.py`.
- Implement all four abstract methods from `HumanChannel` base class:
  - `send_interaction(interaction, recipient)` — serialize and push question payload via `UserSocketManager.notify_channel`.
  - `register_response_handler(callback)` — store the callback (required by contract; not invoked internally).
  - `send_notification(recipient, message)` — emit a `hitl:notification` payload.
  - `cancel_interaction(interaction_id, recipient)` — emit a `hitl:cancel` payload.
- Add a `channel_type` class attribute set to `"web"`.
- Add Google-style docstrings to the class and all public methods.
- Add `self.logger` initialization in `__init__`.

**NOT in scope**:
- `WebHumanTool` — belongs to TASK-1004 and TASK-1005.
- HTTP endpoint — belongs to TASK-1006.
- Bootstrap logic — belongs to TASK-1007.
- Integration with `AgentTalk` — belongs to TASK-1008.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/channels/web.py` | CREATE | `WebHumanChannel` class with all four abstract methods. |
| `packages/ai-parrot/tests/human/test_web_channel.py` | CREATE | Unit tests for `WebHumanChannel`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot/human/channels/base.py
from parrot.human.channels.base import HumanChannel                             # parrot/human/channels/base.py:11

# parrot/human/models.py
from parrot.human.models import (                                              # parrot/human/models.py:11-120
    HumanInteraction,
    HumanResponse,
    InteractionType,
)

# Web infra
from parrot.handlers.user import UserSocketManager                              # parrot/handlers/user.py:27

# Logging
import logging
from typing import Callable, Awaitable, Any, Dict, Optional
```

### Existing Signatures to Use

```python
# parrot/human/channels/base.py:11
class HumanChannel(ABC):
    channel_type: str = "base"                                                  # line 19

    @abstractmethod
    async def send_interaction(
        self, interaction: "HumanInteraction", recipient: str,                  # line 22
    ) -> bool: ...

    @abstractmethod
    async def register_response_handler(                                        # line 33
        self, callback: Callable[["HumanResponse"], Awaitable[None]],
    ) -> None: ...

    @abstractmethod
    async def send_notification(                                               # line 41
        self, recipient: str, message: str,
    ) -> None: ...

    @abstractmethod
    async def cancel_interaction(                                              # line 50
        self, interaction_id: str, recipient: str,
    ) -> None: ...

# parrot/handlers/user.py:756
class UserSocketManager(WebSocketManager):
    async def notify_channel(                                                  # line 756
        self, channel_name: str, message: Dict[str, Any],
    ) -> bool: ...
```

### Does NOT Exist

- ~~`WebHumanChannel`~~ — to be created in this task.
- ~~`HumanInteraction.to_dict()` or similar serializer~~ — does not exist; must manually construct the JSON payload from `HumanInteraction` attributes per §2 Data Models in the spec.
- ~~`UserSocketManager.send_interaction`~~ — does not exist; only `notify_channel` exists.
- ~~`parrot.human.channels.web` module~~ — to be created.

---

## Implementation Notes

### Pattern to Follow

Mirror the `TelegramHumanChannel` pattern (located at `parrot/integrations/telegram/channels/human.py`). Key points:
- Constructor takes the upstream channel dependencies (in this case, `UserSocketManager`).
- Store the response callback in an instance variable but do **not** invoke it.
- Serialize `HumanInteraction` to the wire format documented in spec §2 Data Models.
- Return `True` on success, `False` if the channel has no subscribers.

### Key Constraints

- Every interaction type (`APPROVAL`, `SINGLE_CHOICE`, `MULTI_CHOICE`, `FORM`, `FREE_TEXT`) must produce the correct payload shape per spec.
- The `recipient` parameter is the WebSocket channel name (typically the user's `session_id`).
- Async-first: all methods are `async`.
- Logging: use `self.logger.info`, `self.logger.debug`, `self.logger.warning` at key points.

---

## Acceptance Criteria

- [ ] `WebHumanChannel` class exists at `parrot/human/channels/web.py`.
- [ ] All four abstract methods are implemented and async.
- [ ] `send_interaction` produces JSON payload with correct shape for each `interaction_type`.
- [ ] `send_interaction` calls `self.socket_manager.notify_channel(recipient, payload)` exactly once per call.
- [ ] `send_interaction` returns `bool` (result of `notify_channel`).
- [ ] `cancel_interaction` emits `{"type": "hitl:cancel", "interaction_id": ..., "reason": ...}`.
- [ ] `send_notification` emits `{"type": "hitl:notification", "recipient": ..., "message": ...}`.
- [ ] `channel_type` class attribute is set to `"web"`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/human/test_web_channel.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/human/channels/web.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/human/test_web_channel.py
import pytest
from parrot.human.channels.web import WebHumanChannel
from parrot.human.models import HumanInteraction, InteractionType, ChoiceOption
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_socket_manager():
    """Fake UserSocketManager that records all notify_channel calls."""
    manager = MagicMock()
    manager.notify_channel = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def web_channel(fake_socket_manager):
    return WebHumanChannel(socket_manager=fake_socket_manager)


class TestWebHumanChannel:
    async def test_web_channel_send_approval(self, web_channel, fake_socket_manager):
        """send_interaction with APPROVAL produces correct payload shape."""
        interaction = HumanInteraction(
            interaction_type=InteractionType.APPROVAL,
            question="Approve this?",
            context="test",
        )
        result = await web_channel.send_interaction(interaction, "sess-123")
        assert result is True
        assert fake_socket_manager.notify_channel.called

    async def test_web_channel_send_single_choice(self, web_channel, fake_socket_manager):
        """send_interaction with SINGLE_CHOICE includes options."""
        options = [
            ChoiceOption(key="a", label="Option A"),
            ChoiceOption(key="b", label="Option B"),
        ]
        interaction = HumanInteraction(
            interaction_type=InteractionType.SINGLE_CHOICE,
            question="Pick one",
            options=options,
        )
        result = await web_channel.send_interaction(interaction, "sess-123")
        assert result is True
        call_args = fake_socket_manager.notify_channel.call_args
        payload = call_args[0][1]
        assert payload["options"] == [{"key": "a", "label": "Option A"}, {"key": "b", "label": "Option B"}]

    async def test_web_channel_send_form(self, web_channel, fake_socket_manager):
        """send_interaction with FORM includes form_schema."""
        form_schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        interaction = HumanInteraction(
            interaction_type=InteractionType.FORM,
            question="Fill out",
            form_schema=form_schema,
        )
        result = await web_channel.send_interaction(interaction, "sess-123")
        assert result is True
        call_args = fake_socket_manager.notify_channel.call_args
        payload = call_args[0][1]
        assert payload["form_schema"] == form_schema

    async def test_web_channel_returns_false_when_channel_missing(self, web_channel, fake_socket_manager):
        """send_interaction returns False if notify_channel returns False."""
        fake_socket_manager.notify_channel = AsyncMock(return_value=False)
        interaction = HumanInteraction(
            interaction_type=InteractionType.APPROVAL,
            question="Test",
        )
        result = await web_channel.send_interaction(interaction, "sess-123")
        assert result is False

    async def test_web_channel_cancel(self, web_channel, fake_socket_manager):
        """cancel_interaction emits hitl:cancel payload."""
        await web_channel.cancel_interaction("uuid-123", "sess-123")
        call_args = fake_socket_manager.notify_channel.call_args
        channel, payload = call_args[0]
        assert channel == "sess-123"
        assert payload["type"] == "hitl:cancel"
        assert payload["interaction_id"] == "uuid-123"

    async def test_web_channel_register_response_handler(self, web_channel):
        """register_response_handler stores callback without raising."""
        callback = AsyncMock()
        await web_channel.register_response_handler(callback)
        # Should not raise and callback should be stored
        assert web_channel._response_callback is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — none, this is the first module
3. **Verify the Codebase Contract** — confirm imports and class signatures are current
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1003-webhumanchannel.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
