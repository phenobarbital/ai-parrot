---
type: Wiki Summary
title: parrot.integrations.slack.oauth_callback
id: mod:parrot.integrations.slack.oauth_callback
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Slack OAuth callback helpers for Jira 3LO flow (FEAT-225).
relates_to:
- concept: class:parrot.integrations.slack.oauth_callback.SlackOAuthNotifier
  rel: defines
- concept: func:parrot.integrations.slack.oauth_callback.handle_slack_jira_callback
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
---

# `parrot.integrations.slack.oauth_callback`

Slack OAuth callback helpers for Jira 3LO flow (FEAT-225).

After a Slack user authorizes their Jira account, Atlassian redirects to
``/api/auth/jira/callback``.  When ``extra_state["channel"] == "slack"``
this module handles:

1. Writing an ``auth.user_identities`` row via :class:`IdentityMappingService`.
2. Returning a plain HTML success/error page shown in the user's browser.
3. Firing a DM notification via :class:`SlackOAuthNotifier` (fire-and-forget).

The notifier must be registered on the aiohttp app as
``app["slack_jira_oauth_notifier"]`` by :class:`SlackAgentWrapper` during
``__init__`` (wired in TASK-1470).

## Classes

- **`SlackOAuthNotifier`** — Push a DM confirmation to a Slack user after a successful Jira OAuth callback.

## Functions

- `async def handle_slack_jira_callback(request: 'web.Request', token_set: Optional['JiraTokenSet'], state_payload: Dict[str, Any]) -> 'web.Response'` — Process a Jira OAuth callback originating from the Slack integration.
