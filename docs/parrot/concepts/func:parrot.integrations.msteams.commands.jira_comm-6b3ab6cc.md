---
type: Concept
title: connect_jira_handler()
id: func:parrot.integrations.msteams.commands.jira_commands.connect_jira_handler
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handle ``/connect_jira`` text command.
---

# connect_jira_handler

```python
async def connect_jira_handler(turn_context: 'TurnContext', oauth_manager: 'JiraOAuthManager') -> None
```

Handle ``/connect_jira`` text command.

Checks whether the user already has a valid Jira token. If yes, sends
an "already connected" reply. Otherwise generates an auth URL and sends
an Adaptive Card with a button.

Args:
    turn_context: The current Bot Framework turn context.
    oauth_manager: Backing Jira OAuth manager.
