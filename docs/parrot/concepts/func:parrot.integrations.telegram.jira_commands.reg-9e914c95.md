---
type: Concept
title: register_jira_commands()
id: func:parrot.integrations.telegram.jira_commands.register_jira_commands
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register the three Jira commands on *router*.
---

# register_jira_commands

```python
def register_jira_commands(router: Router, oauth_manager: 'JiraOAuthManager', session_clearer: Optional[SessionClearer]=None) -> None
```

Register the three Jira commands on *router*.

The handlers are closed over the provided ``oauth_manager``, so there's
no need to wire aiogram middleware for dependency injection.

Args:
    router: Target aiogram ``Router``.
    oauth_manager: Backing Jira OAuth manager.
    session_clearer: Optional callback invoked after
        ``/disconnect_jira`` to wipe the caller's in-memory Jira
        identity on the ``TelegramUserSession``. Callers that track
        per-user sessions (``TelegramAgentWrapper``) should pass a
        closure over their ``_user_sessions`` dict.
