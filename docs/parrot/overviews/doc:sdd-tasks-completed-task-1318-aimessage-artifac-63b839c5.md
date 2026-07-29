---
type: Wiki Overview
title: 'TASK-1318: Add `AIMessage.artifact_id` top-level field'
id: doc:sdd-tasks-completed-task-1318-aimessage-artifact-id-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 6 from the spec. `AIMessage` currently carries a generic
relates_to:
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1318: Add `AIMessage.artifact_id` top-level field

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 6)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Parallel**: true
**Assigned-to**: unassigned

---

## Context

Module 6 from the spec. `AIMessage` currently carries a generic
`artifacts: List[Dict[str, Any]]` (line 206) plus an `add_artifact()` helper
(line 271). The infographic flow needs a **dedicated top-level field** that
carries the single rendered artifact's ID so downstream consumers
(PandasAgent post-loop in TASK-1326, HTTP formatter in TASK-1320) can route
on it without rummaging through the generic list. This was Q13 in the
brainstorm (resolved Round 1).

---

## Scope

- Add `artifact_id: Optional[str] = None` to `AIMessage` as a top-level
  field, placed alongside the other identifier-style fields (near `model`,
  `provider`).
- Verify Pydantic v2 model_dump / model_validate round-trip.
- Add unit tests proving the field defaults to `None` and round-trips.

**NOT in scope**:
- Modifying the existing `artifacts: List[Dict[str, Any]]` field.
- Modifying `add_artifact()` helper.
- Wiring `artifact_id` into any producer (PandasAgent, toolkit) — those
  live in TASK-1326 / TASK-1323.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | Add `artifact_id: Optional[str] = None` to `AIMessage`. |
| `packages/ai-parrot/tests/unit/models/test_aimessage_artifact_id.py` | CREATE | Unit tests for the new field. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.responses import AIMessage
# verified: packages/ai-parrot/src/parrot/models/responses.py:72
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                          # line 72
    input: str
    output: Any
    response: Optional[str] = None
    data: Optional[Any] = None
    code: Optional[str] = None
    images: Optional[List[Path]] = Field(default_factory=list)
    media: Optional[List[Path]] = Field(default_factory=list)
    files: Optional[List[Path]] = Field(default_factory=list)
    documents: Optional[List[Any]] = Field(default_factory=list)
    model: str
    provider: str
    usage: CompletionUsage
    # ...
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)    # line 206
    def add_artifact(self, artifact_type: str, content: Any, **metadata) -> None: ...  # line 271
```

### Does NOT Exist
- ~~`AIMessage.artifact_id`~~ — created by this task.
- ~~`AIMessage.artifact`~~ (singular) — do NOT add; the field name MUST be
  `artifact_id`.

---

## Implementation Notes

### Pattern to Follow

Place `artifact_id` next to `model`/`provider` so it groups with the other
top-level identifier-style scalars rather than near the bulky `artifacts:
List[Dict]` field:

```python
class AIMessage(BaseModel):
    # ... existing fields ...
    model: str
    provider: str
    usage: CompletionUsage
    artifact_id: Optional[str] = None  # NEW (FEAT-197)
    # ... rest ...
```

### Key Constraints
- Must default to `None` — existing producers don't set it.
- Use Pydantic v2 `Optional[str]` — no `model_validator` needed.
- DO NOT touch `artifacts: List[Dict[str, Any]]` or `add_artifact()`.

---

## Acceptance Criteria

- [ ] `AIMessage(artifact_id=None)` validates.
- [ ] `AIMessage(artifact_id="abc-123")` validates.
- [ ] `AIMessage(...).model_dump()['artifact_id']` is `None` by default.
- [ ] `AIMessage.model_validate(json.loads(msg.model_dump_json()))` round-trips
      `artifact_id`.
- [ ] Existing `artifacts: List[Dict]` field is independent and unchanged.
- [ ] `pytest packages/ai-parrot/tests/unit/models/test_aimessage_artifact_id.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/models/responses.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/models/test_aimessage_artifact_id.py
import json
import pytest
from parrot.models.responses import AIMessage


def _minimal_kwargs():
    return dict(input="q", output="a", model="m", provider="p",
                usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})


class TestAIMessageArtifactId:
    def test_artifact_id_defaults_to_none(self):
        msg = AIMessage(**_minimal_kwargs())
        assert msg.artifact_id is None

    def test_artifact_id_round_trips(self):
        msg = AIMessage(**_minimal_kwargs(), artifact_id="art-001")
        dumped = json.loads(msg.model_dump_json())
        restored = AIMessage.model_validate(dumped)
        assert restored.artifact_id == "art-001"

    def test_artifact_id_independent_of_artifacts_list(self):
        msg = AIMessage(**_minimal_kwargs(), artifact_id="art-001")
        assert msg.artifacts == []  # untouched
        msg.add_artifact("dataset", {"foo": "bar"})
        assert msg.artifact_id == "art-001"
        assert len(msg.artifacts) == 1
```

---

## Agent Instructions

1. Read `packages/ai-parrot/src/parrot/models/responses.py` to see the
   current `AIMessage` shape.
2. Add the field, then run the new test file.
3. Run `pytest packages/ai-parrot/tests/unit/models/ -v` to make sure no
   adjacent tests broke.
4. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*
