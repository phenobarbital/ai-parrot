---
type: Wiki Entity
title: CommandInGroupFilter
id: class:parrot.integrations.telegram.filters.CommandInGroupFilter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Filter that matches commands directed at this bot in groups.
---

# CommandInGroupFilter

Defined in [`parrot.integrations.telegram.filters`](../summaries/mod:parrot.integrations.telegram.filters.md).

```python
class CommandInGroupFilter(Filter)
```

Filter that matches commands directed at this bot in groups.

Handles both:
- /command (standard command)
- /command@bot_username (command explicitly for this bot)

Usage:
    @router.message(CommandInGroupFilter("ask"))
    async def handle_ask(message: Message, bot: Bot):
        ...
