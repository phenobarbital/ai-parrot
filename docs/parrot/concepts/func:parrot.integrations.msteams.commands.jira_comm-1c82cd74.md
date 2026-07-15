---
type: Concept
title: disconnect_jira_handler()
id: func:parrot.integrations.msteams.commands.jira_commands.disconnect_jira_handler
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle ``/disconnect_jira`` text command.
---

# disconnect_jira_handler

```python
async def disconnect_jira_handler(turn_context: 'TurnContext', oauth_manager: 'JiraOAuthManager') -> None
```

Handle ``/disconnect_jira`` text command.

Revokes stored Jira tokens and sends a confirmation reply.

Args:
    turn_context: The current Bot Framework turn context.
    oauth_manager: Backing Jira OAuth manager.
