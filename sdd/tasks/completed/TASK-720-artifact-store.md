# TASK-720: ArtifactStore

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-717, TASK-718, TASK-719
**Assigned-to**: unassigned

---

## Context

Implements spec Module 4. High-level artifact CRUD operations that compose `ConversationDynamoDB` (artifacts table) and `S3OverflowManager`. This is the interface that API endpoints and handler integrations use for artifact persistence.

---

## Scope

- Create `parrot/storage/artifacts.py` with `ArtifactStore` class
- Implement: `save_artifact()`, `get_artifact()`, `list_artifacts()`, `update_artifact()`, `delete_artifact()`
- `save_artifact` runs S3 overflow check before writing to DynamoDB
- `get_artifact` resolves S3 references transparently
- `list_artifacts` returns `ArtifactSummary` list (no full definitions)
- `delete_artifact` cleans up both DynamoDB item and S3 object
- Export from `parrot/storage/__init__.py`
- Write unit tests

**NOT in scope**: ChatStorage migration, API endpoints, handler integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/artifacts.py` | CREATE | ArtifactStore class |
| `parrot/storage/__init__.py` | MODIFY | Export ArtifactStore |
| `tests/storage/test_artifact_store.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage.models import Artifact, ArtifactSummary, ArtifactType  # after TASK-717
from parrot.storage.dynamodb import ConversationDynamoDB                     # after TASK-718
from parrot.storage.s3_overflow import S3OverflowManager                    # after TASK-719
from navconfig.logging import logging
```

### Existing Signatures to Use
```python
# From TASK-718 (ConversationDynamoDB):
async def put_artifact(self, user_id, agent_id, session_id, artifact_id, data): ...
async def get_artifact(self, user_id, agent_id, session_id, artifact_id) -> Optional[dict]: ...
async def query_artifacts(self, user_id, agent_id, session_id) -> List[dict]: ...
async def delete_artifact(self, user_id, agent_id, session_id, artifact_id): ...

# From TASK-719 (S3OverflowManager):
async def maybe_offload(self, data, key_prefix) -> tuple[dict|None, str|None]: ...
async def resolve(self, definition, definition_ref) -> dict: ...
async def delete(self, definition_ref): ...
```

### Does NOT Exist
- ~~`parrot.storage.artifacts`~~ — does not exist yet; this task creates it
- ~~`ChatStorage.save_artifact()`~~ — does not exist; artifact methods go on ArtifactStore
- ~~`ChatStorage.list_artifacts()`~~ — does not exist

---

## Implementation Notes

### Key Constraints
- `save_artifact` must call `S3OverflowManager.maybe_offload()` before writing
- `get_artifact` must call `S3OverflowManager.resolve()` to handle S3 refs
- `list_artifacts` returns `ArtifactSummary` (id, type, title, dates) — NOT full definitions
- `delete_artifact` must delete S3 object first (if exists), then DynamoDB item
- All methods receive `user_id`, `agent_id`, `session_id` — the ArtifactStore does NOT store these

---

## Acceptance Criteria

- [ ] `ArtifactStore` class exists in `parrot/storage/artifacts.py`
- [ ] `from parrot.storage import ArtifactStore` works
- [ ] Full CRUD cycle works: save → list → get → update → delete
- [ ] Large artifacts transparently use S3 overflow
- [ ] `list_artifacts` returns summaries without full definitions
- [ ] `delete_artifact` cleans up S3 objects
- [ ] Unit tests pass: `pytest tests/storage/test_artifact_store.py -v`

---

## Test Specification

```python
# tests/storage/test_artifact_store.py
import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator


@pytest.fixture
def mock_dynamo():
    return AsyncMock()

@pytest.fixture
def mock_overflow():
    overflow = AsyncMock()
    overflow.maybe_offload.return_value = ({"engine": "echarts"}, None)  # inline
    overflow.resolve.return_value = {"engine": "echarts"}
    return overflow

@pytest.fixture
def store(mock_dynamo, mock_overflow):
    return ArtifactStore(dynamodb=mock_dynamo, s3_overflow=mock_overflow)


class TestArtifactStore:
    @pytest.mark.asyncio
    async def test_save_artifact(self, store, mock_dynamo, mock_overflow):
        artifact = Artifact(
            artifact_id="chart-x1", artifact_type=ArtifactType.CHART,
            title="Test", created_at=datetime.now(), updated_at=datetime.now(),
            definition={"engine": "echarts"},
        )
        await store.save_artifact("u1", "agent1", "sess1", artifact)
        mock_overflow.maybe_offload.assert_called_once()
        mock_dynamo.put_artifact.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_artifact_resolves_s3(self, store, mock_dynamo, mock_overflow):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "infog-1", "artifact_type": "infographic",
            "definition": None, "definition_ref": "s3://bucket/key.json",
        }
        mock_overflow.resolve.return_value = {"blocks": []}
        result = await store.get_artifact("u1", "agent1", "sess1", "infog-1")
        mock_overflow.resolve.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_returns_summaries(self, store, mock_dynamo):
        mock_dynamo.query_artifacts.return_value = [
            {"artifact_id": "c1", "artifact_type": "chart", "title": "Chart 1",
             "created_at": "2025-04-16T00:00:00", "updated_at": "2025-04-16T00:00:00"},
        ]
        results = await store.list_artifacts("u1", "agent1", "sess1")
        assert len(results) >= 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** Section 2 (New Public Interfaces — ArtifactStore)
2. **Check dependencies** — TASK-717, TASK-718, TASK-719 must be completed
3. **Read** the completed TASK-718 and TASK-719 code to verify interfaces
4. **Update status** → `"in-progress"`
5. **Implement** ArtifactStore
6. **Run tests**: `pytest tests/storage/test_artifact_store.py -v`
7. **Move + update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
