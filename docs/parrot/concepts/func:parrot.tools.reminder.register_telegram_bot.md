---
type: Concept
title: register_telegram_bot()
id: func:parrot.tools.reminder.register_telegram_bot
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register a Telegram bot token under its non-secret numeric id.
---

# register_telegram_bot

```python
def register_telegram_bot(bot_id: str | int, bot_token: str) -> None
```

Register a Telegram bot token under its non-secret numeric id.

Called by the Telegram integration when a bot starts so that
:func:`deliver_reminder` can deliver through the same bot the user
interacted with.

Args:
    bot_id: The bot's Telegram numeric id (token prefix before ``:``).
    bot_token: The full ``<id>:<secret>`` bot token.
