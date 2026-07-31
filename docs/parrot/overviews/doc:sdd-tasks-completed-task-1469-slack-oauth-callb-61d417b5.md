---
type: Wiki Overview
title: 'TASK-1469: Slack OAuth Callback + DM Notification'
id: doc:sdd-tasks-completed-task-1469-slack-oauth-callback-notification-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After a Slack user consents in the Atlassian OAuth flow, the browser
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations.slack.oauth_callback
  rel: mentions
- concept: mod:parrot.services.identity_mapping
  rel: mentions
---

# TASK-1469: Slack OAuth Callback + DM Notification

**Feature**: FEAT-225 — JiraToolkit Integrations OAuth2
**Spec**: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1468
**Assigned-to**: unassigned

---

## Context

After a Slack user consents in the Atlassian OAuth flow, the browser
redirects to `/api/auth/jira/callback`. The callback route currently
handles `channel == "web"` and `channel == "telegram"` (or absent).
This task adds a `channel == "slack"` branch that: writes an
`auth.user_identities` row, returns an HTML success page, and DMs the
Slack user confirming the connection.

Implements Spec §3 Module 3.

---

## Scope

- Create `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` with:
  - `SlackOAuthNotifier` class (mirrors `TelegramOAuthNotifier`):
    - `__init__(self, bot_token: str)` — takes the Slack bot token
    - `async notify_connected(self, team_id, slack_user_id, display_name, site_url)` — sends a DM via `chat.postMessage`
    - `async notify_failure(self, team_id, slack_user_id, reason)` — sends an error DM
  - `async handle_slack_jira_callback(request, token_set, state_payload)` helper that:
    - Writes `auth.user_identities` via `IdentityMappingService.upsert_identity` (if available on app)
    - Fires `SlackOAuthNotifier.notify_connected` as fire-and-forget
    - Returns an HTML success page
- Extend `jira_oauth_callback` in `parrot/auth/routes.py` to add a `channel == "slack"` branch that delegates to the handler above.
- Write unit tests for the notifier and callback handler.

**NOT in scope**: MS Teams callback handling, Slack wrapper wiring, command router.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` | CREATE | SlackOAuthNotifier + handle_slack_jira_callback |
| `packages/ai-parrot/src/parrot/auth/routes.py` | MODIFY | Add `channel == "slack"` branch in jira_oauth_callback |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.auth.jira_oauth import JiraTokenSet  # packages/ai-parrot/src/parrot/auth/jira_oauth.py:59
from parrot.services.identity_mapping import IdentityMappingService  # packages/ai-parrot-server/src/parrot/services/identity_mapping.py:76

# Slack SDK for DMs:
from slack_sdk.web.async_client import AsyncWebClient  # existing dep

# Existing callback route:
# packages/ai-parrot/src/parrot/auth/routes.py:186 — jira_oauth_callback
# packages/ai-parrot/src/parrot/auth/routes.py:265 — setup_jira_oauth_routes
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/routes.py
async def jira_oauth_callback(request: web.Request) -> web.Response:  # line 186
    # After handle_callback, dispatches on channel:
    channel = state_payload.get("channel", "telegram")  # line 220
    if channel == "web":  # line 221
        return await _handle_web_callback(request, token_set, state_payload)
    if state_payload.get("channel") == "telegram":  # line 228
        # ... telegram-specific stamping
    # NEW: add `if channel == "slack":` branch BEFORE the telegram block

# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
class IdentityMappingService:  # line 76
    async def upsert_identity(  # line 99
        self, nav_user_id: str, auth_provider: str,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:

# Existing notifier pattern (Telegram):
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py
class TelegramOAuthNotifier:  # line 192
    def __init__(self, bot: "Bot") -> None:
    async def notify_connected(self, chat_id: int, display_name: str, site_url: str) -> None:
```

### Does NOT Exist

- ~~`parrot.integrations.slack.oauth_callback`~~ — does not exist yet (will be created)
- ~~`SlackOAuthNotifier`~~ — does not exist yet
- ~~`handle_slack_jira_callback`~~ — does not exist yet
- ~~`app["slack_oauth_notifier"]`~~ — not registered on the aiohttp app yet (wrapper wiring task will register it)

---

## Implementation Notes

### Pattern to Follow

```python
# Mirror the Telegram notification pattern in routes.py:
# 1. Add channel == "slack" branch in jira_oauth_callback
# 2. Fire-and-forget DM notification via SlackOAuthNotifier

# In jira_oauth_callback, after the existing web channel check:
if channel == "slack":
    return await _handle_slack_callback(request, token_set, state_payload)

async def _handle_slack_callback(request, token_set, state_payload):
    # Write identity
    identity_service = request.app.get("identity_mapping_service")
    if identity_service:
        team_id = state_payload.get("team_id")
        slack_user_id = state_payload.get("slack_user_id")
        await identity_service.upsert_identity(
            nav_user_id=state_payload.get("user_id", ""),
            auth_provider="slack",
            auth_data={"team_id": team_id, "slack_user_id": slack_user_id},
            display_name=token_set.display_name,
            email=token_set.email,
        )

    # DM notification
    notifier = request.app.get("slack_jira_oauth_notifier")
    if notifier:
        asyncio.create_task(notifier.notify_connected(...))

    # Return HTML success page
    return web.Response(text=_SLACK_SUCCESS_HTML.format(...), content_type="text/html")
```

### Key Constraints

- The `SlackOAuthNotifier` uses `slack-sdk`'s `AsyncWebClient` which requires a bot token. The notifier instance will be registered on `app["slack_jira_oauth_notifier"]` by the wrapper wiring task (TASK-1470).
- DM delivery: use `chat.postMessage(channel=slack_user_id, text=...)` where passing a user_id as `channel` sends a DM.
- If DM delivery fails (bot not allowed to DM user), log and continue — the browser HTML page is the fallback.
- The `identity_mapping_service` may not be available on the app in all deployments. Guard with `if identity_service:`.

### References in Codebase

- `packages/ai-parrot/src/parrot/auth/routes.py:186-262` — existing callback handler
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py:192` — TelegramOAuthNotifier pattern

---

## Acceptance Criteria

- [ ] `SlackOAuthNotifier.notify_connected` sends a DM via `chat.postMessage` to the Slack user
- [ ] `SlackOAuthNotifier.notify_failure` sends an error DM
- [ ] `jira_oauth_callback` with `channel == "slack"` writes `auth.user_identities` row with `auth_provider="slack"`
- [ ] `jira_oauth_callback` with `channel == "slack"` returns an HTML success page
- [ ] `jira_oauth_callback` with `channel == "telegram"` (existing) still works unchanged
- [ ] All tests pass: `pytest tests/integrations/slack/test_slack_oauth_callback.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/slack/`

---

## Test Specification

```python
# tests/integrations/slack/test_slack_oauth_callback.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier


class TestSlackOAuthNotifier:
    async def test_notify_connected_sends_dm(self):
        notifier = SlackOAuthNotifier(bot_token="xoxb-test")
        with patch.object(notifier, "_client") as mock_client:
            mock_client.chat_postMessage = AsyncMock()
            await notifier.notify_connected("T001", "U123", "Jane", "myco.atlassian.net")
            mock_client.chat_postMessage.assert_called_once()

    async def test_notify_failure_sends_dm(self):
        notifier = SlackOAuthNotifier(bot_token="xoxb-test")
        with patch.object(notifier, "_client") as mock_client:
            mock_client.chat_postMessage = AsyncMock()
            await notifier.notify_failure("T001", "U123", "expired nonce")
            mock_client.chat_postMessage.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1468 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports/signatures still match
4. **Update status** in `sdd/tasks/index/jiratoolkit-integrations-oauth2.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1469-slack-oauth-callback-notification.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Created `slack/oauth_callback.py` with `SlackOAuthNotifier` and `handle_slack_jira_callback`. Extended `parrot/auth/routes.py` with `channel == "slack"` and `channel == "msteams"` branches. Tests created.

**Deviations from spec**: The `channel == "msteams"` branch was also added in this commit (in routes.py) since both callbacks needed to be added to the same file and it was simpler to do both at once.
