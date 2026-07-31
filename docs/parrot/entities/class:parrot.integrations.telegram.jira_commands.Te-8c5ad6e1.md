---
type: Wiki Entity
title: TelegramOAuthNotifier
id: class:parrot.integrations.telegram.jira_commands.TelegramOAuthNotifier
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Push a confirmation message to the originating Telegram chat after
---

# TelegramOAuthNotifier

Defined in [`parrot.integrations.telegram.jira_commands`](../summaries/mod:parrot.integrations.telegram.jira_commands.md).

```python
class TelegramOAuthNotifier
```

Push a confirmation message to the originating Telegram chat after
a successful Jira OAuth callback.

The OAuth callback route stores the chat id under ``extra_state`` when
generating the authorization URL; this notifier reads the chat id back
and sends a friendly confirmation.

## Methods

- `async def notify_connected(self, chat_id: int, display_name: str, site_url: str) -> None`
- `async def notify_failure(self, chat_id: int, reason: str) -> None`
