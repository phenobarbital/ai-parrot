# TASK-718: DynamoDB Backend (ConversationDynamoDB)

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-717
**Assigned-to**: unassigned

---

## Context

Implements spec Module 2. This is the core DynamoDB integration layer that wraps `asyncdb`'s built-in `dynamodb` driver with domain-specific methods for conversation storage. All other storage modules (ArtifactStore, ChatStorage migration) depend on this.

---

## Scope

- Create `parrot/storage/dynamodb.py` with `ConversationDynamoDB` class
- The class wraps two `asyncdb` dynamodb driver instances — one per table (conversations, artifacts)
- Implement domain methods for PK/SK construction, TTL setting, and all access patterns:
  - `put_thread()`, `update_thread()`, `query_threads()` — thread metadata CRUD
  - `put_turn()`, `query_turns()` — turn storage with limit/sort support
  - `delete_thread_cascade()` — delete all items for a session from conversations table
  - `put_artifact()`, `get_artifact()`, `query_artifacts()`, `delete_artifact()`, `delete_session_artifacts()` — artifact CRUD on artifacts table
- Implement graceful degradation: catch `DriverError`/`ConnectionTimeout`, log warning, return empty/None
- Implement `initialize()` and `close()` lifecycle methods
- Write unit tests with mocked asyncdb driver

**NOT in scope**: S3 overflow, ArtifactStore business logic, ChatStorage migration, API endpoints.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/dynamodb.py` | CREATE | ConversationDynamoDB class |
| `parrot/storage/__init__.py` | MODIFY | Export ConversationDynamoDB |
| `tests/storage/test_dynamodb_backend.py` | CREATE | Unit tests with mocked driver |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# asyncdb DynamoDB driver:
from asyncdb import AsyncDB                                        # asyncdb/__init__.py
from asyncdb.exceptions import DriverError, ConnectionTimeout      # asyncdb/exceptions.py

# Logging:
from navconfig.logging import logging                              # used by ChatStorage

# Models from TASK-717:
from parrot.storage.models import Artifact, ThreadMetadata         # after TASK-717 completes
```

### Existing Signatures to Use
```python
# asyncdb/drivers/dynamodb.py:62
class dynamodb(InitDriver):
    async def connection(self, **kwargs) -> "dynamodb":  # line 146
    async def close(self, timeout=10) -> None:           # line 177
    async def get(self, table=None, key=None, **kwargs) -> Optional[dict]:  # line 343
    async def set(self, table=None, item=None, **kwargs) -> bool:           # line 376
    async def delete(self, table=None, key=None, **kwargs) -> bool:         # line 405
    async def update(self, table=None, key=None, update_expression=None,
                     expression_values=None, **kwargs) -> Optional[dict]:   # line 446
    async def query(self, table=None, **kwargs) -> Optional[list[dict]]:    # line 501
    async def write_batch(self, table=None, items=None, **kwargs) -> bool:  # line 734

# Usage pattern:
# async with AsyncDB("dynamodb", params={"region_name": "us-east-1", ...}) as db:
#     await db.set(table="my-table", item={"PK": "val", "SK": "val", ...})
#     results = await db.query(table="my-table",
#         KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
#         ExpressionAttributeValues={":pk": "val", ":prefix": "THREAD#"})
```

### Does NOT Exist
- ~~`parrot.storage.dynamodb`~~ — does not exist yet; this task creates it
- ~~`parrot.interfaces.dynamodb`~~ — do NOT create here; use asyncdb's driver
- ~~`ConversationDynamoDB`~~ — does not exist yet; this task creates it
- ~~`asyncdb.drivers.dynamodb.dynamodb.batch_delete()`~~ — no such method; use query + delete loop or write_batch with DeleteRequest

---

## Implementation Notes

### Pattern to Follow
```python
from asyncdb import AsyncDB
from asyncdb.exceptions import DriverError, ConnectionTimeout
from navconfig.logging import logging

class ConversationDynamoDB:
    def __init__(self, conversations_table: str, artifacts_table: str,
                 dynamo_params: dict):
        self._conversations_table = conversations_table
        self._artifacts_table = artifacts_table
        self._dynamo_params = dynamo_params
        self._db = None  # asyncdb dynamodb driver instance
        self.logger = logging.getLogger("parrot.storage.ConversationDynamoDB")

    async def initialize(self) -> None:
        """Open asyncdb connection."""
        try:
            self._db = AsyncDB("dynamodb", params=self._dynamo_params)
            await self._db.connection()
        except (DriverError, ConnectionTimeout) as exc:
            self.logger.warning(f"DynamoDB unavailable: {exc}")
            self._db = None

    @staticmethod
    def _build_pk(user_id: str, agent_id: str) -> str:
        return f"USER#{user_id}#AGENT#{agent_id}"

    @staticmethod
    def _ttl_epoch(updated_at, days: int = 180) -> int:
        from datetime import timedelta
        return int((updated_at + timedelta(days=days)).timestamp())

    async def put_turn(self, user_id, agent_id, session_id, turn_id, data: dict):
        if not self._db:
            return
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#TURN#{turn_id}"
        item = {"PK": pk, "SK": sk, "type": "turn", **data,
                "ttl": self._ttl_epoch(data.get("timestamp", datetime.now()))}
        try:
            await self._db.set(table=self._conversations_table, item=item)
        except (DriverError, Exception) as exc:
            self.logger.warning(f"DynamoDB put_turn failed: {exc}")
```

### Key Constraints
- Use ONE `asyncdb` connection for BOTH tables (the driver supports specifying table per operation)
- All methods must catch exceptions and log warnings — never raise to caller
- PK format: `USER#{user_id}#AGENT#{agent_id}`
- SK format: `THREAD#{session_id}` (metadata), `THREAD#{session_id}#TURN#{turn_id}` (turns), `THREAD#{session_id}#{artifact_id}` (artifacts)
- Every item must include `ttl` attribute = epoch seconds (updated_at + 180 days)
- `query_turns()` must support `Limit` and `ScanIndexForward=false` for newest-first

---

## Acceptance Criteria

- [ ] `ConversationDynamoDB` class exists in `parrot/storage/dynamodb.py`
- [ ] `from parrot.storage import ConversationDynamoDB` works
- [ ] All domain methods implemented: put_thread, update_thread, query_threads, put_turn, query_turns, delete_thread_cascade, put_artifact, get_artifact, query_artifacts, delete_artifact, delete_session_artifacts
- [ ] Graceful degradation: if asyncdb connection fails, methods log warning and return empty/None
- [ ] TTL attribute set on every PutItem
- [ ] Unit tests pass with mocked asyncdb driver
- [ ] `pytest tests/storage/test_dynamodb_backend.py -v` passes

---

## Test Specification

```python
# tests/storage/test_dynamodb_backend.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.storage.dynamodb import ConversationDynamoDB


@pytest.fixture
def dynamo_backend():
    return ConversationDynamoDB(
        conversations_table="test-conversations",
        artifacts_table="test-artifacts",
        dynamo_params={"region_name": "us-east-1", "endpoint_url": "http://localhost:8000"},
    )


class TestConversationDynamoDB:
    def test_build_pk(self):
        pk = ConversationDynamoDB._build_pk("u123", "sales-bot")
        assert pk == "USER#u123#AGENT#sales-bot"

    def test_ttl_epoch(self):
        from datetime import datetime
        now = datetime(2025, 4, 16, 12, 0, 0)
        ttl = ConversationDynamoDB._ttl_epoch(now, days=180)
        assert ttl > 0
        # Should be ~180 days from now
        assert ttl > int(now.timestamp())

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, dynamo_backend):
        # Not initialized — methods should return None/empty without raising
        result = await dynamo_backend.query_threads("u1", "agent1")
        assert result == [] or result is None

    @pytest.mark.asyncio
    async def test_put_turn_constructs_correct_keys(self, dynamo_backend):
        mock_db = AsyncMock()
        dynamo_backend._db = mock_db
        await dynamo_backend.put_turn("u1", "agent1", "sess1", "t001", {
            "user_message": "hello",
            "assistant_response": "hi",
        })
        mock_db.set.assert_called_once()
        call_kwargs = mock_db.set.call_args
        item = call_kwargs.kwargs.get("item") or call_kwargs[1].get("item")
        assert item["PK"] == "USER#u1#AGENT#agent1"
        assert item["SK"] == "THREAD#sess1#TURN#t001"
        assert "ttl" in item
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-artifact-persistency.spec.md` — Section 2 (DynamoDB Table Design, Access Patterns) and Section 6 (asyncdb driver signatures)
2. **Check dependencies** — TASK-717 must be completed (models available)
3. **Verify asyncdb driver** — `read` the asyncdb dynamodb driver to confirm method signatures
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** ConversationDynamoDB in `parrot/storage/dynamodb.py`
6. **Run tests**: `pytest tests/storage/test_dynamodb_backend.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
