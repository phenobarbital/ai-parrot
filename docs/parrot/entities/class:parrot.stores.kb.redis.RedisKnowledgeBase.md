---
type: Wiki Entity
title: RedisKnowledgeBase
id: class:parrot.stores.kb.redis.RedisKnowledgeBase
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generic Redis-based Knowledge Base with CRUD operations.
relates_to:
- concept: class:parrot.stores.kb.abstract.AbstractKnowledgeBase
  rel: extends
---

# RedisKnowledgeBase

Defined in [`parrot.stores.kb.redis`](../summaries/mod:parrot.stores.kb.redis.md).

```python
class RedisKnowledgeBase(AbstractKnowledgeBase)
```

Generic Redis-based Knowledge Base with CRUD operations.

Supports both hash storage (HSET/HGET) and simple key-value storage (SET/GET).
Provides flexible search, filtering, and data management capabilities.

## Methods

- `async def should_activate(self, query: str, context: Dict[str, Any]) -> Tuple[bool, float]` — Default activation strategy based on configured patterns.
- `async def search(self, query: str, *, identifier: Optional[str]=None, field_filter: Optional[List[str]]=None, match_fn: Optional[Callable]=None, limit: int=100, **kwargs: Any) -> List[Dict[str, Any]]` — Search for entries matching the query.
- `async def list_all(self, pattern: Optional[str]=None, limit: int=1000) -> List[Dict[str, Any]]` — List all entries matching a pattern.
- `async def count(self, pattern: Optional[str]=None) -> int` — Count entries matching a pattern.
- `async def clear_all(self, pattern: Optional[str]=None) -> int` — Delete all entries matching a pattern.
- `async def set_ttl(self, identifier: str, ttl: int, **kwargs) -> bool` — Set TTL for a key.
- `async def get_ttl(self, identifier: str, **kwargs) -> Optional[int]` — Get remaining TTL for a key.
- `async def ping(self) -> bool` — Test Redis connection.
- `async def close(self)` — Close Redis connection.
- `async def insert(self, identifier: str, data: Union[Dict[str, Any], str, Any], field: Optional[str]=None, ttl: Optional[int]=None, **kwargs) -> bool` — Insert or update data in Redis.
- `async def get(self, identifier: str, field: Optional[str]=None, default: Any=None, **kwargs) -> Any` — Retrieve data from Redis.
- `async def update(self, identifier: str, data: Union[Dict[str, Any], Any], field: Optional[str]=None, **kwargs) -> bool` — Update existing data (alias for insert with merge capability).
- `async def delete(self, identifier: str, field: Optional[str]=None, **kwargs) -> bool` — Delete data from Redis.
- `async def exists(self, identifier: str, field: Optional[str]=None, **kwargs) -> bool` — Check if key or field exists.
- `async def bulk_insert(self, items: List[Dict[str, Any]], identifier_key: str='id', ttl: Optional[int]=None) -> int` — Insert multiple items in bulk.
- `async def bulk_get(self, identifiers: List[str], **kwargs) -> Dict[str, Any]` — Retrieve multiple items in bulk.
- `async def bulk_delete(self, identifiers: List[str], **kwargs) -> int` — Delete multiple items in bulk.
