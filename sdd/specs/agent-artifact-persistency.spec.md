# Feature Specification: Agent Artifact Persistency

**Feature ID**: FEAT-103
**Date**: 2025-04-16
**Author**: Jesus
**Status**: approved
**Target version**: 1.x
**Brainstorm**: `sdd/proposals/agent-artifact-persistency.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

Every interaction with an AI agent generates artifacts — charts, canvas tabs, infographics, DataFrames — that live exclusively in frontend memory and disappear on page reload. The backend has no concept of "artifact"; all rich content is ephemeral.

Additionally, the current cold-storage layer (DocumentDB) is both expensive (~$400/month for a db.r6g.large cluster) and architecturally mismatched: the access pattern is pure key-value (user+agent → threads, session_id → turns), but DocumentDB charges for a semi-relational query engine we never use.

### Goals

1. **Persist all conversation artifacts** (charts, canvas tabs, infographics, DataFrames, exports) in DynamoDB + S3, associated with their conversation thread.
2. **Replace DocumentDB cold storage** with DynamoDB for conversation threads and turns — the `ChatStorage` class swaps its `_docdb` backend.
3. **Provide REST API endpoints** for frontend artifact CRUD (save, load, update, delete).
4. **Maintain Redis hot cache** for LLM context — no changes to `ConversationMemory` / `RedisConversation`.
5. **Enable parallel frontend loading** — sidebar list, thread turns, and artifacts are three independent reads.
6. **Reduce infrastructure cost** by ~95% (DocumentDB $400/mo → DynamoDB ~$23/mo).

### Non-Goals (explicitly out of scope)

- Infrastructure provisioning (DynamoDB tables, S3 buckets, IAM roles) — assumed to exist.
- Cross-thread artifact references — all artifacts are scoped to a single thread.
- Artifact versioning — updates replace in-place, no undo history.
- Multi-user collaboration on canvas tabs — single-owner, future sharing = read-only copy.
- Artifact quotas — deferred to a future iteration.
- Migration of historical DocumentDB data — separate migration script, not part of this feature.
- Changes to the Redis hot-cache layer (`ConversationMemory`).

---

## 2. Architectural Design

### Overview

Replace the DocumentDB cold-storage backend in `ChatStorage` with a two-table DynamoDB design, and add a new `ArtifactStore` for artifact persistence. Both tables share the same partition key pattern (`USER#{user_id}#AGENT#{agent_id}`) and can be queried in parallel.

The two-table split is driven by the frontend's actual access pattern — three distinct reads, not one mega-read:

1. **Sidebar load** (page open): list conversation sessions → conversations table, thread metadata only.
2. **Thread load** (click): load last 10 turns → conversations table, turn items only.
3. **Artifacts load** (parallel with #2): load all artifacts → artifacts table.

### Component Diagram

```
Frontend (React/Svelte)
  │
  ├── GET /threads?agent_id=X ────────────────────────┐
  │                                                    │
  ├── GET /threads/{id} ──────────────────────┐        │
  │                                           │        │
  └── GET /threads/{id}/artifacts ──┐         │        │
                                    │         │        │
                              ┌─────┴─────────┴────────┴──────┐
                              │        API Layer (aiohttp)     │
                              │   ThreadView  ArtifactView     │
                              └──────┬──────────────┬──────────┘
                                     │              │
                          ┌──────────┴───┐   ┌──────┴──────────┐
                          │  ChatStorage  │   │  ArtifactStore  │
                          │  (modified)   │   │  (new)          │
                          └──────┬───────┘   └──────┬──────────┘
                                 │                   │
                    ┌────────────┴────────────────────┴─────────┐
                    │       ConversationDynamoDB (new)          │
                    │  domain wrapper: PK/SK + TTL + queries    │
                    └────────────────────┬─────────────────────┘
                                         │
                    ┌────────────────────┴─────────────────────┐
                    │   asyncdb dynamodb driver (existing)      │
                    │   AsyncDB("dynamodb", params={...})       │
                    │   get/set/query/update/delete/write_batch │
                    └────────┬──────────────────┬──────────────┘
                             │                  │
                ┌────────────┴──┐    ┌──────────┴──────────┐
                │  parrot-      │    │  parrot-artifacts   │
                │  conversations│    │  (DynamoDB table)   │
                │  (DynamoDB)   │    │                     │
                └───────────────┘    └─────────────────────┘
                                              │
                                     ┌────────┴────────┐
                                     │ S3Overflow      │
                                     │ Manager         │
                                     │ (> 200KB → S3)  │
                                     └────────┬────────┘
                                              │
                                     ┌────────┴────────┐
                                     │ S3 Bucket       │
                                     │ (parrot-        │
                                     │  artifacts)     │
                                     └─────────────────┘
```

### DynamoDB Table Design

**Table 1: `parrot-conversations`** (thread metadata + turns)

| PK | SK | Type | Content |
|---|---|---|---|
| `USER#u123#AGENT#bot` | `THREAD#sess-abc` | thread | Session metadata (title, updated_at, turn_count) |
| `USER#u123#AGENT#bot` | `THREAD#sess-abc#TURN#001` | turn | Individual turn (user_message, assistant_response, data, tools) |
| `USER#u123#AGENT#bot` | `THREAD#sess-abc#TURN#002` | turn | Individual turn |

**Table 2: `parrot-artifacts`**

| PK | SK | Type | Content |
|---|---|---|---|
| `USER#u123#AGENT#bot` | `THREAD#sess-abc#chart-x1` | artifact | Chart definition (ECharts/ChartJS spec) |
| `USER#u123#AGENT#bot` | `THREAD#sess-abc#canvas-main` | artifact | Canvas tab (blocks referencing turns and other artifacts) |
| `USER#u123#AGENT#bot` | `THREAD#sess-abc#infog-r1` | artifact | Infographic (`InfographicResponse` payload) |

### Access Patterns

| Operation | Table | Query | Returns |
|---|---|---|---|
| List conversations (sidebar) | conversations | `PK=..., SK begins_with "THREAD#", Filter: type="thread"` | `[{session_id, title, updated_at}]` |
| Load turns (on click) | conversations | `PK=..., SK begins_with "THREAD#sess#TURN#", Limit=10, ScanIndexForward=false` | Last 10 turns |
| Load artifacts (parallel) | artifacts | `PK=..., SK begins_with "THREAD#sess"` | All artifacts for session |
| Save turn | conversations | `PutItem` turn + `UpdateItem` thread metadata | Atomic |
| Save artifact | artifacts | `PutItem` | Atomic |
| Delete thread | both | `Query + BatchWriteItem` on each table (parallel) | Cascade delete |
| Get single artifact | artifacts | `GetItem(PK, SK)` | One artifact |
| Update artifact | artifacts | `PutItem` (replace) | Atomic |

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ChatStorage` (`parrot/storage/chat.py`) | modifies | Replace `_docdb` (DocumentDb) with `ConversationDynamoDB` |
| `ChatStorage.save_turn()` | modifies | Write to DynamoDB instead of DocumentDB |
| `ChatStorage.load_conversation()` | modifies | Query DynamoDB conversations table |
| `ChatStorage.list_user_conversations()` | modifies | Query DynamoDB conversations table (thread metadata only) |
| `ChatStorage.delete_conversation()` | modifies | Cascade delete from both tables |
| `S3FileManager` (`parrot/interfaces/file/s3.py`) | reuses | S3 overflow for large artifacts via `create_from_bytes()` |
| `AWSInterface` (`parrot/interfaces/aws.py`) | reuses | AWS credential management for DynamoDB client |
| `InfographicResponse` (`parrot/models/infographic.py`) | reuses | Serialized as infographic artifact definition |
| `AgentTalk` handler (`parrot/handlers/agent.py`) | extends | Wire artifact save after `ask()` response |
| `InfographicTalk` handler (`parrot/handlers/infographic.py`) | extends | Wire artifact save after `get_infographic()` |
| `AbstractBot` (`parrot/bots/abstract.py`) | extends | Add `save_conversation_artifact()` convenience method |
| `parrot/conf.py` | extends | Add `DYNAMODB_CONVERSATIONS_TABLE`, `DYNAMODB_ARTIFACTS_TABLE`, `DYNAMODB_REGION`, `S3_ARTIFACT_BUCKET` |

### Data Models

```python
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class ArtifactType(str, Enum):
    CHART = "chart"
    CANVAS = "canvas"
    INFOGRAPHIC = "infographic"
    DATAFRAME = "dataframe"
    EXPORT = "export"


class ArtifactCreator(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class ArtifactSummary(BaseModel):
    """Lightweight artifact reference for thread metadata."""
    id: str
    type: ArtifactType
    title: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class Artifact(BaseModel):
    """Full artifact with definition payload."""
    artifact_id: str
    artifact_type: ArtifactType
    title: str
    created_at: datetime
    updated_at: datetime
    source_turn_id: Optional[str] = None
    created_by: ArtifactCreator = ArtifactCreator.USER
    definition: Optional[Dict[str, Any]] = None
    definition_ref: Optional[str] = None  # S3 URI if overflow


class ThreadMetadata(BaseModel):
    """Conversation thread metadata."""
    session_id: str
    user_id: str
    agent_id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0
    pinned: bool = False
    archived: bool = False
    tags: List[str] = Field(default_factory=list)


class CanvasBlockType(str, Enum):
    MARKDOWN = "markdown"
    HEADING = "heading"
    CHART_REF = "chart_ref"
    DATA_TABLE = "data_table"
    AGENT_RESPONSE = "agent_response"
    INFOGRAPHIC_REF = "infographic_ref"
    NOTE = "note"
    CODE = "code"
    IMAGE = "image"
    DIVIDER = "divider"


class CanvasBlock(BaseModel):
    """Individual block within a canvas tab."""
    block_id: str
    block_type: CanvasBlockType
    content: Optional[str] = None
    artifact_ref: Optional[str] = None
    source_turn_id: Optional[str] = None
    display_options: Optional[Dict[str, Any]] = None
    position: int = 0


class CanvasDefinition(BaseModel):
    """Complete canvas tab artifact definition."""
    tab_id: str
    title: str
    blocks: List[CanvasBlock] = Field(default_factory=list)
    layout: str = "vertical"
    export_config: Optional[Dict[str, Any]] = None
```

### New Public Interfaces

```python
class ConversationDynamoDB:
    """Domain wrapper around asyncdb's dynamodb driver for conversation storage.

    Uses two asyncdb dynamodb driver instances — one per table.
    All low-level DynamoDB operations (serialization, pagination, retries)
    are handled by asyncdb. This class only adds PK/SK construction,
    TTL setting, and domain-specific query patterns.
    """

    def __init__(self, conversations_table: str, artifacts_table: str,
                 dynamo_params: dict): ...
        # dynamo_params passed to AsyncDB("dynamodb", params=dynamo_params)

    async def initialize(self) -> None:
        """Open asyncdb connections to both tables."""
        ...

    async def close(self) -> None:
        """Close both asyncdb connections."""
        ...

    # --- Conversations table (threads + turns) ---
    async def put_thread(self, user_id: str, agent_id: str, session_id: str,
                         metadata: dict) -> None: ...
    async def update_thread(self, user_id: str, agent_id: str, session_id: str,
                            **updates) -> None: ...
    async def query_threads(self, user_id: str, agent_id: str,
                            limit: int = 50) -> List[dict]: ...
    async def put_turn(self, user_id: str, agent_id: str, session_id: str,
                       turn_id: str, data: dict) -> None: ...
    async def query_turns(self, user_id: str, agent_id: str, session_id: str,
                          limit: int = 10, newest_first: bool = True) -> List[dict]: ...
    async def delete_thread_cascade(self, user_id: str, agent_id: str,
                                    session_id: str) -> int: ...

    # --- Artifacts table ---
    async def put_artifact(self, user_id: str, agent_id: str,
                           session_id: str, artifact_id: str, data: dict) -> None: ...
    async def get_artifact(self, user_id: str, agent_id: str,
                           session_id: str, artifact_id: str) -> Optional[dict]: ...
    async def query_artifacts(self, user_id: str, agent_id: str,
                              session_id: str) -> List[dict]: ...
    async def delete_artifact(self, user_id: str, agent_id: str,
                              session_id: str, artifact_id: str) -> None: ...
    async def delete_session_artifacts(self, user_id: str, agent_id: str,
                                       session_id: str) -> int: ...

    # --- Helpers ---
    @staticmethod
    def _build_pk(user_id: str, agent_id: str) -> str:
        return f"USER#{user_id}#AGENT#{agent_id}"

    @staticmethod
    def _ttl_epoch(updated_at: datetime, days: int = 180) -> int:
        return int((updated_at + timedelta(days=days)).timestamp())


class ArtifactStore:
    """Artifact CRUD operations against the artifacts DynamoDB table."""

    def __init__(self, dynamodb: ConversationDynamoDB,
                 s3_overflow: S3OverflowManager): ...

    async def save_artifact(self, user_id: str, agent_id: str, session_id: str,
                            artifact: Artifact) -> None: ...
    async def get_artifact(self, user_id: str, agent_id: str, session_id: str,
                           artifact_id: str) -> Optional[Artifact]: ...
    async def list_artifacts(self, user_id: str, agent_id: str,
                             session_id: str) -> List[ArtifactSummary]: ...
    async def update_artifact(self, user_id: str, agent_id: str, session_id: str,
                              artifact_id: str, definition: dict) -> None: ...
    async def delete_artifact(self, user_id: str, agent_id: str, session_id: str,
                              artifact_id: str) -> bool: ...


class S3OverflowManager:
    """Transparent large-item offloading to S3."""

    INLINE_THRESHOLD = 200 * 1024  # 200KB

    def __init__(self, s3_file_manager: S3FileManager, bucket: str): ...

    async def maybe_offload(self, data: dict, key_prefix: str) -> tuple[Optional[dict], Optional[str]]:
        """Returns (inline_data, None) or (None, s3_uri)."""
        ...

    async def resolve(self, definition: Optional[dict],
                      definition_ref: Optional[str]) -> dict:
        """Returns the actual definition, fetching from S3 if needed."""
        ...

    async def delete(self, definition_ref: Optional[str]) -> None:
        """Delete S3 object if ref exists."""
        ...
```

### REST API Endpoints

```
# Thread management (user_id from JWT)
GET    /api/v1/threads?agent_id=X                    → list threads (sidebar)
POST   /api/v1/threads                               → create thread
GET    /api/v1/threads/{session_id}                   → load thread (turns, limit=10)
PATCH  /api/v1/threads/{session_id}                   → update thread metadata (title, pinned, tags)
DELETE /api/v1/threads/{session_id}                   → delete thread + cascade

# Artifact CRUD
GET    /api/v1/threads/{session_id}/artifacts         → list artifacts for session
POST   /api/v1/threads/{session_id}/artifacts         → save new artifact
GET    /api/v1/threads/{session_id}/artifacts/{id}    → get artifact (full definition)
PUT    /api/v1/threads/{session_id}/artifacts/{id}    → update artifact definition
DELETE /api/v1/threads/{session_id}/artifacts/{id}    → delete artifact
```

---

## 3. Module Breakdown

### Module 1: Artifact & Thread Pydantic Models
- **Path**: `parrot/storage/models.py` (extend existing file)
- **Responsibility**: Define `ArtifactType`, `ArtifactCreator`, `ArtifactSummary`, `Artifact`, `ThreadMetadata`, `CanvasBlockType`, `CanvasBlock`, `CanvasDefinition` as Pydantic models. These models are used by all other modules.
- **Depends on**: None (pure data models)

### Module 2: DynamoDB Backend
- **Path**: `parrot/storage/dynamodb.py` (new file)
- **Responsibility**: Thin wrapper around `asyncdb`'s `dynamodb` driver. Provides conversation-domain methods (`put_thread`, `query_turns`, `put_artifact`, etc.) that construct PK/SK keys and call the underlying `asyncdb` driver methods (`set()`, `query()`, `get()`, `update()`, `delete()`, `write_batch()`). Handles TTL attribute setting and graceful degradation (warning on unreachable, no hard failure). Does NOT implement low-level DynamoDB protocol — that's `asyncdb`'s job.
- **Depends on**: `asyncdb` (`AsyncDB("dynamodb", params={...})`), `parrot/conf.py` (AWS credentials and table names)

### Module 3: S3 Overflow Manager
- **Path**: `parrot/storage/s3_overflow.py` (new file)
- **Responsibility**: Decide whether an artifact definition should be stored inline in DynamoDB (< 200KB) or offloaded to S3. Handles upload, download, and deletion of overflow objects. Uses existing `S3FileManager`.
- **Depends on**: Module 1 (models), `parrot/interfaces/file/s3.py` (`S3FileManager`)

### Module 4: ArtifactStore
- **Path**: `parrot/storage/artifacts.py` (new file)
- **Responsibility**: High-level artifact CRUD operations. Composes `DynamoDBBackend` (artifacts table) and `S3OverflowManager`. Handles serialization/deserialization of `Artifact` models to/from DynamoDB items.
- **Depends on**: Module 1 (models), Module 2 (DynamoDB backend), Module 3 (S3 overflow)

### Module 5: ChatStorage Migration
- **Path**: `parrot/storage/chat.py` (modify existing)
- **Responsibility**: Replace `DocumentDb` backend with `DynamoDBBackend` for conversations table. Modify `save_turn()`, `load_conversation()`, `list_user_conversations()`, `delete_conversation()`, `delete_turn()` to use DynamoDB instead of DocumentDB. The `initialize()` method creates the DynamoDB backend instead of connecting to DocumentDB. Redis hot-cache path remains unchanged.
- **Depends on**: Module 2 (DynamoDB backend), Module 1 (models)

### Module 6: Configuration
- **Path**: `parrot/conf.py` (extend existing)
- **Responsibility**: Add configuration variables for DynamoDB table names (`DYNAMODB_CONVERSATIONS_TABLE`, `DYNAMODB_ARTIFACTS_TABLE`), region (`DYNAMODB_REGION`), and S3 artifact bucket (`S3_ARTIFACT_BUCKET`). Add a `dynamodb` entry to `AWS_CREDENTIALS` if separate credentials are needed.
- **Depends on**: None

### Module 7: API Endpoints — Thread Views
- **Path**: `parrot/handlers/threads.py` (new file)
- **Responsibility**: aiohttp views for thread management: `GET /api/v1/threads` (list), `POST /api/v1/threads` (create), `GET /api/v1/threads/{session_id}` (load turns), `PATCH /api/v1/threads/{session_id}` (update metadata), `DELETE /api/v1/threads/{session_id}` (delete + cascade). Uses `ChatStorage` for thread/turn operations and `ArtifactStore` for cascade deletes.
- **Depends on**: Module 4 (ArtifactStore), Module 5 (ChatStorage)

### Module 8: API Endpoints — Artifact Views
- **Path**: `parrot/handlers/artifacts.py` (new file)
- **Responsibility**: aiohttp views for artifact CRUD: `GET/POST /api/v1/threads/{id}/artifacts`, `GET/PUT/DELETE /api/v1/threads/{id}/artifacts/{aid}`. Uses `ArtifactStore`.
- **Depends on**: Module 4 (ArtifactStore)

### Module 9: Handler Integration — Auto-Save Artifacts
- **Path**: `parrot/handlers/agent.py` and `parrot/handlers/infographic.py` (modify existing)
- **Responsibility**: After `ask()` returns data or `get_infographic()` returns an `InfographicResponse`, automatically save the result as an artifact via `ArtifactStore`. Fire-and-forget async (same pattern as current DocumentDB writes).
- **Depends on**: Module 4 (ArtifactStore), Module 1 (models)

### Module 10: Tests
- **Path**: `tests/storage/` (new directory)
- **Responsibility**: Unit tests for DynamoDB backend (mocked), ArtifactStore, S3OverflowManager, ChatStorage migration. Integration tests for API endpoints.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_dynamodb_backend_put_turn` | Module 2 | PutItem constructs correct PK/SK and attributes |
| `test_dynamodb_backend_query_threads` | Module 2 | Query with begins_with filter returns only thread metadata items |
| `test_dynamodb_backend_query_turns_limit` | Module 2 | Query with Limit=10, ScanIndexForward=false returns newest turns |
| `test_dynamodb_backend_graceful_degradation` | Module 2 | Connection failure logs warning, does not raise |
| `test_dynamodb_backend_delete_cascade` | Module 2 | BatchWriteItem deletes all items for a session |
| `test_s3_overflow_inline` | Module 3 | Data < 200KB returns inline dict with no S3 upload |
| `test_s3_overflow_offload` | Module 3 | Data >= 200KB uploads to S3 and returns URI |
| `test_s3_overflow_resolve_inline` | Module 3 | Resolve with definition returns definition as-is |
| `test_s3_overflow_resolve_s3` | Module 3 | Resolve with definition_ref downloads from S3 |
| `test_artifact_store_save` | Module 4 | Serializes Artifact model to DynamoDB item correctly |
| `test_artifact_store_get_with_s3` | Module 4 | Resolves S3 reference when loading artifact |
| `test_artifact_store_list` | Module 4 | Returns ArtifactSummary list without full definitions |
| `test_artifact_store_update` | Module 4 | Replaces definition in-place |
| `test_artifact_store_delete_with_s3` | Module 4 | Deletes both DynamoDB item and S3 object |
| `test_artifact_models_serialization` | Module 1 | Artifact, CanvasDefinition round-trip serialize/deserialize |
| `test_chat_storage_save_turn_dynamodb` | Module 5 | save_turn writes to DynamoDB instead of DocumentDB |
| `test_chat_storage_load_conversation` | Module 5 | load_conversation queries DynamoDB conversations table |
| `test_chat_storage_list_conversations` | Module 5 | list_user_conversations returns thread metadata only |
| `test_chat_storage_delete_cascade` | Module 5 | delete_conversation removes from both tables |
| `test_ttl_attribute_set` | Module 2 | Every PutItem sets TTL = updated_at + 6 months |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_conversation_lifecycle` | Create thread → add turns → list threads → load thread → delete thread |
| `test_artifact_lifecycle` | Save artifact → list → get (full) → update → delete |
| `test_infographic_auto_persist` | Call get_infographic() → verify artifact saved in artifacts table |
| `test_large_artifact_s3_overflow` | Save artifact > 200KB → verify S3 upload + DynamoDB ref |
| `test_thread_delete_cascade` | Delete thread with turns + artifacts → verify both tables cleaned |
| `test_graceful_degradation_dynamo_down` | DynamoDB unreachable → bot still works via Redis, warning logged |
| `test_api_thread_list` | GET /api/v1/threads returns lightweight metadata list |
| `test_api_artifact_crud` | POST/GET/PUT/DELETE artifact via API endpoints |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_artifact():
    return Artifact(
        artifact_id="chart-x1",
        artifact_type=ArtifactType.CHART,
        title="Revenue by Region",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        source_turn_id="001",
        created_by=ArtifactCreator.AGENT,
        definition={
            "engine": "echarts",
            "spec": {"xAxis": {"data": ["NA", "LATAM"]}, "series": [{"type": "bar", "data": [100, 200]}]}
        },
    )

@pytest.fixture
def sample_canvas():
    return Artifact(
        artifact_id="canvas-main",
        artifact_type=ArtifactType.CANVAS,
        title="Main",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        created_by=ArtifactCreator.USER,
        definition=CanvasDefinition(
            tab_id="main", title="Main",
            blocks=[
                CanvasBlock(block_id="blk-1", block_type=CanvasBlockType.MARKDOWN, content="## Title"),
                CanvasBlock(block_id="blk-2", block_type=CanvasBlockType.CHART_REF, artifact_ref="chart-x1"),
            ],
        ).model_dump(),
    )

@pytest.fixture
def mock_dynamodb():
    """Mocked aioboto3 DynamoDB resource for unit tests."""
    ...

@pytest.fixture
def mock_s3():
    """Mocked S3FileManager for overflow tests."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `ChatStorage.save_turn()` writes to DynamoDB conversations table (not DocumentDB)
- [ ] `ChatStorage.load_conversation()` reads from DynamoDB conversations table
- [ ] `ChatStorage.list_user_conversations()` returns thread metadata only (session_id, title, updated_at)
- [ ] `ChatStorage.delete_conversation()` cascade-deletes from both tables
- [ ] `ArtifactStore` supports full CRUD for all artifact types (chart, canvas, infographic, dataframe, export)
- [ ] Artifacts > 200KB are transparently offloaded to S3 with inline reference in DynamoDB
- [ ] S3 overflow resolution is transparent — `get_artifact()` returns full definition regardless of storage location
- [ ] `get_infographic()` auto-saves the `InfographicResponse` as an infographic artifact
- [ ] `ask()` auto-saves data results as turn data (with S3 overflow for large payloads)
- [ ] Frontend can POST/PUT artifact updates (user-edited infographics)
- [ ] REST API: `GET /api/v1/threads?agent_id=X` returns conversation list
- [ ] REST API: `GET /api/v1/threads/{id}` returns last 10 turns
- [ ] REST API: `GET /api/v1/threads/{id}/artifacts` returns artifacts for session
- [ ] REST API: full artifact CRUD (POST, GET, PUT, DELETE)
- [ ] Graceful degradation: DynamoDB unreachable → bot works via Redis, warning logged, no crash
- [ ] DynamoDB TTL attribute set to `updated_at + 6 months` on all items
- [ ] Thread deletion cleans up S3 objects referenced by `definition_ref`
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] No breaking changes to `ConversationMemory` / Redis hot-cache path

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# These imports have been confirmed to work:
from parrot.storage import ChatStorage, ChatMessage, Conversation  # parrot/storage/__init__.py:1-8
from parrot.storage.models import MessageRole, ToolCall, Source     # parrot/storage/models.py
from parrot.memory import ConversationMemory, ConversationHistory, ConversationTurn  # parrot/memory/__init__.py
from parrot.memory import RedisConversation                        # parrot/memory/__init__.py
from parrot.interfaces.file.s3 import S3FileManager                # parrot/interfaces/file/s3.py
from parrot.interfaces.aws import AWSInterface                     # parrot/interfaces/aws.py
from parrot.interfaces.documentdb import DocumentDb                # parrot/interfaces/documentdb.py
from parrot.models.infographic import InfographicResponse          # parrot/models/infographic.py
from navconfig.logging import logging                              # used by ChatStorage for logger

# asyncdb DynamoDB driver (installed, verified):
from asyncdb import AsyncDB                                        # asyncdb/__init__.py
# Usage: async with AsyncDB("dynamodb", params={...}) as db:
#            await db.set(table, item)
#            await db.get(table, key)
#            await db.query(table, KeyConditionExpression=..., ...)
#            await db.update(table, key, update_expression, expression_values)
#            await db.delete(table, key)
#            await db.write_batch(table, items)
```

### Existing Class Signatures

```python
# parrot/storage/chat.py:27
class ChatStorage:
    def __init__(self, redis_conversation=None, document_db=None):  # line 30
        self._redis = redis_conversation          # line 35 — Optional[RedisConversation]
        self._docdb = document_db                 # line 36 — Optional[DocumentDb]
        self._initialized = False                 # line 37
        self.logger = logging.getLogger("parrot.storage.ChatStorage")  # line 38

    async def initialize(self) -> None:           # line 44
    async def save_turn(self, *, turn_id, user_id, session_id, agent_id,
                        user_message, assistant_response, output=None,
                        output_mode=None, data=None, code=None,
                        model=None, provider=None, response_time_ms=None,
                        tool_calls=None, sources=None, metadata=None) -> str:  # line 126
    async def _save_to_documentdb(self, user_msg, assistant_msg,
                                  agent_id, now) -> None:            # line 243
    async def load_conversation(self, user_id, session_id,
                                agent_id=None, limit=50) -> List[Dict]:  # line 323
    async def list_user_conversations(self, user_id, agent_id=None,
                                      limit=50, since=None) -> List[Dict]:  # line 479
    async def create_conversation(self, user_id, session_id,
                                  agent_id, title="New Conversation"):  # line 510
    async def update_conversation_title(self, session_id, title) -> bool:  # line 545
    async def delete_conversation(self, user_id, session_id,
                                  agent_id=None) -> bool:            # line 572
    async def delete_turn(self, session_id, turn_id) -> bool:        # line 613
    async def get_context_for_agent(self, user_id, session_id,
                                    agent_id=None, max_turns=10,
                                    model="claude") -> List[Dict]:   # line 649
    async def close(self) -> None:                                   # line 109
```

```python
# parrot/storage/models.py:68
@dataclass
class ChatMessage:
    message_id: str        # line 74
    session_id: str        # line 75
    user_id: str           # line 76
    agent_id: str          # line 77
    role: str              # line 78 — MessageRole value
    content: str           # line 79
    timestamp: datetime    # line 80
    output: Optional[Any]  # line 82
    output_mode: Optional[str]  # line 83
    data: Optional[Any]    # line 84
    code: Optional[str]    # line 85
    model: Optional[str]   # line 86
    provider: Optional[str]  # line 87
    response_time_ms: Optional[int]  # line 88
    tool_calls: List[ToolCall]  # line 89
    sources: List[Source]  # line 90
    metadata: Dict[str, Any]  # line 91
    def to_dict(self) -> Dict[str, Any]:  # line 93
    @classmethod
    def from_dict(cls, data) -> "ChatMessage":  # line 117
```

```python
# parrot/storage/models.py:152
@dataclass
class Conversation:
    session_id: str        # line 159
    user_id: str           # line 160
    agent_id: str          # line 161
    title: Optional[str]   # line 162
    created_at: datetime   # line 163
    updated_at: datetime   # line 164
    message_count: int     # line 165
    last_user_message: Optional[str]  # line 166
    last_assistant_message: Optional[str]  # line 167
    model: Optional[str]   # line 168
    provider: Optional[str]  # line 169
    metadata: Dict[str, Any]  # line 170
    def to_dict(self) -> Dict[str, Any]:  # line 172
    @classmethod
    def from_dict(cls, data) -> "Conversation":  # line 194
```

```python
# parrot/memory/abstract.py:10
@dataclass
class ConversationTurn:
    turn_id: str; user_id: str; user_message: str; assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

```python
# parrot/memory/abstract.py:50
@dataclass
class ConversationHistory:
    session_id: str; user_id: str; chatbot_id: Optional[str] = None
    turns: List[ConversationTurn] = field(default_factory=list)
    created_at: datetime; updated_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
```

```python
# parrot/interfaces/file/s3.py:15
class S3FileManager:
    def __init__(self, bucket_name, aws_id='default', region_name=None,
                 prefix="", multipart_threshold=None, multipart_chunksize=None,
                 max_concurrency=None):  # line 15
    async def upload_file(self, local_path, remote_path, content_type=None):  # line 226
    async def download_file(self, remote_path, local_path):  # line 355
    async def create_from_bytes(self, data, remote_path, content_type=None):  # line 470
    async def get_file_url(self, remote_path, expires_in=3600):  # line 337
    async def delete_file(self, remote_path):  # line 417
```

```python
# parrot/interfaces/aws.py:22
class AWSInterface:
    # Uses AWS_CREDENTIALS dict from parrot.conf for credential resolution
    async def validate_credentials(self):  # line 121
    # Provides client() and resource() async context managers for AWS services
```

```python
# parrot/models/infographic.py:580
class InfographicResponse(BaseModel):
    template: Optional[str]
    theme: Optional[str]
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]]
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

```python
# asyncdb/drivers/dynamodb.py:62
class dynamodb(InitDriver, _KwargsTerminator):
    """AWS DynamoDB async driver from asyncdb framework."""
    _provider: str = "dynamodb"
    _syntax: str = "nosql"

    def __init__(self, loop=None, params=None, **kwargs):  # line 84
        # params: aws_access_key_id, aws_secret_access_key, region_name,
        #         endpoint_url, aws_session_token, profile_name, table

    async def connection(self, **kwargs) -> "dynamodb":  # line 146
    async def close(self, timeout=10) -> None:           # line 177

    # CRUD
    async def get(self, table=None, key=None, **kwargs) -> Optional[dict]:  # line 343
    async def set(self, table=None, item=None, **kwargs) -> bool:           # line 376
    async def write(self, table=None, item=None, **kwargs) -> bool:         # line 433 (alias for set)
    async def delete(self, table=None, key=None, **kwargs) -> bool:         # line 405
    async def update(self, table=None, key=None, update_expression=None,
                     expression_values=None, **kwargs) -> Optional[dict]:   # line 446

    # Query & Scan
    async def query(self, table=None, **kwargs) -> Optional[list[dict]]:    # line 501
    async def queryrow(self, table=None, **kwargs) -> Optional[dict]:       # line 524
    async def fetch_all(self, table=None, **kwargs) -> list[dict]:          # line 542 (scan)

    # Batch
    async def write_batch(self, table=None, items=None, **kwargs) -> bool:  # line 734
    async def get_batch(self, table=None, keys=None, **kwargs) -> list[dict]:  # line 788

    # Serialization (automatic — PutItem/GetItem serialize/deserialize transparently)
    def _serialize(self, item: dict) -> dict:     # line 229
    def _deserialize(self, item: dict) -> dict:   # line 240

    # Auto-pagination for query/scan
    async def _paginate_query(self, method, table, **kwargs) -> list[dict]:  # line 287
```

```python
# parrot/interfaces/documentdb.py:63
class DocumentDb:
    async def write(self, collection, data): ...
    async def read(self, collection, query): ...
    async def find_documents(self, collection, query, sort=None, limit=None): ...
    async def update_one(self, collection, filter, update): ...
    async def delete_many(self, collection, filter): ...
    async def create_indexes(self, collection, indexes): ...
    async def documentdb_connect(self): ...
```

```python
# parrot/conf.py:380-412
AWS_CREDENTIALS = {
    'default': {
        'bucket_name': aws_bucket,   # from AWS_BUCKET env var
        'aws_key': AWS_ACCESS_KEY,
        'aws_secret': AWS_SECRET_KEY,
        'region_name': AWS_REGION_NAME,
    },
}
# Relevant env vars: AWS_REGION, AWS_BUCKET, AWS_KEY, AWS_SECRET,
# AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION_NAME
```

```python
# parrot/bots/abstract.py:106
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin,
                  ToolInterface, VectorInterface, ABC):
    conversation_memory: Optional[ConversationMemory]  # line 332
    async def ask(self, question, session_id=None, user_id=None, ...):  # line 2531
    async def get_infographic(self, question, template=None, theme=None, ...):  # line 2644
```

### Key Constants

- `CONVERSATIONS_COLLECTION = "chat_conversations"` — parrot/storage/chat.py:18
- `MESSAGES_COLLECTION = "chat_messages"` — parrot/storage/chat.py:19
- `HOT_TTL_HOURS = 48` — parrot/storage/chat.py:22
- `DEFAULT_LIST_LIMIT = 50` — parrot/storage/chat.py:23
- `DEFAULT_CONTEXT_TURNS = 10` — parrot/storage/chat.py:24

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ConversationDynamoDB` | `asyncdb.AsyncDB("dynamodb")` | DynamoDB driver | `asyncdb/drivers/dynamodb.py:62` |
| `S3OverflowManager` | `S3FileManager.create_from_bytes()` | Upload large artifacts | `parrot/interfaces/file/s3.py:470` |
| `S3OverflowManager` | `S3FileManager.download_file()` | Download for resolve | `parrot/interfaces/file/s3.py:355` |
| `S3OverflowManager` | `S3FileManager.delete_file()` | Cleanup on artifact delete | `parrot/interfaces/file/s3.py:417` |
| `ChatStorage` (modified) | `ConversationDynamoDB` | Replaces `self._docdb` | `parrot/storage/chat.py:36` |
| `ArtifactStore` | `ConversationDynamoDB` | Artifact CRUD on artifacts table | New |
| Handler integration | `ArtifactStore.save_artifact()` | Auto-save after ask/get_infographic | New |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.storage.dynamodb`~~ — no DynamoDB module exists; must be created as Module 2 (wraps `asyncdb`'s driver)
- ~~`parrot.storage.artifacts`~~ — no artifact store exists; must be created as Module 4
- ~~`parrot.storage.s3_overflow`~~ — no overflow manager exists; must be created as Module 3
- ~~`parrot.storage.ConversationStore`~~ — no abstract store class; `ChatStorage` is concrete
- ~~`parrot.interfaces.dynamodb`~~ — do NOT create a DynamoDB interface here; use `asyncdb`'s built-in driver instead
- ~~`parrot.storage.models.Artifact`~~ — no artifact model exists; must be created in Module 1
- ~~`parrot.storage.models.ThreadMetadata`~~ — `Conversation` dataclass exists but is NOT the same; new Pydantic model needed
- ~~`ChatStorage.save_artifact()`~~ — does not exist; artifact methods go on `ArtifactStore`
- ~~`ChatStorage.list_artifacts()`~~ — does not exist
- ~~`AbstractBot.conversation_store`~~ — no such attribute
- ~~`AbstractBot.save_conversation_artifact()`~~ — does not exist
- ~~`parrot.handlers.ThreadListView`~~ — no thread/artifact views exist; must be created
- ~~`parrot.handlers.threads`~~ — module does not exist; must be created as Module 7
- ~~`parrot.handlers.artifacts`~~ — module does not exist; must be created as Module 8
- ~~`parrot.conf.DYNAMODB_CONVERSATIONS_TABLE`~~ — no DynamoDB config exists; must be added in Module 6
- ~~`S3FileManager.create_from_json()`~~ — does not exist; use `create_from_bytes()` with JSON bytes
- ~~`S3FileManager.download_to_bytes()`~~ — does not exist; `download_file()` writes to disk

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Use `asyncdb` driver**: all DynamoDB operations go through `AsyncDB("dynamodb", params={...})`. Do NOT use `aioboto3` or `boto3` directly — `asyncdb` handles serialization, deserialization, pagination, and retries.
- **Pydantic models**: all new data structures as Pydantic `BaseModel` (not dataclasses). Existing `ChatMessage` and `Conversation` dataclasses remain unchanged to avoid breaking changes.
- **Graceful degradation**: wrap all DynamoDB calls in try/except. On failure, log warning via `self.logger.warning()`, return empty/None. Never raise to the caller for persistence failures. Catch `asyncdb.exceptions.DriverError` and `asyncdb.exceptions.ConnectionTimeout`.
- **Fire-and-forget writes**: follow the existing pattern in `ChatStorage.save_turn()` — DynamoDB writes are `asyncio.create_task()` background tasks, not awaited in the request path.
- **S3 overflow**: write S3 first, then DynamoDB. If DynamoDB fails after S3 succeeds, the orphaned S3 object is cleaned up by lifecycle policy.
- **PK construction**: `f"USER#{user_id}#AGENT#{agent_id}"` — always derived from the same two identifiers.
- **TTL**: every `PutItem` (via `db.set()`) sets a `ttl` attribute = `int(updated_at + timedelta(days=180).timestamp())`.
- **asyncdb query pattern**: use `db.query(table, KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)", ExpressionAttributeValues={":pk": pk, ":prefix": prefix})`. The driver handles serialization of expression values automatically.

### Known Risks / Gotchas

1. **DynamoDB 400KB item limit**: Mitigated by S3 overflow at 200KB threshold. Turn `data` fields (DataFrame results) must also go through overflow check.
2. **S3 object orphaning**: If DynamoDB write fails after S3 upload, orphaned objects accumulate. Mitigated by S3 lifecycle policy (auto-delete after 7 months — 1 month past the 6-month TTL).
3. **Thread listing FilterExpression**: The `type="thread"` filter on `list_user_conversations` consumes RCUs for turn items even though they're discarded. For high-turn-count users, consider a GSI with `type` as SK. Defer to v2 if not a bottleneck.
4. **Concurrent artifact updates**: Last-writer-wins (no optimistic locking). Acceptable because artifacts are single-user, no collaboration.
5. **Canvas block references to deleted artifacts**: If an artifact is deleted (via API or TTL) but a canvas still references it, the frontend must handle missing references gracefully (show placeholder).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb[boto3]` | installed | Provides `dynamodb` driver with auto-serialization, pagination, batch ops — already a core dependency |
| `aiobotocore` | transitive | Required by asyncdb's dynamodb driver — transitive dependency |
| `pydantic` | `>=2.0` | Data models — already a core dependency |

### Graceful Degradation Detail

```python
from asyncdb.exceptions import DriverError, ConnectionTimeout

# Pattern for all DynamoDB operations:
async def _save_to_dynamodb(self, ...):
    try:
        await self._dynamo.set(
            table=self._conversations_table,
            item=item,
        )
    except (DriverError, ConnectionTimeout, Exception) as exc:
        self.logger.warning(
            "DynamoDB write failed for session %s: %s",
            session_id, exc
        )
        # Do NOT re-raise — bot continues working via Redis
```

---

## 8. Open Questions

- [ ] **S3 compression** — Should overflow objects use gzip? JSON artifacts compress 5-10x, but adds CPU on decompress. Decision: defer, start uncompressed. — *Owner: Jesus*
- [ ] **Chart engine versioning** — Store ECharts/ChartJS version in chart artifact definition? Low effort, prevents future compat issues. Recommendation: include `engine` + `version` fields. — *Owner: Jesus*
- [ ] **Data deduplication** — Charts referencing the same turn's DataFrame: duplicate data or reference-by-turn-id? Recommendation: reference-by-turn-id in chart spec, frontend resolves. — *Owner: Jesus*
- [ ] **PandasAgent auto-artifact** — Should `ask()` auto-create dataframe artifacts, or only on user action? Risk of clutter. Recommendation: auto-save turn data (already happens), but don't create a separate dataframe artifact unless user pins it. — *Owner: Jesus*
- [x] **DynamoDB on-demand vs provisioned** — On-demand for v1, revisit at scale. — *Owner: Jesus*: will be provisioned.
- [x] **Thread list filter efficiency** — `FilterExpression: type="thread"` wastes RCUs on turn items. Monitor and add GSI if needed. — *Owner: Jesus*: I'm open to suggestions.

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: The dependency chain is linear (models → backend → overflow → artifact store → ChatStorage migration → handlers → API). Parallel worktrees would cause merge conflicts on shared files (`parrot/storage/models.py`, `parrot/storage/chat.py`, `parrot/storage/__init__.py`).
- **Cross-feature dependencies**: None. No in-flight specs touch `parrot/storage/` or `parrot/handlers/agent.py`.
- **Recommended worktree creation**:
  ```bash
  git worktree add -b feat-103-agent-artifact-persistency \
    .claude/worktrees/feat-103-agent-artifact-persistency HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2025-04-16 | Jesus | Initial draft from brainstorm |
