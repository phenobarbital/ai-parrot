---
type: Wiki Entity
title: UserPrompts
id: class:parrot.handlers.models.users_prompts.UserPrompts
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-user prompt definition.
---

# UserPrompts

Defined in [`parrot.handlers.models.users_prompts`](../summaries/mod:parrot.handlers.models.users_prompts.md).

```python
class UserPrompts(Model)
```

Per-user prompt definition.

All fields mirror :class:`PromptLibrary` semantics where applicable,
plus ``user_id`` and the future-promotion flag ``is_public``.
