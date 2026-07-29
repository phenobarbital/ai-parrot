---
type: Wiki Entity
title: UserInfo
id: class:parrot.stores.kb.user.UserInfo
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Class to manage user information.
relates_to:
- concept: class:parrot.stores.kb.abstract.AbstractKnowledgeBase
  rel: extends
---

# UserInfo

Defined in [`parrot.stores.kb.user`](../summaries/mod:parrot.stores.kb.user.md).

```python
class UserInfo(AbstractKnowledgeBase)
```

Class to manage user information.

## Methods

- `async def should_activate(self, query: str, context: dict) -> Tuple[bool, float]`
- `async def search(self, query: str, user_id: int, **kwargs) -> List[Dict]` — Query Database for User Information.
