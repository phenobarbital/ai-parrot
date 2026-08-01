# TASK-2046: Checkpoint data models + error types

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of the new checkpoint plane (spec §2 Data Models, §3 Module 1).
Every other FEAT-399 task consumes these models: `FlowCheckpoint` is the unit
stored by every `CheckpointStore`, assembled by `FlowCheckpointer`, and loaded
by `AgentsFlow.resume()`.

---

## Scope

- Create package `parrot/bots/flows/core/checkpoint/` with `__init__.py`.
- Implement `model.py` with Pydantic v2 models exactly as spec §2 Data Models:
  `MemoryRefs`, `NodeStateSnapshot`, `ContextSnapshot`, `FlowCheckpoint`.
- Implement `errors.py`: `FlowLockedError(RuntimeError)`,
  `CheckpointNotFoundError(LookupError)`, `FlowNotExportableError(ValueError)`.
- Re-export all public names from `checkpoint/__init__.py`.
- Write unit tests (model round-trip incl. embedded `FlowDefinition`).

**NOT in scope**: serialization to ormsgpack (TASK-2047), any store
(TASK-2048/2049/2050), `FlowContext.to_snapshot()` (TASK-2052).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py` | CREATE | Package init, re-exports |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py` | CREATE | Pydantic checkpoint models |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/errors.py` | CREATE | Error types |
| `packages/ai-parrot/tests/flows/checkpoint/test_checkpoint_model.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.flow.definition import FlowDefinition  # verified: flow/definition.py:296
from pydantic import BaseModel, Field                          # pydantic v2, project-wide
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/definition.py
class FlowDefinition(BaseModel): ...   # line 296 — full JSON round-trip
                                       # (model_validate / model_dump_json(by_alias=True))
```

`FlowCheckpoint.status` is `Literal["running", "suspended", "completed", "failed"]`.
`ContextSnapshot.errors` is `dict[str, dict[str, str]]` — node_id →
`{type, message, repr}` (spec §7: FlowContext holds live Exceptions; we store
structured dicts, never Exception instances).

### Does NOT Exist
- ~~`parrot/bots/flows/core/checkpoint/`~~ — this task creates it; nothing to import from it yet.
- ~~`FlowCheckpoint`, `ContextSnapshot`, `NodeStateSnapshot`, `MemoryRefs`, `FlowLockedError`, `CheckpointNotFoundError`, `FlowNotExportableError`~~ — all introduced HERE.
- ~~`parrot.bots.flows.core.checkpoint.serializer`~~ — TASK-2047, do not stub it.

---

## Implementation Notes

### Pattern to Follow
Model style mirrors `flow/definition.py` (Pydantic v2 `BaseModel` + `Field`
with descriptions, `model_validator` only where needed). Keep models pure
data — no I/O, no logging.

### Key Constraints
- Pydantic v2 only; strict type hints; Google-style docstrings.
- `FlowCheckpoint.definition: FlowDefinition` embeds the graph snapshot
  (do NOT store a path or hash — spec §2).
- `checkpoint_id: int` monotonic per flow; `parent_checkpoint_id: Optional[int]`.
- `lossy: bool = False` flag (set by the serializer in TASK-2047).
- `ContextSnapshot.responses: Optional[dict[str, Any]] = None` — only
  populated when `checkpoint_include_responses=True` (spec resolved OQ2).

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.core.checkpoint import FlowCheckpoint, ContextSnapshot, NodeStateSnapshot, MemoryRefs, FlowLockedError, CheckpointNotFoundError, FlowNotExportableError` works.
- [ ] `FlowCheckpoint.model_validate(cp.model_dump())` round-trips, including the embedded `FlowDefinition`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/checkpoint/test_checkpoint_model.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/checkpoint/test_checkpoint_model.py
from parrot.bots.flows.core.checkpoint import FlowCheckpoint

def test_flow_checkpoint_model_roundtrip(linear_flow_definition):
    cp = FlowCheckpoint(
        flow_id="f1", flow_name="demo", checkpoint_id=1,
        created_at=..., status="running",
        definition=linear_flow_definition,
        context=..., node_states=[], memory_refs=...,
    )
    assert FlowCheckpoint.model_validate(cp.model_dump()) == cp

def test_status_literal_rejects_unknown():
    ...  # status="paused" → ValidationError

def test_errors_are_structured_dicts():
    ...  # ContextSnapshot.errors values are {type, message, repr} strings
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Created `parrot/bots/flows/core/checkpoint/` with `model.py`
(`MemoryRefs`, `NodeStateSnapshot`, `ContextSnapshot`, `FlowCheckpoint`),
`errors.py` (`FlowLockedError`, `CheckpointNotFoundError`,
`FlowNotExportableError`), and `__init__.py` re-exporting all seven names.
Added `tests/flows/checkpoint/test_checkpoint_model.py` with 6 tests
covering model round-trip (incl. embedded `FlowDefinition`), the `status`
Literal rejecting unknown values, structured `errors` dicts, defaults, and
the three error types' base classes. All 6 tests pass; `ruff check` clean.

**Deviations from spec**: none
