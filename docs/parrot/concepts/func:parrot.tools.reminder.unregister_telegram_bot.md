---
type: Concept
title: unregister_telegram_bot()
id: func:parrot.tools.reminder.unregister_telegram_bot
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Remove a previously registered Telegram bot token.
---

# unregister_telegram_bot

```python
def unregister_telegram_bot(bot_id: str | int) -> None
```

Remove a previously registered Telegram bot token.

Args:
    bot_id: The bot's Telegram numeric id used at registration time.
