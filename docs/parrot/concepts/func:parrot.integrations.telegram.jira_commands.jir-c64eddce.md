---
type: Concept
title: jira_status_handler()
id: func:parrot.integrations.telegram.jira_commands.jira_status_handler
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle ``/jira_status`` — report the user's Jira connection state.
---

# jira_status_handler

```python
async def jira_status_handler(message: Message, oauth_manager: 'JiraOAuthManager') -> None
```

Handle ``/jira_status`` — report the user's Jira connection state.

Uses :meth:`validate_token` rather than :meth:`get_valid_token` so a
token that Atlassian no longer accepts (admin revocation, expired
refresh chain that we couldn't recover, scope change, …) is revoked
locally and the user is told to reconnect — instead of being told
"connected" while every Jira tool returns 401.
