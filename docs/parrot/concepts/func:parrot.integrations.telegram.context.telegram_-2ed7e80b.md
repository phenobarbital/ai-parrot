---
type: Concept
title: telegram_chat_scope()
id: func:parrot.integrations.telegram.context.telegram_chat_scope
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Set the current Telegram chat id for the duration of the block.
---

# telegram_chat_scope

```python
def telegram_chat_scope(chat_id: int | str | None) -> Iterator[None]
```

Set the current Telegram chat id for the duration of the block.
