---
type: Concept
title: disconnect_jira_handler()
id: func:parrot.integrations.slack.commands.jira_commands.disconnect_jira_handler
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handle ``/disconnect_jira`` slash command.
---

# disconnect_jira_handler

```python
async def disconnect_jira_handler(payload: Dict[str, Any], oauth_manager: 'JiraOAuthManager') -> Dict[str, Any]
```

Handle ``/disconnect_jira`` slash command.

Revokes the user's stored Jira tokens and confirms disconnection.

Args:
    payload: Slack slash-command POST data.
    oauth_manager: Backing Jira OAuth manager.

Returns:
    An ephemeral response dict confirming disconnection.
