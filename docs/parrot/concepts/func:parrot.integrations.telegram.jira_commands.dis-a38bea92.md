---
type: Concept
title: disconnect_jira_handler()
id: func:parrot.integrations.telegram.jira_commands.disconnect_jira_handler
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle ``/disconnect_jira`` — revoke stored tokens and clear session.
---

# disconnect_jira_handler

```python
async def disconnect_jira_handler(message: Message, oauth_manager: 'JiraOAuthManager', session_clearer: Optional[SessionClearer]=None) -> None
```

Handle ``/disconnect_jira`` — revoke stored tokens and clear session.

Args:
    message: Incoming ``/disconnect_jira`` update.
    oauth_manager: Manager used to revoke the persisted tokens.
    session_clearer: Optional callback invoked with the Telegram user id
        after revocation to wipe the in-memory ``TelegramUserSession``
        Jira fields. Without this the ``user_context`` prompt enrichment
        keeps announcing the old Jira identity until the process
        restarts or the user logs out.
