---
type: Concept
title: jira_status_handler()
id: func:parrot.integrations.slack.commands.jira_commands.jira_status_handler
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handle ``/jira_status`` slash command.
---

# jira_status_handler

```python
async def jira_status_handler(payload: Dict[str, Any], oauth_manager: 'JiraOAuthManager') -> Dict[str, Any]
```

Handle ``/jira_status`` slash command.

Reports whether a valid Jira token is on file for the calling user.

Args:
    payload: Slack slash-command POST data.
    oauth_manager: Backing Jira OAuth manager.

Returns:
    An ephemeral response dict with connection status.
