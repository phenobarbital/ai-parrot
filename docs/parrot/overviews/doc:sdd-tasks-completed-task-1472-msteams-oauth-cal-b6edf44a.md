---
type: Wiki Overview
title: 'TASK-1472: MS Teams OAuth Callback + Proactive Notification'
id: doc:sdd-tasks-completed-task-1472-msteams-oauth-callback-notification-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After a Teams user consents in the Atlassian OAuth flow, the callback
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations.msteams.oauth_callback
  rel: mentions
- concept: mod:parrot.services.identity_mapping
  rel: mentions
---

# TASK-1472: MS Teams OAuth Callback + Proactive Notification

**Feature**: FEAT-225 — JiraToolkit Integrations OAuth2
**Spec**: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1471
**Assigned-to**: unassigned

---

## Context

After a Teams user consents in the Atlassian OAuth flow, the callback
route needs a `channel == "msteams"` branch. Unlike Slack (DM via Web API),
Teams requires proactive messaging via the Bot Framework adapter using a
stored `conversation_reference`. This task creates the `MSTeamsOAuthNotifier`
and adds the callback branch.

Implements Spec §3 Module 6.

---

## Scope

- Create `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py` with:
  - `MSTeamsOAuthNotifier` class:
    - `__init__(self, adapter, app_id)` — takes the Bot Framework adapter and app ID
    - `async notify_connected(self, conversation_ref, display_name, site_url)` — sends proactive message using `adapter.continue_conversation`
    - `async notify_failure(self, conversation_ref, reason)` — sends error proactive message
  - `async handle_msteams_jira_callback(request, token_set, state_payload)` helper that:
    - Writes `auth.user_identities` row with `auth_provider="msteams"`, `auth_data={"aad_object_id": ..., "tenant_id": ...}`
    - Fires `MSTeamsOAuthNotifier.notify_connected` as fire-and-forget
    - Returns an HTML success page (instructs user to return to Teams)
- Extend `jira_oauth_callback` in `parrot/auth/routes.py` to add `channel == "msteams"` branch.
- Write unit tests.

**NOT in scope**: Slack callback (TASK-1469), command router (TASK-1471), wrapper wiring (TASK-1473).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py` | CREATE | MSTeamsOAuthNotifier + callback handler |
| `packages/ai-parrot/src/parrot/auth/routes.py` | MODIFY | Add `channel == "msteams"` branch |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_oauth_callback.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.auth.jira_oauth import JiraTokenSet  # packages/ai-parrot/src/parrot/auth/jira_oauth.py:59
from parrot.services.identity_mapping import IdentityMappingService  # packages/ai-parrot-server/src/parrot/services/identity_mapping.py:76

# Bot Framework (existing deps):
from botbuilder.core import BotFrameworkAdapter, TurnContext
from botbuilder.schema import ConversationReference, Activity
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/routes.py
async def jira_oauth_callback(request: web.Request) -> web.Response:  # line 186
    channel = state_payload.get("channel", "telegram")  # line 220
    if channel == "web":  # line 221
        return await _handle_web_callback(...)
    # After TASK-1469: if channel == "slack": return await _handle_slack_callback(...)
    # NEW: if channel == "msteams": return await _handle_msteams_callback(...)

# Bot Framework proactive messaging pattern:
# adapter.continue_conversation(conversation_ref, callback, app_id)
# where callback receives a TurnContext and can send_activity
```

### Does NOT Exist

- ~~`parrot.integrations.msteams.oauth_callback`~~ — does not exist yet
- ~~`MSTeamsOAuthNotifier`~~ — does not exist yet
- ~~`app["msteams_jira_oauth_notifier"]`~~ — not registered on app yet (wrapper wiring task)

---

## Implementation Notes

### Pattern to Follow

```python
class MSTeamsOAuthNotifier:
    def __init__(self, adapter: BotFrameworkAdapter, app_id: str):
        self._adapter = adapter
        self._app_id = app_id

    async def notify_connected(self, conversation_ref_dict: dict, display_name: str, site_url: str):
        conv_ref = ConversationReference().from_dict(conversation_ref_dict)

        async def _callback(turn_context: TurnContext):
            await turn_context.send_activity(
                f"✅ Jira connected as {display_name}\nSite: {site_url}"
            )

        await self._adapter.continue_conversation(conv_ref, _callback, self._app_id)
```

### Key Constraints

- The `conversation_reference` is stored as a JSON dict in `extra_state` by TASK-1471. It must be deserialized back to a `ConversationReference` object.
- `adapter.continue_conversation` requires the bot's `app_id` (Microsoft App ID from `MSTeamsAgentConfig.client_id`).
- The HTML success page for Teams should say "You can close this tab and return to Microsoft Teams" since the OAuth flow opens in a browser outside of Teams.
- If proactive messaging fails (e.g., conversation deleted), log and continue.

### References in Codebase

- `packages/ai-parrot/src/parrot/auth/routes.py:186-262` — existing callback handler
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:56` — MSTeamsAgentWrapper (adapter access)
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/proactive.py` — existing proactive messaging patterns

---

## Acceptance Criteria

- [ ] `MSTeamsOAuthNotifier.notify_connected` sends a proactive message to the Teams conversation
- [ ] `MSTeamsOAuthNotifier.notify_failure` sends an error proactive message
- [ ] `jira_oauth_callback` with `channel == "msteams"` writes identity row with `auth_provider="msteams"`
- [ ] `jira_oauth_callback` with `channel == "msteams"` returns HTML success page
- [ ] Existing Telegram and Slack callback paths still work unchanged
- [ ] All tests pass: `pytest tests/integrations/msteams/test_msteams_oauth_callback.py -v`

---

## Test Specification

```python
# tests/integrations/msteams/test_msteams_oauth_callback.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.msteams.oauth_callback import MSTeamsOAuthNotifier


class TestMSTeamsOAuthNotifier:
    async def test_notify_connected_sends_proactive(self):
        adapter = AsyncMock()
        notifier = MSTeamsOAuthNotifier(adapter=adapter, app_id="test-app-id")
        conv_ref = {"conversation": {"id": "conv-123"}, "bot": {"id": "bot-1"}}
        await notifier.notify_connected(conv_ref, "Jane Doe", "myco.atlassian.net")
        adapter.continue_conversation.assert_called_once()

    async def test_notify_failure_sends_proactive(self):
        adapter = AsyncMock()
        notifier = MSTeamsOAuthNotifier(adapter=adapter, app_id="test-app-id")
        conv_ref = {"conversation": {"id": "conv-123"}}
        await notifier.notify_failure(conv_ref, "expired nonce")
        adapter.continue_conversation.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1471 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports/signatures still match
4. **Update status** in `sdd/tasks/index/jiratoolkit-integrations-oauth2.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1472-msteams-oauth-callback-notification.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
