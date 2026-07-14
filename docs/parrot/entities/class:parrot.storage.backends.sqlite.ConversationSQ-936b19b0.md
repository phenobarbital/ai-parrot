---
type: Wiki Entity
title: ConversationSQLiteBackend
id: class:parrot.storage.backends.sqlite.ConversationSQLiteBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async SQLite implementation of ConversationBackend.
relates_to:
- concept: class:parrot.storage.backends.base.ConversationBackend
  rel: extends
---

# ConversationSQLiteBackend

Defined in [`parrot.storage.backends.sqlite`](../summaries/mod:parrot.storage.backends.sqlite.md).

```python
class ConversationSQLiteBackend(ConversationBackend)
```

Async SQLite implementation of ConversationBackend.

Stores threads, turns, and artifacts in two local SQLite tables.
Payload dicts are JSON-encoded so the schema stays simple.

Turn IDs MUST be zero-padded for lexicographic ordering to match
numeric ordering (e.g. ``"001"``, ``"002"``). This mirrors the
DynamoDB reference implementation.

Args:
    path: Filesystem path to the SQLite database file.
    default_ttl_days: TTL for new rows in days (default 180).

## Methods

- `async def initialize(self) -> None` — Open the database connection and create tables (idempotent).
- `async def close(self) -> None` — Close the database connection.
- `def is_connected(self) -> bool` — Return True when the connection is open.
- `async def put_thread(self, user_id: str, agent_id: str, session_id: str, metadata: dict) -> None` — Create or replace a thread metadata row.
- `async def update_thread(self, user_id: str, agent_id: str, session_id: str, **updates) -> None` — Update specific attributes on a thread metadata row.
- `async def query_threads(self, user_id: str, agent_id: str, limit: int=50) -> List[dict]` — List thread metadata items for a user+agent pair, newest first.
- `async def put_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str, data: dict) -> None` — Store a conversation turn.
- `async def query_turns(self, user_id: str, agent_id: str, session_id: str, limit: int=10, newest_first: bool=True) -> List[dict]` — Query conversation turns for a session.
- `async def delete_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str) -> bool` — Delete a single conversation turn.
- `async def delete_thread_cascade(self, user_id: str, agent_id: str, session_id: str) -> int` — Delete all conversation items + artifacts for a session.
- `async def put_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str, data: dict) -> None` — Store an artifact row.
- `async def get_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> Optional[dict]` — Get a single artifact by its key.
- `async def query_artifacts(self, user_id: str, agent_id: str, session_id: str) -> List[dict]` — List all artifacts for a session.
- `async def delete_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> None` — Delete a single artifact row.
- `async def delete_session_artifacts(self, user_id: str, agent_id: str, session_id: str) -> int` — Delete all artifacts for a session.
- `async def sweep_expired(self) -> int` — Delete all rows whose ``expires_at`` is in the past.
