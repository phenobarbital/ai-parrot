---
type: Concept
title: mention_from_username()
id: func:parrot.integrations.telegram.crew.mention.mention_from_username
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build an @mention string from a Telegram username.
---

# mention_from_username

```python
def mention_from_username(username: str) -> str
```

Build an @mention string from a Telegram username.

Idempotent: strips leading @ if already present.

Args:
    username: Telegram username, with or without leading @.

Returns:
    String in the format ``@username``.
