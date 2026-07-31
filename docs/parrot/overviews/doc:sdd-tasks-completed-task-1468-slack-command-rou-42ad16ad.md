---
type: Wiki Overview
title: 'TASK-1468: Slack Command Router + Jira Commands'
id: doc:sdd-tasks-completed-task-1468-slack-command-router-jira-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The Slack integration currently handles only three built-in commands (`help`,
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations.slack
  rel: mentions
- concept: mod:parrot.integrations.slack.commands
  rel: mentions
- concept: mod:parrot.integrations.slack.commands.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: mentions
- concept: mod:parrot.services.identity_mapping
  rel: mentions
---

# TASK-1468: Slack Command Router + Jira Commands

**Feature**: FEAT-225 — JiraToolkit Integrations OAuth2
**Spec**: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1467
**Assigned-to**: unassigned

---

## Context

The Slack integration currently handles only three built-in commands (`help`,
`clear`, `commands`) via hardcoded string matching in `_handle_command` (HTTP)
and `_handle_slash_command` (Socket Mode). This task introduces a
`SlackCommandRouter` that decouples command dispatch from the wrapper, and
registers the three Jira commands (`/connect_jira`, `/disconnect_jira`,
`/jira_status`) on it.

Implements Spec §3 Module 2.

---

## Scope

- Create `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py` with `SlackCommandRouter` class.
- Create `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py` with:
  - `_SLACK_CHANNEL = "slack"` constant
  - `connect_jira_handler(payload, oauth_manager)` — checks existing token via `validate_token`, generates auth URL, returns ephemeral message with button
  - `disconnect_jira_handler(payload, oauth_manager)` — revokes token, returns ephemeral confirmation
  - `jira_status_handler(payload, oauth_manager)` — reports connection status
  - `register_jira_commands(router, oauth_manager)` — registers the three handlers on the router
- `SlackCommandRouter.dispatch(command, payload)` returns an ephemeral response dict (for HTTP mode) or `None` if the command is not registered.
- Slack user_id format: `f"{team_id}:{slack_user_id}"` for multi-workspace safety.
- Already-connected check: short-circuit with "Already connected" (matches Telegram).
- Write unit tests for router dispatch, command handlers, and multi-workspace keying.

**NOT in scope**: OAuth callback handler, Slack DM notifications, wrapper wiring (those are separate tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py` | CREATE | SlackCommandRouter class |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py` | CREATE | Jira command handlers + register_jira_commands |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_jira_commands.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Core auth (no change):
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet  # packages/ai-parrot/src/parrot/auth/jira_oauth.py:86, :59

# Reference pattern (Telegram jira_commands):
from parrot.integrations.telegram.jira_commands import register_jira_commands  # jira_commands.py:156
# _TELEGRAM_CHANNEL = "telegram"  — jira_commands.py:39

# Identity mapping (may be needed for post-callback):
from parrot.services.identity_mapping import IdentityMappingService  # packages/ai-parrot-server/src/parrot/services/identity_mapping.py:76
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
```

### Does NOT Exist

- ~~`parrot.integrations.slack.commands`~~ — subpackage does not exist yet (will be created)
- ~~`parrot.integrations.slack.auth`~~ — does not exist
- ~~`SlackUserSession`~~ — no session equivalent exists for Slack
- ~~`SlackCommandRouter`~~ — does not exist yet (will be created)

---

## Implementation Notes

### Pattern to Follow

Mirror `telegram/jira_commands.py` structure. The Slack-specific differences:

```python
# Slack command payload contains:
# team_id, user_id, channel_id, text, response_url

_SLACK_CHANNEL = "slack"

async def connect_jira_handler(payload: dict, oauth_manager: JiraOAuthManager) -> dict:
    team_id = payload["team_id"]
    slack_user_id = payload["user_id"]
    user_id = f"{team_id}:{slack_user_id}"

    if await oauth_manager.validate_token(_SLACK_CHANNEL, user_id) is not None:
        return {"response_type": "ephemeral", "text": "Already connected..."}

    url, _nonce = await oauth_manager.create_authorization_url(
        _SLACK_CHANNEL, user_id,
        extra_state={"channel": "slack", "team_id": team_id, "slack_user_id": slack_user_id},
    )
    return {
        "response_type": "ephemeral",
        "text": "Click the button below to connect your Jira account:",
        "attachments": [{"actions": [{"type": "button", "text": "Connect Jira", "url": url}]}],
    }
```

### Key Constraints

- Slack 3-second ack: the handler MUST return a response dict quickly. If OAuth URL generation is slow, return "Processing..." first and post the URL via `response_url` asynchronously. For now, assume `create_authorization_url` is fast (Redis nonce write only).
- Use Block Kit format for buttons when possible (more modern than attachments).
- `extra_state` MUST include `"channel": "slack"` so the callback route can dispatch correctly.

### References in Codebase

- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` — reference pattern to mirror
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:290-341` — current command handling to understand payload format

---

## Acceptance Criteria

- [ ] `SlackCommandRouter` dispatches registered commands and returns None for unknown
- [ ] `/connect_jira` generates auth URL with `channel="slack"`, `user_id=f"{team_id}:{slack_user_id}"`
- [ ] `/connect_jira` when already connected returns "Already connected" ephemeral
- [ ] `/disconnect_jira` calls `oauth_manager.revoke("slack", ...)` and confirms
- [ ] `/jira_status` reports connection details or "Not connected"
- [ ] All tests pass: `pytest tests/integrations/slack/test_slack_jira_commands.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/slack/`

---

## Test Specification

```python
# tests/integrations/slack/test_slack_jira_commands.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.slack.commands.jira_commands import (
    connect_jira_handler,
    disconnect_jira_handler,
    jira_status_handler,
    register_jira_commands,
    _SLACK_CHANNEL,
)


class TestSlackCommandRouter:
    def test_dispatch_registered_command(self):
        router = SlackCommandRouter()
        handler = AsyncMock(return_value={"text": "ok"})
        router.register("test", handler)
        # dispatch should call handler

    def test_dispatch_unknown_returns_none(self):
        router = SlackCommandRouter()
        # dispatch unknown command returns None


class TestConnectJira:
    async def test_generates_auth_url(self):
        manager = AsyncMock()
        manager.validate_token.return_value = None
        manager.create_authorization_url.return_value = ("https://auth.atlassian.com/...", "nonce")
        payload = {"team_id": "T001", "user_id": "U123", "channel_id": "C456"}
        result = await connect_jira_handler(payload, manager)
        manager.create_authorization_url.assert_called_once_with(
            "slack", "T001:U123", extra_state=pytest.approx({"channel": "slack", "team_id": "T001", "slack_user_id": "U123"}, abs=1)
        )

    async def test_already_connected_short_circuits(self):
        manager = AsyncMock()
        manager.validate_token.return_value = MagicMock(display_name="Jane")
        payload = {"team_id": "T001", "user_id": "U123"}
        result = await connect_jira_handler(payload, manager)
        assert "already" in result["text"].lower() or "Already" in result["text"]

    def test_multi_workspace_key_format(self):
        # Verify user_id is f"{team_id}:{slack_user_id}"
        assert f"T001:U123" == "T001:U123"
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
7. **Move this file** to `sdd/tasks/completed/TASK-1468-slack-command-router-jira.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Created `slack/commands/__init__.py` with `SlackCommandRouter` (register/dispatch pattern) and `slack/commands/jira_commands.py` with `connect_jira_handler`, `disconnect_jira_handler`, `jira_status_handler`, `register_jira_commands`, and `_SLACK_CHANNEL` constant. Block Kit button used for Connect Jira. Multi-workspace user_id format `{team_id}:{slack_user_id}` implemented. Unit tests created.

**Deviations from spec**: none
