---
type: Wiki Summary
title: parrot.integrations.telegram.utils
id: mod:parrot.integrations.telegram.utils
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Utility functions for Telegram bot message processing.
relates_to:
- concept: func:parrot.integrations.telegram.utils.extract_query_from_mention
  rel: defines
- concept: func:parrot.integrations.telegram.utils.get_user_display_name
  rel: defines
---

# `parrot.integrations.telegram.utils`

Utility functions for Telegram bot message processing.

Provides helpers for extracting user queries from group messages.

## Functions

- `async def extract_query_from_mention(message: Message, bot: Bot) -> str` — Extract the actual query from a mention or command message.
- `def get_user_display_name(message: Message) -> str` — Get a display name for the message sender.
