---
type: Concept
title: connect_jira_handler()
id: func:parrot.integrations.slack.commands.jira_commands.connect_jira_handler
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle ``/connect_jira`` slash command.
---

# connect_jira_handler

```python
async def connect_jira_handler(payload: Dict[str, Any], oauth_manager: 'JiraOAuthManager') -> Dict[str, Any]
```

Handle ``/connect_jira`` slash command.

Checks whether the user already has a valid Jira token. If yes, returns
an "already connected" ephemeral. If no, generates an auth URL and sends
an ephemeral message with a button.

Args:
    payload: Slack slash-command POST data (team_id, user_id, channel_id, …).
    oauth_manager: Backing Jira OAuth manager.

Returns:
    An ephemeral response dict suitable for Slack's slash-command response.
