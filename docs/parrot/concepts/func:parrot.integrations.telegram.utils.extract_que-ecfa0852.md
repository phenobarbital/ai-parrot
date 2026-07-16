---
type: Concept
title: extract_query_from_mention()
id: func:parrot.integrations.telegram.utils.extract_query_from_mention
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract the actual query from a mention or command message.
---

# extract_query_from_mention

```python
async def extract_query_from_mention(message: Message, bot: Bot) -> str
```

Extract the actual query from a mention or command message.

Strips the @bot_username and any leading /command from the message
to get the user's actual query text.

Args:
    message: The Telegram message
    bot: The aiogram Bot instance

Returns:
    Cleaned query string with @mention and /command removed

Examples:
    "@mybot what is Python?" -> "what is Python?"
    "Hey @mybot tell me about AI" -> "Hey tell me about AI"
    "/ask@mybot what is RAG?" -> "what is RAG?"
    "/ask what is machine learning?" -> "what is machine learning?"
