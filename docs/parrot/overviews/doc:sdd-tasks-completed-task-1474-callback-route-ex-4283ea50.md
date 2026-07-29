---
type: Wiki Overview
title: 'TASK-1474: Config + Callback Route Extension (Integration Test)'
id: doc:sdd-tasks-completed-task-1474-callback-route-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the final integration task. TASK-1469 and TASK-1472 each added their
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.auth.routes
  rel: mentions
- concept: mod:parrot.integrations.msteams.oauth_callback
  rel: mentions
- concept: mod:parrot.integrations.msteams.wrapper
  rel: mentions
- concept: mod:parrot.integrations.slack.oauth_callback
  rel: mentions
- concept: mod:parrot.integrations.slack.wrapper
  rel: mentions
---

# TASK-1474: Config + Callback Route Extension (Integration Test)

**Feature**: FEAT-225 — JiraToolkit Integrations OAuth2
**Spec**: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1470, TASK-1473
**Assigned-to**: unassigned

---

## Context

This is the final integration task. TASK-1469 and TASK-1472 each added their
callback branches to `routes.py`. This task verifies the full callback route
works correctly for all three channels (telegram, slack, msteams), ensures
the manager setup flow wires the Slack/Teams notifiers into the parrot
server manager, and writes end-to-end integration tests.

Implements Spec §3 Module 8.

---

## Scope

- Verify/fix `jira_oauth_callback` in `parrot/auth/routes.py` dispatches correctly for all channels:
  - `channel == "web"` → existing `_handle_web_callback`
  - `channel == "slack"` → `_handle_slack_callback` (from TASK-1469)
  - `channel == "msteams"` → `_handle_msteams_callback` (from TASK-1472)
  - `channel == "telegram"` or absent → existing Telegram flow
- Modify the parrot server manager (`packages/ai-parrot-server/src/parrot/manager/manager.py`) to:
  - When initializing Slack agents with Jira OAuth config, create `JiraOAuthManager` and pass to `SlackAgentWrapper`.
  - When initializing MS Teams agents with Jira OAuth config, create `JiraOAuthManager` and pass to `MSTeamsAgentWrapper`.
  - Register notifiers on the aiohttp app.
- Write integration tests that exercise the full flow: command → auth URL → mock callback → token stored → notification sent.
- Verify cross-integration identity: a user connecting from both Telegram and Slack gets identity rows with the same shape.

**NOT in scope**: Implementing command handlers or notifiers (done in prior tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/routes.py` | VERIFY/FIX | Ensure all channel branches work together |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Wire JiraOAuthManager into Slack/Teams agent init |
| `packages/ai-parrot-integrations/tests/integrations/test_jira_oauth_integration.py` | CREATE | End-to-end integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.auth.jira_oauth import JiraOAuthManager  # packages/ai-parrot/src/parrot/auth/jira_oauth.py:86
from parrot.auth.routes import jira_oauth_callback, setup_jira_oauth_routes  # routes.py:186, :265

from parrot.integrations.slack.wrapper import SlackAgentWrapper  # wrapper.py:68
from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier  # (TASK-1469)
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper  # wrapper.py:56
from parrot.integrations.msteams.oauth_callback import MSTeamsOAuthNotifier  # (TASK-1472)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/routes.py
async def jira_oauth_callback(request: web.Request) -> web.Response:  # line 186
    # After TASK-1469 + TASK-1472, channel dispatch should be:
    channel = state_payload.get("channel", "telegram")  # line 220
    if channel == "web": ...       # line 221 (existing)
    if channel == "slack": ...     # (TASK-1469)
    if channel == "msteams": ...   # (TASK-1472)
    if channel == "telegram": ...  # line 228 (existing)

def setup_jira_oauth_routes(app: web.Application) -> None:  # line 265

# packages/ai-parrot-server/src/parrot/manager/manager.py
# Route registration block near line 1000-1006
# Slack agent initialization section
# MS Teams agent initialization section
```

### Does NOT Exist

- ~~A unified JiraOAuthManager initialization for Slack/Teams~~ — currently only Telegram wires it up

---

## Implementation Notes

### Pattern to Follow

```python
# In manager.py, when initializing a Slack agent:
jira_oauth_manager = None
if slack_config.jira_client_id:
    jira_oauth_manager = JiraOAuthManager(
        client_id=slack_config.jira_client_id,
        client_secret=slack_config.jira_client_secret,
        redirect_uri=slack_config.jira_redirect_uri,
        app=app,
    )
wrapper = SlackAgentWrapper(agent, config=slack_config, app=app, oauth_manager=jira_oauth_manager)
```

### Key Constraints

- The `JiraOAuthManager` may already be instantiated for Telegram. If both Telegram and Slack agents are configured in the same server, they should share the same manager instance (same Redis, same callback route). The manager is stored on `app["jira_oauth_manager"]` — reuse it.
- `setup_jira_oauth_routes` should only be called once per app, even if multiple integrations use it.
- The integration tests should mock Redis but exercise the actual `jira_oauth_callback` aiohttp handler.

### References in Codebase

- `packages/ai-parrot-server/src/parrot/manager/manager.py` — server initialization
- `packages/ai-parrot/src/parrot/auth/routes.py:186-262` — callback route
- `packages/ai-parrot/src/parrot/auth/jira_oauth.py:134` — JiraOAuthManager.setup()

---

## Acceptance Criteria

- [ ] `jira_oauth_callback` correctly dispatches for `channel == "slack"`, `"msteams"`, `"telegram"`, and `"web"`
- [ ] Slack agents with Jira config get a `JiraOAuthManager` wired in
- [ ] MS Teams agents with Jira config get a `JiraOAuthManager` wired in
- [ ] Shared `JiraOAuthManager` instance when multiple integrations use the same Atlassian app
- [ ] End-to-end test: Slack command → auth URL → mock callback → token in Redis → DM sent
- [ ] End-to-end test: Teams command → auth URL → mock callback → token in Redis → proactive msg
- [ ] Telegram flow unchanged (regression test)
- [ ] All tests pass: `pytest tests/integrations/ -v`

---

## Test Specification

```python
# tests/integrations/test_jira_oauth_integration.py
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from unittest.mock import AsyncMock, MagicMock, patch


class TestJiraOAuthCallbackRouting:
    async def test_slack_channel_dispatches_to_slack_handler(self):
        """Callback with channel=slack writes identity and returns HTML."""
        ...

    async def test_msteams_channel_dispatches_to_msteams_handler(self):
        """Callback with channel=msteams writes identity and sends proactive msg."""
        ...

    async def test_telegram_channel_unchanged(self):
        """Callback with channel=telegram still fires TelegramOAuthNotifier."""
        ...

    async def test_missing_channel_defaults_to_telegram(self):
        """Backward compat: absent channel defaults to telegram behavior."""
        ...

    async def test_web_channel_unchanged(self):
        """Callback with channel=web still renders postMessage page."""
        ...


class TestCrossIntegrationIdentity:
    async def test_same_nav_user_different_integrations(self):
        """User connecting via Telegram and Slack gets separate identity rows
        but could share the same nav_user_id."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1470 and TASK-1473 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports/signatures still match
4. **Update status** in `sdd/tasks/index/jiratoolkit-integrations-oauth2.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1474-callback-route-extension.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
