---
type: Wiki Entity
title: BotMentionedFilter
id: class:parrot.integrations.telegram.filters.BotMentionedFilter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Filter that matches messages where the bot is @mentioned.
---

# BotMentionedFilter

Defined in [`parrot.integrations.telegram.filters`](../summaries/mod:parrot.integrations.telegram.filters.md).

```python
class BotMentionedFilter(Filter)
```

Filter that matches messages where the bot is @mentioned.

Works by checking:
1. Message entities for 'mention' type matching the bot username
2. Message text containing @bot_username (fallback)

Usage:
    @router.message(BotMentionedFilter())
    async def handle_mention(message: Message, bot: Bot):
        ...
