# TASK-717: Artifact & Thread Pydantic Models

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-103. All other tasks depend on these models for serialization, deserialization, and type safety. Implements spec Module 1.

The models define the shape of every artifact type (chart, canvas, infographic, dataframe, export) and the thread metadata structure used by DynamoDB items.

---

## Scope

- Add the following Pydantic models to `parrot/storage/models.py`:
  - `ArtifactType` enum (chart, canvas, infographic, dataframe, export)
  - `ArtifactCreator` enum (user, agent, system)
  - `ArtifactSummary` — lightweight artifact reference for thread metadata
  - `Artifact` — full artifact with definition payload and optional S3 reference
  - `ThreadMetadata` — conversation thread metadata (replaces the role of `Conversation` dataclass for DynamoDB)
  - `CanvasBlockType` enum (markdown, heading, chart_ref, data_table, agent_response, infographic_ref, note, code, image, divider)
  - `CanvasBlock` — individual block within a canvas tab
  - `CanvasDefinition` — complete canvas tab artifact definition
- Update `parrot/storage/__init__.py` to export the new models
- Write unit tests for serialization/deserialization round-trips

**NOT in scope**: DynamoDB backend, S3 overflow, API endpoints, handler integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/models.py` | MODIFY | Add new Pydantic models after existing dataclass definitions |
| `parrot/storage/__init__.py` | MODIFY | Export new model classes |
| `tests/storage/test_artifact_models.py` | CREATE | Unit tests for model serialization |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage.models import MessageRole, ToolCall, Source     # parrot/storage/models.py
from parrot.storage.models import ChatMessage, Conversation         # parrot/storage/models.py
from parrot.storage import ChatStorage, ChatMessage, Conversation   # parrot/storage/__init__.py:1-8
```

### Existing Signatures to Use
```python
# parrot/storage/models.py:12
class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

# parrot/storage/models.py:68
@dataclass
class ChatMessage:
    message_id: str        # line 74
    session_id: str        # line 75
    # ... (full definition in spec Section 6)

# parrot/storage/models.py:152
@dataclass
class Conversation:
    session_id: str        # line 159
    user_id: str           # line 160
    agent_id: str          # line 161
    title: Optional[str]   # line 162
    # ... (full definition in spec Section 6)

# parrot/storage/__init__.py:1-8
from .chat import ChatStorage
from .models import ChatMessage, Conversation

__all__ = [
    "ChatStorage",
    "ChatMessage",
    "Conversation",
]
```

### Does NOT Exist
- ~~`parrot.storage.models.Artifact`~~ — does not exist yet; this task creates it
- ~~`parrot.storage.models.ThreadMetadata`~~ — does not exist; the existing `Conversation` dataclass is NOT the same
- ~~`parrot.storage.models.ArtifactType`~~ — does not exist yet
- ~~`parrot.storage.models.CanvasDefinition`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
The existing models in `parrot/storage/models.py` use `@dataclass` with manual `to_dict()`/`from_dict()`. The NEW models should use **Pydantic `BaseModel`** instead (per spec requirements). Both can coexist in the same file — do NOT convert existing dataclasses.

```python
# Existing pattern (dataclass) — DO NOT change these:
@dataclass
class ChatMessage:
    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data) -> "ChatMessage": ...

# New pattern (Pydantic) — use this for all new models:
class Artifact(BaseModel):
    artifact_id: str
    artifact_type: ArtifactType
    # Pydantic handles serialization via .model_dump() / .model_validate()
```

### Key Constraints
- All new models MUST be Pydantic `BaseModel` subclasses
- Enums MUST inherit from `(str, Enum)` for JSON serialization
- `Artifact.definition` is `Optional[Dict[str, Any]]` — it can be None when `definition_ref` points to S3
- `ThreadMetadata` is a NEW model — it does NOT replace `Conversation` dataclass
- Preserve all existing code in `models.py` — add new models at the end

---

## Acceptance Criteria

- [ ] All 8 new models/enums exist in `parrot/storage/models.py`
- [ ] `from parrot.storage import Artifact, ArtifactType, ThreadMetadata, CanvasDefinition` works
- [ ] `Artifact.model_dump()` produces a JSON-serializable dict
- [ ] `Artifact.model_validate(data)` reconstructs from dict
- [ ] `CanvasDefinition` with nested `CanvasBlock` list round-trips correctly
- [ ] Existing `ChatMessage` and `Conversation` dataclasses still work unchanged
- [ ] Unit tests pass: `pytest tests/storage/test_artifact_models.py -v`

---

## Test Specification

```python
# tests/storage/test_artifact_models.py
import pytest
from datetime import datetime
from parrot.storage.models import (
    ArtifactType, ArtifactCreator, ArtifactSummary, Artifact,
    ThreadMetadata, CanvasBlockType, CanvasBlock, CanvasDefinition,
)


class TestArtifactModels:
    def test_artifact_type_enum(self):
        assert ArtifactType.CHART == "chart"
        assert ArtifactType.INFOGRAPHIC == "infographic"

    def test_artifact_roundtrip(self):
        artifact = Artifact(
            artifact_id="chart-x1",
            artifact_type=ArtifactType.CHART,
            title="Test Chart",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            definition={"engine": "echarts", "spec": {}},
        )
        data = artifact.model_dump()
        restored = Artifact.model_validate(data)
        assert restored.artifact_id == "chart-x1"
        assert restored.artifact_type == ArtifactType.CHART

    def test_artifact_with_s3_ref(self):
        artifact = Artifact(
            artifact_id="infog-r1",
            artifact_type=ArtifactType.INFOGRAPHIC,
            title="Big Infographic",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            definition=None,
            definition_ref="s3://parrot-artifacts/USER#u1/sess/infog.json",
        )
        assert artifact.definition is None
        assert artifact.definition_ref is not None

    def test_canvas_definition_roundtrip(self):
        canvas = CanvasDefinition(
            tab_id="main",
            title="Main",
            blocks=[
                CanvasBlock(block_id="b1", block_type=CanvasBlockType.MARKDOWN, content="# Hello"),
                CanvasBlock(block_id="b2", block_type=CanvasBlockType.CHART_REF, artifact_ref="chart-x1"),
            ],
        )
        data = canvas.model_dump()
        restored = CanvasDefinition.model_validate(data)
        assert len(restored.blocks) == 2
        assert restored.blocks[0].block_type == CanvasBlockType.MARKDOWN

    def test_thread_metadata(self):
        meta = ThreadMetadata(
            session_id="sess-abc",
            user_id="u123",
            agent_id="sales-bot",
            title="Test Thread",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        data = meta.model_dump()
        assert data["session_id"] == "sess-abc"
        assert data["turn_count"] == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-artifact-persistency.spec.md` Section 2 (Data Models)
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — read `parrot/storage/models.py` and `parrot/storage/__init__.py`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the models at the end of `models.py`, update `__init__.py`
6. **Run tests**: `pytest tests/storage/test_artifact_models.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
