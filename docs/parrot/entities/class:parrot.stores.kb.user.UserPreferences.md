---
type: Wiki Entity
title: UserPreferences
id: class:parrot.stores.kb.user.UserPreferences
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: KB for user preferences stored in Redis.
relates_to:
- concept: class:parrot.stores.kb.redis.RedisKnowledgeBase
  rel: extends
---

# UserPreferences

Defined in [`parrot.stores.kb.user`](../summaries/mod:parrot.stores.kb.user.md).

```python
class UserPreferences(RedisKnowledgeBase)
```

KB for user preferences stored in Redis.

## Methods

- `async def search(self, query: str, user_id: Optional[str]=None, **kwargs) -> List[Dict[str, Any]]` — Retrieve user preferences matching the query.
- `async def set_preference(self, user_id: str, preference: str, value: Any) -> bool` — Set a single user preference.
- `async def get_preference(self, user_id: str, preference: str, default: Any=None) -> Any` — Get a single user preference.
- `async def delete_preference(self, user_id: str, preference: str) -> bool` — Delete a single user preference.
- `async def get_all_preferences(self, user_id: str) -> Dict[str, Any]` — Get all preferences for a user.
- `async def clear_all_preferences(self, user_id: str) -> bool` — Clear all preferences for a user.
- `async def update_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool` — Update multiple preferences at once.
- `async def has_preference(self, user_id: str, preference: str) -> bool` — Check if a user has a specific preference set.
- `async def list_user_preference_keys(self, user_id: str) -> List[str]` — Get list of all preference keys for a user.
