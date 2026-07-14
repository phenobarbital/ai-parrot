---
type: Wiki Entity
title: SlackOAuthNotifier
id: class:parrot.integrations.slack.oauth_callback.SlackOAuthNotifier
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Push a DM confirmation to a Slack user after a successful Jira OAuth callback.
---

# SlackOAuthNotifier

Defined in [`parrot.integrations.slack.oauth_callback`](../summaries/mod:parrot.integrations.slack.oauth_callback.md).

```python
class SlackOAuthNotifier
```

Push a DM confirmation to a Slack user after a successful Jira OAuth callback.

Uses the Slack Web API ``chat.postMessage`` method with the user's Slack ID
as the ``channel`` parameter, which opens a DM thread.

Args:
    bot_token: Slack bot token (``xoxb-…``) used to authenticate API calls.

## Methods

- `async def notify_connected(self, team_id: str, slack_user_id: str, display_name: str, site_url: str) -> None` — Send a DM to *slack_user_id* confirming Jira connection.
- `async def notify_failure(self, team_id: str, slack_user_id: str, reason: str) -> None` — Send a DM to *slack_user_id* reporting a Jira OAuth failure.
