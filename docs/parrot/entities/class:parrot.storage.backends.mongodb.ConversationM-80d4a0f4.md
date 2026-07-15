---
type: Wiki Entity
title: ConversationMongoBackend
id: class:parrot.storage.backends.mongodb.ConversationMongoBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async MongoDB implementation of ConversationBackend.
relates_to:
- concept: class:parrot.storage.backends.base.ConversationBackend
  rel: extends
---

# ConversationMongoBackend

Defined in [`parrot.storage.backends.mongodb`](../summaries/mod:parrot.storage.backends.mongodb.md).

```python
class ConversationMongoBackend(ConversationBackend)
```

Async MongoDB implementation of ConversationBackend.

Uses ``motor`` (the async MongoDB driver) accessed via ``asyncdb[mongo]``.
Two collections are used:
  - ``conversations``: thread metadata + turns (discriminated by ``kind``).
  - ``artifacts``: artifact items.

``replace_one(..., upsert=True)`` is used for all writes to match
DynamoDB's overwrite-or-create semantics.

Args:
    dsn: MongoDB connection string, e.g.
        ``"mongodb://user:pw@host:27017/parrot"``.
    database: Database name (default ``"parrot"``).
    default_ttl_days: TTL for new documents in days (default 180).

## Methods

- `async def initialize(self) -> None` — Connect to MongoDB and create indexes (idempotent).
- `async def close(self) -> None` — Close the MongoDB client.
- `def is_connected(self) -> bool`
- `async def put_thread(self, user_id: str, agent_id: str, session_id: str, metadata: dict) -> None`
- `async def update_thread(self, user_id: str, agent_id: str, session_id: str, **updates) -> None`
- `async def query_threads(self, user_id: str, agent_id: str, limit: int=50) -> List[dict]`
- `async def put_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str, data: dict) -> None`
- `async def query_turns(self, user_id: str, agent_id: str, session_id: str, limit: int=10, newest_first: bool=True) -> List[dict]`
- `async def delete_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str) -> bool`
- `async def delete_thread_cascade(self, user_id: str, agent_id: str, session_id: str) -> int`
- `async def put_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str, data: dict) -> None`
- `async def get_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> Optional[dict]`
- `async def query_artifacts(self, user_id: str, agent_id: str, session_id: str) -> List[dict]`
- `async def delete_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> None`
- `async def delete_session_artifacts(self, user_id: str, agent_id: str, session_id: str) -> int`
- `async def sweep_expired(self) -> int` — No-op for Mongo: TTL indexes handle expiry automatically.
