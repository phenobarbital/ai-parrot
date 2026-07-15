---
type: Wiki Entity
title: ConversationDynamoDB
id: class:parrot.storage.backends.dynamodb.ConversationDynamoDB
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Domain wrapper around DynamoDB for conversation storage.
relates_to:
- concept: class:parrot.storage.backends.base.ConversationBackend
  rel: extends
---

# ConversationDynamoDB

Defined in [`parrot.storage.backends.dynamodb`](../summaries/mod:parrot.storage.backends.dynamodb.md).

```python
class ConversationDynamoDB(ConversationBackend)
```

Domain wrapper around DynamoDB for conversation storage.

Uses a single ``aioboto3`` session with two table targets — one for
conversations (thread metadata + turns) and one for artifacts.

All low-level DynamoDB operations (serialization, pagination, retries)
are handled by aioboto3.  This class only adds PK/SK construction,
TTL setting, and domain-specific query patterns.

Args:
    conversations_table: DynamoDB table name for conversations.
    artifacts_table: DynamoDB table name for artifacts.
    dynamo_params: Dict with ``region_name``, ``aws_access_key_id``,
        ``aws_secret_access_key``, and optional ``endpoint_url``.

## Methods

- `async def initialize(self) -> None` — Open aioboto3 resource connections to both tables (idempotent).
- `async def close(self) -> None` — Close aioboto3 resource connections.
- `def is_connected(self) -> bool` — Return True if the DynamoDB resource is available.
- `def build_overflow_prefix(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> str` — Return the S3 key prefix, byte-identical to the original layout.
- `async def put_thread(self, user_id: str, agent_id: str, session_id: str, metadata: dict) -> None` — Create or replace a thread metadata item.
- `async def update_thread(self, user_id: str, agent_id: str, session_id: str, **updates) -> None` — Update specific attributes on a thread metadata item.
- `async def query_threads(self, user_id: str, agent_id: str, limit: int=50) -> List[dict]` — List thread metadata items for a user+agent pair, newest first.
- `async def put_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str, data: dict) -> None` — Store a conversation turn.
- `async def query_turns(self, user_id: str, agent_id: str, session_id: str, limit: int=10, newest_first: bool=True) -> List[dict]` — Query conversation turns for a session.
- `async def delete_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str) -> bool` — Delete a single conversation turn.
- `async def delete_thread_cascade(self, user_id: str, agent_id: str, session_id: str) -> int` — Delete all items for a session from the conversations table.
- `async def put_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str, data: dict) -> None` — Store an artifact item.
- `async def get_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> Optional[dict]` — Get a single artifact by its key.
- `async def query_artifacts(self, user_id: str, agent_id: str, session_id: str) -> List[dict]` — List all artifacts for a session.
- `async def delete_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> None` — Delete a single artifact.
- `async def delete_session_artifacts(self, user_id: str, agent_id: str, session_id: str) -> int` — Delete all artifacts for a session.
