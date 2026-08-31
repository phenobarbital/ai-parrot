# TASK-2623: Checkpoint Input Metadata, Error Types, and Awaited Persistence

**Feature**: FEAT-480 — Dev Flow Node Checkpoint Recovery
**Spec**: `sdd/specs/dev-flow-node-caching.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2622
**Assigned-to**: unassigned

---

## Context

Implements the data/persistence half of spec §3 Module 2. Checkpoint writes
today go through the fire-and-forget listener produced by
`FlowCheckpointer.make_listener()` (`checkpointer.py:207`), whose failures are
deliberately swallowed. Required mode needs (a) an awaited `checkpoint()` call
that propagates encode/persist errors, (b) immutable input-fingerprint
metadata on `FlowCheckpoint`, (c) explicit error types, and (d) support for an
externally supplied declarative definition plus an allowlisted shared-data
projector — explicit graphs with callable predicates fail `to_definition()`
(`flow.py:652`), so the checkpointer must not derive the definition itself.

---

## Scope

- Add `CheckpointInputMetadata(BaseModel)` (spec §2 Data Models: `workflow:
  Literal["dev-loop","dev-flow"]`, `topology_version: str`,
  `input_fingerprint: str`) and optional `input_metadata` field on
  `FlowCheckpoint` (default `None` — existing checkpoints stay valid).
- Create `checkpoint/errors.py` with `CheckpointPersistenceError(RuntimeError)`
  and `CheckpointFingerprintMismatchError(RuntimeError)`; export both.
- Add `async FlowCheckpointer.checkpoint(ctx, *, status="running") ->
  FlowCheckpoint`: builds one snapshot and awaits `CheckpointStore.put()`,
  raising `CheckpointPersistenceError` on encoding/connection/write failure.
  The existing listener path stays best-effort and unchanged.
- Accept an external `checkpoint_definition: FlowDefinition` and an optional
  `checkpoint_shared_data: Callable[[FlowContext], dict[str, Any]]` projector
  on `AgentsFlow.__init__` / `_ensure_checkpointer()` (`flow.py:1276`) so
  explicit graphs never call `to_definition()` and never persist the full live
  `shared_data` mapping.
- Add `expected_input: CheckpointInputMetadata | None` to `resume()`: a loaded
  checkpoint whose `input_metadata` mismatches raises
  `CheckpointFingerprintMismatchError`.
- Unit tests for awaited failure propagation, metadata round-trip, mismatch
  rejection, and unchanged best-effort default.

**NOT in scope**: scheduler barrier placement and retry reset (TASK-2624),
fingerprint *computation* (TASK-2625 — the digest algorithm lives in the dev
adapter; this task only carries the value).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py` | MODIFY | `CheckpointInputMetadata`, `FlowCheckpoint.input_metadata` |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/errors.py` | CREATE | Explicit failure types |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py` | MODIFY | Awaited `checkpoint()`; keep listener best-effort |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py` | MODIFY | Export new names |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `checkpoint_definition` / `checkpoint_shared_data` / `checkpoint_input` params; `expected_input` on resume |
| `packages/ai-parrot/tests/flows/checkpoint/test_required_persistence.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.checkpoint import (
    CheckpointStore,
    FlowCheckpoint,
    FlowCheckpointer,
    FlowStateSerializer,
    RedisCheckpointStore,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py:7
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py:49
class FlowCheckpointer:
    def make_listener(self, ctx) -> Callable[[str, str, dict[str, Any]], None]: ...  # line 207
    async def aclose(self) -> None: ...  # line 327

# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py:17
class CheckpointStore(ABC):
    async def put(self, checkpoint: FlowCheckpoint) -> None: ...      # line 29
    async def latest(self, flow_id: str) -> FlowCheckpoint | None: ...  # line 37
    async def acquire_lease(self, flow_id, holder, ttl=60) -> bool: ...  # line 93

# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py:89
class FlowCheckpoint(BaseModel): ...  # existing fields unchanged; add optional input_metadata

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
#   line 652:  def to_definition(self) -> FlowDefinition:   (fails for callable predicates)
#   line 1276: checkpointer wiring ("enable checkpointing only for flows that can round-trip")
#   line 1332: resume(); line 1419: from_definition() rebuild
```

### Does NOT Exist
- ~~`checkpoint/errors.py`~~ — created by THIS task.
- ~~`FlowCheckpointer.checkpoint()`~~ — only `make_listener()` exists today.
- ~~`AgentsFlow(checkpoint_definition=...)`~~, ~~`checkpoint_shared_data=`~~,
  ~~`checkpoint_input=`~~ — added by THIS task.
- ~~`FlowCheckpoint.input_metadata`~~ — added by THIS task.

---

## Implementation Notes

### Key Constraints
- Backward compatibility is an acceptance criterion: default construction and
  the listener path must behave exactly as before
  (`test_best_effort_checkpoint_behavior_unchanged`).
- Never serialize live objects; the projector output must be encodable by
  `FlowStateSerializer` — a lossy critical value is an error, not a stringified
  fallback.
- Pydantic models; deterministic structured serialization; never pickle.
- Reuse the existing `flowckpt:{flow_id}:*` key family — no new Redis keys.

---

## Acceptance Criteria

- [ ] `FlowCheckpointer.checkpoint()` awaits `put()` and raises
  `CheckpointPersistenceError` on store failure
- [ ] `FlowCheckpoint.input_metadata` round-trips through the serializer; old
  checkpoints (no metadata) still load
- [ ] `resume(expected_input=...)` raises `CheckpointFingerprintMismatchError`
  on mismatch
- [ ] Explicit-graph flows accept an external definition without calling
  `to_definition()`
- [ ] Best-effort default unchanged (spec test
  `test_best_effort_checkpoint_behavior_unchanged`)
- [ ] `pytest packages/ai-parrot/tests -k checkpoint -x -q` passes; `ruff check` clean

---

## Test Specification

```python
async def test_required_checkpoint_put_failure_raises(failing_checkpoint_store):
    with pytest.raises(CheckpointPersistenceError):
        await checkpointer.checkpoint(ctx)

async def test_same_run_id_different_input_rejected(checkpoint_store):
    with pytest.raises(CheckpointFingerprintMismatchError):
        await AgentsFlow.resume(..., expected_input=other_metadata)

async def test_best_effort_checkpoint_behavior_unchanged(checkpoint_store):
    """Default flows still swallow/log listener write failures."""
```

`failing_checkpoint_store` fixture: `store.put = AsyncMock(side_effect=ConnectionError("redis unavailable"))`.

---

## Agent Instructions

1. Read spec §2 (Data Models, New Public Interfaces), §3 Module 2, §6, §7.
2. Verify contract anchors before coding. 3. TASK-2622 must be in
`sdd/tasks/completed/`. 4. Index → `in-progress`; implement; move this file to
completed; index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
