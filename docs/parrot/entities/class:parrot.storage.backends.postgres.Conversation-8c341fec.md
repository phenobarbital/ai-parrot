---
type: Wiki Entity
title: ConversationPostgresBackend
id: class:parrot.storage.backends.postgres.ConversationPostgresBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async PostgreSQL implementation of ConversationBackend.
relates_to:
- concept: class:parrot.storage.backends.base.ConversationBackend
  rel: extends
---

# ConversationPostgresBackend

Defined in [`parrot.storage.backends.postgres`](../summaries/mod:parrot.storage.backends.postgres.md).

```python
class ConversationPostgresBackend(ConversationBackend)
```

Async PostgreSQL implementation of ConversationBackend.

Uses asyncpg directly (via a thin wrapper) for JSONB support.
Every ``put_*`` operation uses ``INSERT ... ON CONFLICT ... DO UPDATE``
semantics to match DynamoDB's overwrite-or-create behaviour.

Args:
    dsn: PostgreSQL DSN, e.g.
        ``"postgresql://user:pw@host:5432/parrot"``.
    default_ttl_days: TTL for new rows in days (default 180).

## Methods

- `async def initialize(self) -> None` — Open connection pool and create tables (idempotent).
- `async def close(self) -> None` — Close connection pool.
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
- `async def sweep_expired(self) -> int` — Delete rows past their TTL (optional helper, not auto-called).
