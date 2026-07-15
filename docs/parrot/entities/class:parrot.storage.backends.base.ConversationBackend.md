---
type: Wiki Entity
title: ConversationBackend
id: class:parrot.storage.backends.base.ConversationBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract storage backend for conversations, threads, turns, and artifacts.
---

# ConversationBackend

Defined in [`parrot.storage.backends.base`](../summaries/mod:parrot.storage.backends.base.md).

```python
class ConversationBackend(ABC)
```

Abstract storage backend for conversations, threads, turns, and artifacts.

All implementations MUST preserve the semantics of the DynamoDB reference
implementation (see backends/dynamodb.py). Verified by the shared contract
test suite in tests/storage/test_backend_contract.py.

The ABC operates on plain ``dict`` payloads; Pydantic model
serialization/deserialization is the responsibility of ``ChatStorage``
and ``ArtifactStore``.

## Methods

- `async def initialize(self) -> None` — Open connections and create schema/indexes if needed (idempotent).
- `async def close(self) -> None` — Release all backend connections.
- `def is_connected(self) -> bool` — Return True when the backend is ready to accept requests.
- `async def put_thread(self, user_id: str, agent_id: str, session_id: str, metadata: dict) -> None` — Create or replace a thread metadata item.
- `async def update_thread(self, user_id: str, agent_id: str, session_id: str, **updates) -> None` — Update specific attributes on an existing thread metadata item.
- `async def query_threads(self, user_id: str, agent_id: str, limit: int=50) -> List[dict]` — List thread metadata items for a user+agent pair, newest first.
- `async def put_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str, data: dict) -> None` — Store a conversation turn.
- `async def query_turns(self, user_id: str, agent_id: str, session_id: str, limit: int=10, newest_first: bool=True) -> List[dict]` — Query conversation turns for a session.
- `async def delete_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str) -> bool` — Delete a single conversation turn.
- `async def delete_thread_cascade(self, user_id: str, agent_id: str, session_id: str) -> int` — Delete all items for a session (thread metadata + turns + artifacts).
- `async def put_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str, data: dict) -> None` — Store an artifact item.
- `async def get_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> Optional[dict]` — Get a single artifact by its key.
- `async def query_artifacts(self, user_id: str, agent_id: str, session_id: str) -> List[dict]` — List all artifacts for a session.
- `async def delete_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> None` — Delete a single artifact.
- `async def delete_session_artifacts(self, user_id: str, agent_id: str, session_id: str) -> int` — Delete all artifacts for a session.
- `def build_overflow_prefix(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> str` — Return a stable key prefix for overflow storage.
