---
type: Wiki Summary
title: parrot.integrations.msteams.oauth_callback
id: mod:parrot.integrations.msteams.oauth_callback
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MS Teams OAuth callback helpers for Jira 3LO flow (FEAT-225).
relates_to:
- concept: class:parrot.integrations.msteams.oauth_callback.MSTeamsOAuthNotifier
  rel: defines
- concept: func:parrot.integrations.msteams.oauth_callback.handle_msteams_jira_callback
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
---

# `parrot.integrations.msteams.oauth_callback`

MS Teams OAuth callback helpers for Jira 3LO flow (FEAT-225).

After a Teams user authorizes their Jira account, Atlassian redirects to
``/api/auth/jira/callback``.  When ``extra_state["channel"] == "msteams"``
this module handles:

1. Writing an ``auth.user_identities`` row via :class:`IdentityMappingService`.
2. Returning a plain HTML success/error page shown in the user's browser.
3. Sending a proactive message to the Teams conversation using the Bot
   Framework adapter and the stored ``conversation_reference``.

Unlike Slack (DM via Web API), Teams uses the Bot Framework proactive
messaging pattern: ``adapter.continue_conversation(ref, callback, app_id)``.
The ``conversation_reference`` was serialized to JSON and stored in
``extra_state`` during ``/connect_jira`` command handling.

The notifier must be registered on the aiohttp app as
``app["msteams_jira_oauth_notifier"]`` by :class:`MSTeamsAgentWrapper` during
``__init__`` (wired in TASK-1473).

## Classes

- **`MSTeamsOAuthNotifier`** — Send a proactive message to a Teams user after a successful Jira OAuth callback.

## Functions

- `async def handle_msteams_jira_callback(request: 'web.Request', token_set: Optional['JiraTokenSet'], state_payload: Dict[str, Any]) -> 'web.Response'` — Process a Jira OAuth callback originating from the MS Teams integration.
