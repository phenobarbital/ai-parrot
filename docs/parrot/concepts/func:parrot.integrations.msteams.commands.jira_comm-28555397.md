---
type: Concept
title: jira_status_handler()
id: func:parrot.integrations.msteams.commands.jira_commands.jira_status_handler
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle ``/jira_status`` text command.
---

# jira_status_handler

```python
async def jira_status_handler(turn_context: 'TurnContext', oauth_manager: 'JiraOAuthManager') -> None
```

Handle ``/jira_status`` text command.

Reports whether a valid Jira token is on file.

Args:
    turn_context: The current Bot Framework turn context.
    oauth_manager: Backing Jira OAuth manager.
