---
type: Wiki Entity
title: UserContext
id: class:parrot.stores.kb.doc.UserContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Knowledge Base for user context and session data.
relates_to:
- concept: class:parrot.stores.kb.redis.RedisKnowledgeBase
  rel: extends
---

# UserContext

Defined in [`parrot.stores.kb.doc`](../summaries/mod:parrot.stores.kb.doc.md).

```python
class UserContext(RedisKnowledgeBase)
```

Knowledge Base for user context and session data.

## Methods

- `async def search(self, query: str, user_id: Optional[str]=None, **kwargs) -> List[Dict[str, Any]]` — Retrieve user context matching the query.
- `async def update_context(self, user_id: str, context_data: Dict[str, Any]) -> bool` — Update user context with new data.
- `async def get_context(self, user_id: str) -> Dict[str, Any]` — Get all context for a user.
- `async def set_context_field(self, user_id: str, field: str, value: Any) -> bool` — Set a specific context field.
- `async def get_context_field(self, user_id: str, field: str, default: Any=None) -> Any` — Get a specific context field.
- `async def clear_context(self, user_id: str) -> bool` — Clear all context for a user.
