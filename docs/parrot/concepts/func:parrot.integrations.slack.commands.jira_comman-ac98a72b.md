---
type: Concept
title: register_jira_commands()
id: func:parrot.integrations.slack.commands.jira_commands.register_jira_commands
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register the three Jira commands on *router*.
---

# register_jira_commands

```python
def register_jira_commands(router: 'SlackCommandRouter', oauth_manager: 'JiraOAuthManager') -> None
```

Register the three Jira commands on *router*.

The handlers are closed over the provided ``oauth_manager``, so there is
no need to thread it through as a request-time dependency.

Args:
    router: Target :class:`SlackCommandRouter` instance.
    oauth_manager: Backing Jira OAuth manager.
