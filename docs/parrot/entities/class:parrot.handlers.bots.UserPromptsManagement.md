---
type: Wiki Entity
title: UserPromptsManagement
id: class:parrot.handlers.bots.UserPromptsManagement
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-user prompt library.
---

# UserPromptsManagement

Defined in [`parrot.handlers.bots`](../summaries/mod:parrot.handlers.bots.md).

```python
class UserPromptsManagement(ModelView)
```

Per-user prompt library.

Exposes CRUD over ``navigator.users_prompts`` at
``/api/v1/agents/user_prompts``. Every read/write is scoped to the
authenticated ``user_id``; clients cannot supply or spoof it.

## Methods

- `async def get(self)` — Override GET to require an authenticated session.
