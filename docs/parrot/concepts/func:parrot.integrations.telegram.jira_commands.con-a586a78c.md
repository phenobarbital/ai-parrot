---
type: Concept
title: connect_jira_handler()
id: func:parrot.integrations.telegram.jira_commands.connect_jira_handler
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle ``/connect_jira`` — send the authorization URL or a status.
---

# connect_jira_handler

```python
async def connect_jira_handler(message: Message, oauth_manager: 'JiraOAuthManager') -> None
```

Handle ``/connect_jira`` — send the authorization URL or a status.

All replies use ``parse_mode=None`` because the bot is constructed with
a default Markdown parse mode (see ``manager.py``) and command names such
as ``/jira_status`` contain underscores that Markdown would interpret as
unclosed italic markers, raising ``TelegramBadRequest`` on send.
