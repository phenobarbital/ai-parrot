---
type: Wiki Entity
title: UserProfileKB
id: class:parrot.stores.kb.user.UserProfileKB
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: KB that queries database for user information.
relates_to:
- concept: class:parrot.stores.kb.abstract.AbstractKnowledgeBase
  rel: extends
---

# UserProfileKB

Defined in [`parrot.stores.kb.user`](../summaries/mod:parrot.stores.kb.user.md).

```python
class UserProfileKB(AbstractKnowledgeBase)
```

KB that queries database for user information.

## Methods

- `async def should_activate(self, query: str, context: Dict) -> Tuple[bool, float]` — Check if query references user-specific information.
- `async def search(self, query: str, user_id: str=None, **kwargs) -> List[Dict]` — Query database for user information.
