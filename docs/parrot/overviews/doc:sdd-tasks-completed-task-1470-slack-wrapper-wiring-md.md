---
type: Wiki Overview
title: 'TASK-1470: Slack Wrapper + Socket Handler Wiring'
id: doc:sdd-tasks-completed-task-1470-slack-wrapper-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: TASK-1468 created `SlackCommandRouter` and Jira command handlers.
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations.slack.commands
  rel: mentions
- concept: mod:parrot.integrations.slack.commands.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.slack.models
  rel: mentions
- concept: mod:parrot.integrations.slack.oauth_callback
  rel: mentions
- concept: mod:parrot.integrations.slack.socket_handler
  rel: mentions
- concept: mod:parrot.integrations.slack.wrapper
  rel: mentions
---

# TASK-1470: Slack Wrapper + Socket Handler Wiring

**Feature**: FEAT-225 — JiraToolkit Integrations OAuth2
**Spec**: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1468, TASK-1469
**Assigned-to**: unassigned

---

## Context

TASK-1468 created `SlackCommandRouter` and Jira command handlers.
TASK-1469 created `SlackOAuthNotifier` and the callback handler. This
task wires them into `SlackAgentWrapper` (HTTP mode) and
`SlackSocketHandler` (Socket Mode) so slash commands are actually
dispatched, and the OAuth notifier is registered on the aiohttp app.

Implements Spec §3 Module 4.

---

## Scope

- Modify `SlackAgentWrapper.__init__` to:
  - Accept optional `oauth_manager: JiraOAuthManager` parameter.
  - Create a `SlackCommandRouter`, call `register_jira_commands(router, oauth_manager)` if provided.
  - Store the router as `self._command_router`.
  - Register `SlackOAuthNotifier` on the aiohttp app as `app["slack_jira_oauth_notifier"]` if `oauth_manager` is provided.
- Modify `SlackAgentWrapper._handle_command` to:
  - After signature verification, try `self._command_router.dispatch(command, payload)` first.
  - If it returns a response dict, return that (ephemeral).
  - Otherwise fall through to existing built-in commands (help, clear, commands) and agent processing.
- Modify `SlackSocketHandler._handle_slash_command` similarly:
  - Try `self._wrapper._command_router.dispatch(command, payload)` first.
  - If dispatched, ack and send the response. Otherwise fall through.
- Add `SlackAgentConfig` optional fields: `jira_client_id`, `jira_client_secret`, `jira_redirect_uri` for Jira OAuth configuration.
- Write tests for the wrapper integration.

**NOT in scope**: Implementing the command handlers (TASK-1468), callback logic (TASK-1469), or MS Teams (separate tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | Wire SlackCommandRouter, register notifier on app |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py` | MODIFY | Wire command router dispatch before built-in commands |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` | MODIFY | Add optional Jira OAuth config fields |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_jira.py` | CREATE | Integration tests for wiring |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.integrations.slack.wrapper import SlackAgentWrapper  # wrapper.py:68
from parrot.integrations.slack.socket_handler import SlackSocketHandler  # socket_handler.py:20
from parrot.integrations.slack.models import SlackAgentConfig  # models.py:8
from parrot.integrations.slack.commands import SlackCommandRouter  # commands/__init__.py (TASK-1468)
from parrot.integrations.slack.commands.jira_commands import register_jira_commands  # (TASK-1468)
from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier  # (TASK-1469)
from parrot.auth.jira_oauth import JiraOAuthManager  # packages/ai-parrot/src/parrot/auth/jira_oauth.py:86
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
class SlackAgentWrapper:  # line 68
    def __init__(self, agent, config: SlackAgentConfig, app: web.Application):  # line 79
        self.commands_route = f"/api/slack/{safe_id}/commands"  # line 110
        # app.router.add_post(self.commands_route, self._handle_command)  # line 114

    async def _handle_command(self, request: web.Request) -> web.Response:  # line 290
        data = await request.post()
        channel = data.get("channel_id", "")
        user = data.get("user_id", "unknown")
        text = (data.get("text") or "").strip()
        # ... built-in commands at lines 308-323
        # ... background processing at line 326

# packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py
class SlackSocketHandler:  # line 20
    def __init__(self, wrapper: SlackAgentWrapper):  # line 23
    async def _handle_slash_command(self, payload: Dict[str, Any]) -> None:  # line 266
        text = (payload.get("text") or "").strip()
        # ... built-in commands at lines 286-310

# packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py
class SlackAgentConfig:  # line 8
    name: str
    chatbot_id: str
    bot_token: Optional[str] = None
    signing_secret: Optional[str] = None
    connection_mode: str = "webhook"  # line 44
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'SlackAgentConfig':  # line 74
```

### Does NOT Exist

- ~~`SlackAgentWrapper._command_router`~~ — does not exist yet (will be added)
- ~~`SlackAgentConfig.jira_client_id`~~ — does not exist yet
- ~~`SlackAgentConfig.jira_client_secret`~~ — does not exist yet
- ~~`SlackAgentConfig.jira_redirect_uri`~~ — does not exist yet
- ~~`app["slack_jira_oauth_notifier"]`~~ — not registered yet (will be added)

---

## Implementation Notes

### Pattern to Follow

```python
# In SlackAgentWrapper.__init__, after existing route setup:
self._command_router = SlackCommandRouter()
if oauth_manager:
    register_jira_commands(self._command_router, oauth_manager)
    # Register notifier on the aiohttp app for the callback route
    notifier = SlackOAuthNotifier(bot_token=config.bot_token)
    app["slack_jira_oauth_notifier"] = notifier

# In _handle_command, BEFORE the built-in command block:
command_text = text.split()[0].lstrip("/") if text else ""
result = await self._command_router.dispatch(command_text, {
    "team_id": data.get("team_id", ""),
    "user_id": user,
    "channel_id": channel,
    "text": text,
    "response_url": data.get("response_url", ""),
})
if result is not None:
    return web.json_response(result)
# ... fall through to existing logic
```

### Key Constraints

- The `_handle_command` method currently returns a response synchronously for built-in commands, or dispatches to `_safe_answer` in background. Jira commands should also return ephemeral responses synchronously (they're fast — just a Redis check + URL generation).
- The `SlackSocketHandler` does NOT return HTTP responses — it uses `client.send_socket_mode_response()` then posts via the Slack Web API. The command router response dict needs to be sent as an ephemeral message.
- Both HTTP and Socket Mode must delegate to the same `SlackCommandRouter` instance.

### References in Codebase

- `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:290-341` — current _handle_command
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py:266-310` — current _handle_slash_command

---

## Acceptance Criteria

- [ ] `/connect_jira` from Slack HTTP mode returns ephemeral message with auth button
- [ ] `/connect_jira` from Socket Mode sends ephemeral message via Slack API
- [ ] `/disconnect_jira` and `/jira_status` work from both modes
- [ ] Built-in commands (help, clear, commands) still work unchanged
- [ ] Unknown commands still pass through to agent processing
- [ ] `SlackOAuthNotifier` registered on app as `app["slack_jira_oauth_notifier"]`
- [ ] `SlackAgentConfig` accepts optional Jira OAuth config fields
- [ ] All tests pass: `pytest tests/integrations/slack/ -v`

---

## Test Specification

```python
# tests/integrations/slack/test_slack_wrapper_jira.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSlackWrapperJiraWiring:
    def test_command_router_created_on_init(self):
        """Wrapper creates a SlackCommandRouter during __init__."""
        ...

    def test_jira_commands_registered_when_oauth_manager_provided(self):
        """When oauth_manager is passed, jira commands are registered on router."""
        ...

    async def test_handle_command_dispatches_connect_jira(self):
        """_handle_command delegates /connect_jira to the command router."""
        ...

    async def test_handle_command_fallthrough_for_unknown(self):
        """Unknown commands still fall through to existing processing."""
        ...

    def test_slack_oauth_notifier_registered_on_app(self):
        """SlackOAuthNotifier is stored at app['slack_jira_oauth_notifier']."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1468 and TASK-1469 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports/signatures still match
4. **Update status** in `sdd/tasks/index/jiratoolkit-integrations-oauth2.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1470-slack-wrapper-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Modified `wrapper.py` to accept optional `oauth_manager`, create `SlackCommandRouter`, register Jira commands, and register `SlackOAuthNotifier` on app. Modified `socket_handler.py` to delegate to command router before built-in commands. Added `jira_client_id`, `jira_client_secret`, `jira_redirect_uri` fields to `SlackAgentConfig`. Tests created.

**Deviations from spec**: none
