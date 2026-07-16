---
type: Wiki Overview
title: 'TASK-1473: MS Teams Wrapper Wiring'
id: doc:sdd-tasks-completed-task-1473-msteams-wrapper-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: TASK-1471 created `MSTeamsCommandRouter` and Jira command handlers.
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations.msteams.commands
  rel: mentions
- concept: mod:parrot.integrations.msteams.commands.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.msteams.models
  rel: mentions
- concept: mod:parrot.integrations.msteams.oauth_callback
  rel: mentions
- concept: mod:parrot.integrations.msteams.wrapper
  rel: mentions
---

# TASK-1473: MS Teams Wrapper Wiring

**Feature**: FEAT-225 — JiraToolkit Integrations OAuth2
**Spec**: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1471, TASK-1472
**Assigned-to**: unassigned

---

## Context

TASK-1471 created `MSTeamsCommandRouter` and Jira command handlers.
TASK-1472 created `MSTeamsOAuthNotifier` and the callback handler. This
task wires them into `MSTeamsAgentWrapper` so commands are intercepted in
`on_message_activity` before reaching the agent, and the notifier is
registered on the aiohttp app.

Implements Spec §3 Module 7.

---

## Scope

- Modify `MSTeamsAgentWrapper.__init__` to:
  - Accept optional `oauth_manager: JiraOAuthManager` parameter.
  - Create a `MSTeamsCommandRouter`, call `register_jira_commands(router, oauth_manager)` if provided.
  - Store the router as `self._command_router`.
  - Register `MSTeamsOAuthNotifier` on the aiohttp app as `app["msteams_jira_oauth_notifier"]`.
- Modify `MSTeamsAgentWrapper.on_message_activity` to:
  - After authorization check and before card submission / voice / dialog handling, intercept text commands:
    ```python
    text = turn_context.activity.text
    if text and self._command_router:
        if await self._command_router.try_dispatch(text, turn_context):
            return  # command handled, skip agent processing
    ```
- Add `MSTeamsAgentConfig` optional fields: `jira_client_id`, `jira_client_secret`, `jira_redirect_uri`.
- Write tests for the wrapper integration.

**NOT in scope**: Command handlers (TASK-1471), callback logic (TASK-1472), Slack wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | Wire MSTeamsCommandRouter, register notifier |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | Add optional Jira OAuth config fields |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper  # wrapper.py:56
from parrot.integrations.msteams.models import MSTeamsAgentConfig  # models.py:13
from parrot.integrations.msteams.commands import MSTeamsCommandRouter  # (TASK-1471)
from parrot.integrations.msteams.commands.jira_commands import register_jira_commands  # (TASK-1471)
from parrot.integrations.msteams.oauth_callback import MSTeamsOAuthNotifier  # (TASK-1472)
from parrot.auth.jira_oauth import JiraOAuthManager  # packages/ai-parrot/src/parrot/auth/jira_oauth.py:86
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):  # line 56
    def __init__(self, agent, config: MSTeamsAgentConfig, app: web.Application,
                 forms_directory=None, voice_config=None):  # line ~68
        self.app = app  # aiohttp Application
        self.config = config
        self.route = f"/api/msteams/{safe_id}/messages"
        self.app.router.add_post(self.route, self.handle_request)  # line 139

    async def on_message_activity(self, turn_context: TurnContext):  # line 367
        # Authorization check: lines 370-379
        # Card submission check: lines 398-404
        # Voice attachment: lines 406-409
        # Dialog continuation: lines 412-415
        # Text extraction: line 418
        # NEW command intercept should go HERE (after auth, before card/voice/dialog)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
class MSTeamsAgentConfig:  # line 13
    name: str
    chatbot_id: str
    client_id: Optional[str] = None  # line 30
    commands: Dict[str, str] = field(default_factory=dict)  # line 36
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'MSTeamsAgentConfig':  # line 93
```

### Does NOT Exist

- ~~`MSTeamsAgentWrapper._command_router`~~ — does not exist yet (will be added)
- ~~`MSTeamsAgentConfig.jira_client_id`~~ — does not exist yet
- ~~`app["msteams_jira_oauth_notifier"]`~~ — not registered yet

---

## Implementation Notes

### Pattern to Follow

```python
# In MSTeamsAgentWrapper.__init__:
self._command_router = None
if oauth_manager:
    self._command_router = MSTeamsCommandRouter()
    register_jira_commands(self._command_router, oauth_manager)
    notifier = MSTeamsOAuthNotifier(adapter=self.adapter, app_id=config.client_id)
    app["msteams_jira_oauth_notifier"] = notifier

# In on_message_activity, after authorization check (line 379):
text = turn_context.activity.text
if text and self._command_router:
    # Strip bot mention first (Teams prepends @BotName in group chats)
    clean_text = self._remove_mentions(turn_context.activity, text).strip()
    if await self._command_router.try_dispatch(clean_text, turn_context):
        return
# ... continue with existing card/voice/dialog/agent flow
```

### Key Constraints

- Command interception MUST happen after `_is_authorized` check but BEFORE card submission handling, voice, and dialog continuation. This ensures unauthorized users can't use Jira commands.
- In group chats, Teams prepends `@BotName` to the message. The existing `_remove_mentions` method (line 565) must be called before command detection.
- The `adapter` reference is needed for `MSTeamsOAuthNotifier`. It's created in `__init__` as `self.adapter = BotFrameworkAdapter(...)` (around line 90).

### References in Codebase

- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:367-440` — on_message_activity
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:565` — _remove_mentions
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/proactive.py` — proactive messaging reference

---

## Acceptance Criteria

- [ ] `/connect_jira` text in MS Teams is intercepted and handled by the command router
- [ ] `/disconnect_jira` and `/jira_status` text commands work in Teams
- [ ] Normal messages (non-commands) still pass through to the agent
- [ ] Command interception happens AFTER authorization check
- [ ] Bot mentions are stripped before command detection in group chats
- [ ] `MSTeamsOAuthNotifier` registered on app as `app["msteams_jira_oauth_notifier"]`
- [ ] `MSTeamsAgentConfig` accepts optional Jira OAuth config fields
- [ ] All tests pass: `pytest tests/integrations/msteams/ -v`

---

## Test Specification

```python
# tests/integrations/msteams/test_msteams_wrapper_jira.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestMSTeamsWrapperJiraWiring:
    async def test_command_router_intercepts_connect_jira(self):
        """on_message_activity dispatches /connect_jira before agent."""
        ...

    async def test_normal_message_passes_through(self):
        """Non-command text still reaches the agent."""
        ...

    async def test_command_after_mention_stripping(self):
        """@BotName /connect_jira is detected after mention removal."""
        ...

    async def test_unauthorized_user_cannot_use_commands(self):
        """Authorization check blocks commands for unauthorized users."""
        ...

    def test_notifier_registered_on_app(self):
        """MSTeamsOAuthNotifier stored at app['msteams_jira_oauth_notifier']."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1471 and TASK-1472 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports/signatures still match
4. **Update status** in `sdd/tasks/index/jiratoolkit-integrations-oauth2.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1473-msteams-wrapper-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
