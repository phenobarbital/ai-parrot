---
type: Concept
title: create_bot()
id: func:parrot.handlers.models.bots.create_bot
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a BasicBot instance from a BotModel database record.
---

# create_bot

```python
def create_bot(bot_model: BotModel, bot_class=None)
```

Create a BasicBot instance from a BotModel database record.

Args:
    bot_model: BotModel instance from database
    bot_class: Optional bot class to use (defaults to UnifiedBot)

Returns:
    Configured bot instance
