---
type: Concept
title: jira_menu_handler()
id: func:parrot.integrations.msteams.commands.jira_commands.jira_menu_handler
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Show a discoverability menu with all Jira commands.
---

# jira_menu_handler

```python
async def jira_menu_handler(turn_context: 'TurnContext', oauth_manager: 'JiraOAuthManager') -> None
```

Show a discoverability menu with all Jira commands.

Triggered by typing ``jira`` or ``integrations`` (without ``/`` prefix).
Registered as plain-text handlers (not slash commands).

Args:
    turn_context: The current Bot Framework turn context.
    oauth_manager: Backing Jira OAuth manager (unused, for signature parity).
