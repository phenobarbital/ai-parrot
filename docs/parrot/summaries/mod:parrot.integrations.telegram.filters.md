---
type: Wiki Summary
title: parrot.integrations.telegram.filters
id: mod:parrot.integrations.telegram.filters
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Custom aiogram filters for Telegram bot message handling.
relates_to:
- concept: class:parrot.integrations.telegram.filters.BotMentionedFilter
  rel: defines
- concept: class:parrot.integrations.telegram.filters.CommandInGroupFilter
  rel: defines
---

# `parrot.integrations.telegram.filters`

Custom aiogram filters for Telegram bot message handling.

Provides filters for detecting bot mentions in group messages.

## Classes

- **`BotMentionedFilter(Filter)`** — Filter that matches messages where the bot is @mentioned.
- **`CommandInGroupFilter(Filter)`** — Filter that matches commands directed at this bot in groups.
