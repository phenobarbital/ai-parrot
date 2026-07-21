---
type: Concept
title: mention_from_user_id()
id: func:parrot.integrations.telegram.crew.mention.mention_from_user_id
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build a Telegram HTML deep-link mention from a user ID.
---

# mention_from_user_id

```python
def mention_from_user_id(user_id: int, display_name: str) -> str
```

Build a Telegram HTML deep-link mention from a user ID.

Args:
    user_id: Telegram user ID.
    display_name: Display name shown in the mention link.

Returns:
    HTML anchor tag linking to the user via ``tg://user?id=``.
