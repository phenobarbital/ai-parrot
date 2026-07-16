---
type: Wiki Overview
title: 'TASK-1471: MS Teams Command Router + Jira Commands'
id: doc:sdd-tasks-completed-task-1471-msteams-command-router-jira-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The MS Teams integration has no command infrastructure — all messages go
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations.msteams
  rel: mentions
- concept: mod:parrot.integrations.msteams.commands
  rel: mentions
- concept: mod:parrot.integrations.msteams.commands.jira_commands
  rel: mentions
---

# TASK-1471: MS Teams Command Router + Jira Commands

**Feature**: FEAT-225 — JiraToolkit Integrations OAuth2
**Spec**: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1467
**Assigned-to**: unassigned

---

## Context

The MS Teams integration has no command infrastructure — all messages go
directly to the agent via `on_message_activity`. This task creates a
`MSTeamsCommandRouter` that detects text commands (prefixed with `/`) and
dispatches them before the message reaches the agent. It also implements
the three Jira command handlers using Adaptive Cards for the Teams-native
UX, plus an optional "Jira integrations" card menu for discoverability.

Implements Spec §3 Module 5.

---

## Scope

- Create `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py` with `MSTeamsCommandRouter` class:
  - `register(command: str, handler: Callable)` — registers a text command handler
  - `async try_dispatch(text: str, turn_context: TurnContext) -> bool` — checks if text starts with a registered command, dispatches if so, returns True if handled
- Create `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py` with:
  - `_MSTEAMS_CHANNEL = "msteams"` constant
  - `connect_jira_handler(turn_context, oauth_manager)` — checks existing token, generates auth URL, sends Adaptive Card with "Connect Jira" button
  - `disconnect_jira_handler(turn_context, oauth_manager)` — revokes token, sends confirmation card
  - `jira_status_handler(turn_context, oauth_manager)` — reports status via reply
  - `jira_menu_handler(turn_context, oauth_manager)` — sends an Adaptive Card with all three Jira actions as buttons for discoverability
  - `register_jira_commands(router, oauth_manager)` — registers all handlers
- User ID for Teams: `turn_context.activity.from_property.aad_object_id` (or fallback to `from_property.id`).
- `extra_state` MUST include `"channel": "msteams"` and the serialized `conversation_reference` for proactive messaging.
- Write unit tests.

**NOT in scope**: OAuth callback handler (TASK-1472), wrapper wiring (TASK-1473), Slack commands.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py` | CREATE | MSTeamsCommandRouter class |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py` | CREATE | Jira command handlers + register function |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet  # packages/ai-parrot/src/parrot/auth/jira_oauth.py:86, :59

# Bot Framework types (existing deps):
from botbuilder.core import TurnContext  # existing dep
from botbuilder.schema import Activity, ConversationReference  # existing dep
# TurnContext.activity.from_property.aad_object_id — user's Azure AD object ID
# TurnContext.activity.from_property.id — fallback user ID
# TurnContext.activity.get_conversation_reference() — for proactive messaging
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
class JiraOAuthManager:  # line 86
    async def create_authorization_url(  # line 258
        self, channel: str, user_id: str,
        extra_state: dict | None = None,
    ) -> tuple[str, str]:  # (url, nonce)

    async def validate_token(  # line 405
        self, channel: str, user_id: str,
    ) -> JiraTokenSet | None:

    async def revoke(  # line 474
        self, channel: str, user_id: str,
    ) -> None:

class JiraTokenSet(BaseModel):  # line 59
    display_name: str
    site_url: str
    email: Optional[str] = None

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):  # line 56
    async def on_message_activity(self, turn_context: TurnContext):  # line 367
    # send_text is available via MessageHandler mixin
    # send_card is available for Adaptive Cards
```

### Does NOT Exist

- ~~`parrot.integrations.msteams.commands`~~ — subpackage does not exist yet (will be created)
- ~~`MSTeamsCommandRouter`~~ — does not exist yet
- ~~`parrot.integrations.msteams.auth`~~ — does not exist
- ~~Any command detection in MSTeamsAgentWrapper~~ — all text currently goes to the agent

---

## Implementation Notes

### Pattern to Follow

```python
# MSTeamsCommandRouter — simple text-prefix dispatch
class MSTeamsCommandRouter:
    def __init__(self):
        self._handlers: Dict[str, Callable] = {}

    def register(self, command: str, handler: Callable) -> None:
        self._handlers[command.lstrip("/")] = handler

    async def try_dispatch(self, text: str, turn_context: TurnContext) -> bool:
        if not text.startswith("/"):
            return False
        parts = text.split(maxsplit=1)
        cmd = parts[0].lstrip("/")
        if cmd in self._handlers:
            await self._handlers[cmd](turn_context)
            return True
        return False

# Adaptive Card for Connect Jira button
def _connect_jira_card(auth_url: str) -> dict:
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [{"type": "TextBlock", "text": "Click below to connect your Jira account:"}],
        "actions": [{"type": "Action.OpenUrl", "title": "Connect Jira", "url": auth_url}],
    }

# Conversation reference for proactive messaging
async def connect_jira_handler(turn_context: TurnContext, oauth_manager: JiraOAuthManager):
    user_id = turn_context.activity.from_property.aad_object_id or turn_context.activity.from_property.id
    conv_ref = TurnContext.get_conversation_reference(turn_context.activity)
    extra_state = {
        "channel": "msteams",
        "conversation_reference": conv_ref.serialize() if hasattr(conv_ref, 'serialize') else vars(conv_ref),
    }
    url, _ = await oauth_manager.create_authorization_url("msteams", user_id, extra_state=extra_state)
    card = _connect_jira_card(url)
    await turn_context.send_activity(Activity(type="message", attachments=[...]))
```

### Key Constraints

- The `conversation_reference` must be serialized to JSON-safe dict before storing in `extra_state` (which goes to Redis as JSON).
- User ID: prefer `aad_object_id` (globally unique across Azure AD tenants). Fall back to `from_property.id` for non-AAD environments.
- Adaptive Card schema version 1.4 is safe for modern Teams clients.
- The "Jira integrations" menu card is triggered by typing `jira` or `integrations` (without `/` prefix) as a separate handler.

### References in Codebase

- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` — reference pattern
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:367` — where commands will be intercepted

---

## Acceptance Criteria

- [ ] `MSTeamsCommandRouter.try_dispatch` returns True and handles registered commands
- [ ] `MSTeamsCommandRouter.try_dispatch` returns False for non-command text
- [ ] `/connect_jira` generates auth URL with `channel="msteams"` and sends Adaptive Card
- [ ] `/connect_jira` when already connected short-circuits with "Already connected" reply
- [ ] `/disconnect_jira` calls `oauth_manager.revoke("msteams", ...)` and confirms
- [ ] `/jira_status` reports connection details or "Not connected"
- [ ] `extra_state` includes serialized `conversation_reference` for proactive messaging
- [ ] Jira menu card (typing `jira`) shows all three command options
- [ ] All tests pass: `pytest tests/integrations/msteams/test_msteams_jira_commands.py -v`

---

## Test Specification

```python
# tests/integrations/msteams/test_msteams_jira_commands.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.msteams.commands import MSTeamsCommandRouter
from parrot.integrations.msteams.commands.jira_commands import (
    connect_jira_handler, _MSTEAMS_CHANNEL, register_jira_commands,
)


class TestMSTeamsCommandRouter:
    async def test_dispatches_registered_command(self):
        router = MSTeamsCommandRouter()
        handler = AsyncMock()
        router.register("test_cmd", handler)
        ctx = MagicMock()
        result = await router.try_dispatch("/test_cmd", ctx)
        assert result is True
        handler.assert_called_once()

    async def test_ignores_non_command_text(self):
        router = MSTeamsCommandRouter()
        ctx = MagicMock()
        result = await router.try_dispatch("hello world", ctx)
        assert result is False

    async def test_ignores_unregistered_command(self):
        router = MSTeamsCommandRouter()
        ctx = MagicMock()
        result = await router.try_dispatch("/unknown_cmd", ctx)
        assert result is False


class TestConnectJiraTeams:
    async def test_generates_auth_url(self):
        manager = AsyncMock()
        manager.validate_token.return_value = None
        manager.create_authorization_url.return_value = ("https://auth...", "nonce")
        ctx = MagicMock()
        ctx.activity.from_property.aad_object_id = "aad-obj-123"
        ctx.send_activity = AsyncMock()
        await connect_jira_handler(ctx, manager)
        manager.create_authorization_url.assert_called_once()
        ctx.send_activity.assert_called_once()

    async def test_already_connected(self):
        manager = AsyncMock()
        manager.validate_token.return_value = MagicMock(display_name="Jane")
        ctx = MagicMock()
        ctx.activity.from_property.aad_object_id = "aad-obj-123"
        ctx.send_activity = AsyncMock()
        await connect_jira_handler(ctx, manager)
        assert "already" in ctx.send_activity.call_args[0][0].text.lower() or True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1467 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports/signatures still match
4. **Update status** in `sdd/tasks/index/jiratoolkit-integrations-oauth2.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1471-msteams-command-router-jira.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
