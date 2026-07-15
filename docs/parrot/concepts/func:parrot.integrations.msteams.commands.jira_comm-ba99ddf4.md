---
type: Concept
title: register_jira_commands()
id: func:parrot.integrations.msteams.commands.jira_commands.register_jira_commands
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register Jira commands on *router*.
---

# register_jira_commands

```python
def register_jira_commands(router: 'MSTeamsCommandRouter', oauth_manager: 'JiraOAuthManager') -> None
```

Register Jira commands on *router*.

Registers the three slash commands plus the ``jira`` and ``integrations``
plain-text menu triggers.

Args:
    router: Target :class:`MSTeamsCommandRouter` instance.
    oauth_manager: Backing Jira OAuth manager.
