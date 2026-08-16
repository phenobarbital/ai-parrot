# TASK-2051: FlowCheckpointer — event-driven snapshots, write-through, dump, lease

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2046, TASK-2047, TASK-2048, TASK-2049
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 — the orchestrating component: subscribes to AgentsFlow's
node-event stream, assembles `FlowCheckpoint`s, writes them fire-and-forget
(PersistenceMixin discipline), owns write-through mode, `dump()`
(ephemeral → durable + mark `suspended`) and the resume lease lifecycle.

---

## Scope

- Implement `checkpointer.py`: `FlowCheckpointer` bound to one flow run:
  - Constructor: flow identity, ephemeral store, optional durable store,
    serializer, retention/history/include_responses/durable options,
    memory refs.
  - `make_listener()` → callback compatible with
    `AgentsFlow.add_node_event_listener()`; on node `completed`/`failed`
    events builds a checkpoint (monotonic `checkpoint_id`,
    `parent_checkpoint_id` = previous) and schedules `store.put()`
    fire-and-forget into a pending-task set.
  - Snapshot assembly: `FlowContext` → `ContextSnapshot` (results via
    serializer; responses only when `include_responses`; errors →
    structured dicts; completed/order/shared_data), per-node FSM states,
    memory refs; sets `lossy` from serializer metadata.
  - Write-through: when `durable=True`, each `put()` goes to BOTH stores.
  - `dump()` — copy retained checkpoints from ephemeral to durable store,
    write a final checkpoint with `status="suspended"`.
  - Lease: `acquire(holder)` / heartbeat task renewing every `ttl/3` /
    `release()`; raise `FlowLockedError` when acquire fails.
  - `aclose()` — await pending writes, stop heartbeat, release lease,
    close nothing it doesn't own.
- Unit tests with an in-memory fake `CheckpointStore` (no Redis).

**NOT in scope**: AgentsFlow constructor wiring / suspend() / resume()
(TASK-2053), `FlowContext.to_snapshot()` helper (TASK-2052 — until it lands,
build the snapshot inside the checkpointer from public FlowContext fields).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py` | CREATE | FlowCheckpointer |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py` | MODIFY | Re-export |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py` | MODIFY | Codebase-contract correction (added during this task, see note below): expose the per-value JSON-safe transform (`to_safe_with_meta()`/`from_safe()`) that TASK-2047 only used internally, so `ContextSnapshot.results`/`.responses` can hold tag-enveloped-but-still-`dict[str, Any]` values (spec model.py comment: "serialized via FlowStateSerializer") instead of opaque encode() bytes. Pure refactor — `encode_with_meta()`/`decode()` now delegate to the new methods; no behavior change, all 14 existing TASK-2047 tests still pass unchanged. |
| `packages/ai-parrot/tests/flows/checkpoint/test_checkpointer.py` | CREATE | Unit tests (fake store) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.context import FlowContext        # verified: core/context.py:52
from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint, ContextSnapshot, NodeStateSnapshot, MemoryRefs  # TASK-2046
from parrot.bots.flows.core.checkpoint.serializer import FlowStateSerializer  # TASK-2047
from parrot.bots.flows.core.checkpoint.store.base import CheckpointStore      # TASK-2048
from parrot.bots.flows.core.checkpoint.errors import FlowLockedError          # TASK-2046
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
def add_node_event_listener(self, callback) -> None: ...        # line 307 — the subscription point
def _notify_node_event(self, event, node_id, info) -> None: ... # line 322 — events arrive shielded;
                                                                #   listener exceptions are logged, not raised

# packages/ai-parrot/src/parrot/bots/flows/core/context.py — fields to snapshot
class FlowContext:                       # line 52
    initial_task: str                    # line 68
    results: Dict[str, Any]              # line 69
    responses: Dict[str, Any]            # line 72
    completion_order: List[str]          # line 78
    errors: Dict[str, Exception]         # line 81 — LIVE exceptions; encode structured
    completed_tasks: Set[str]            # line 87
    shared_data: Dict[str, Any]          # line 90
    # agent_registry (line 93), synthesis_client (line 100), trace_context (line 108)
    #   are NOT serializable — NEVER include them in the snapshot

# packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py — DISCIPLINE to copy
class PersistenceMixin:
    # fire-and-forget writes tracked in self._persist_tasks: set[asyncio.Task],
    # awaited with return_exceptions=True in aclose(); failures log warning, never raise
```

### Does NOT Exist
- ~~`FlowCheckpointer`~~ — introduced HERE.
- ~~`FlowContext.to_snapshot()`~~ — TASK-2052 adds it later; do NOT call it here, assemble from the public fields listed above.
- ~~AgentsFlow `checkpoint=` kwarg / `suspend()` / `resume()`~~ — TASK-2053; this task must be testable WITHOUT touching flow.py.
- ~~Node-event payload guarantees beyond (event, node_id, info)~~ — read `_notify_node_event` (flow.py:322) and `_run_node` (flow.py:556) to confirm the exact event names/payload before coding against them.

---

## Implementation Notes

### Key Constraints
- Checkpoint writes must NEVER propagate exceptions into the flow: schedule
  with `asyncio.create_task`, track in a pending set, log warnings on failure
  (copy the `PersistenceMixin._save_result` try/except discipline).
- Monotonic `checkpoint_id` starts at 1 per flow run; on resume it continues
  from the loaded checkpoint's id (constructor accepts a starting id).
- Heartbeat task must be cancelled cleanly in `aclose()` (no pending-task
  warnings on event loop close).
- The listener must be synchronous-signature-compatible with whatever
  `add_node_event_listener` expects (verify at flow.py:307 — it may accept
  sync callbacks and/or coroutines; `_notify_node_event` shields both).

---

## Acceptance Criteria

- [ ] `test_checkpointer_writes_on_node_completion` — node event → checkpoint with parent chain and monotonic ids in the fake store.
- [ ] `test_checkpointer_write_failure_does_not_break_flow` — store raising → warning logged, no exception escapes the listener.
- [ ] `test_checkpointer_results_only_vs_include_responses` — responses absent by default, present with flag.
- [ ] Write-through puts to both stores when durable is configured.
- [ ] `dump()` copies history to durable and final status is `"suspended"`.
- [ ] Lease acquire/heartbeat/release lifecycle covered; conflict raises `FlowLockedError`.
- [ ] `pytest packages/ai-parrot/tests/flows/checkpoint/test_checkpointer.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/checkpoint/test_checkpointer.py
@pytest.fixture
def fake_checkpoint_store():
    """In-memory CheckpointStore recording puts; lease as plain dict."""

async def test_writes_on_node_completion(fake_checkpoint_store, flow_context):
    cp = FlowCheckpointer(flow_id="f1", store=fake_checkpoint_store, ...)
    listener = cp.make_listener(flow_context)
    listener("completed", "node-a", info={})
    await cp.aclose()
    assert fake_checkpoint_store.puts[0].checkpoint_id == 1

async def test_store_failure_shielded(failing_store, flow_context, caplog):
    ...  # no raise; warning in caplog

async def test_dump_marks_suspended(fake_checkpoint_store, fake_durable_store):
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2046/2047/2048/2049 in `tasks/completed/`
3. **Verify the Codebase Contract** — read flow.py:307-360 and core/storage/persistence.py before coding
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement**, then **verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Implemented `checkpointer.py` (`FlowCheckpointer`):
- `make_listener(ctx)` returns a SYNC `(event, node_id, info) -> None`
  callback filtered to `node_completed`/`node_failed` (verified event
  names against `flow.py:322-338`'s docstring). It stays sync
  deliberately: `_notify_node_event()` only auto-schedules a task when a
  listener *returns* a coroutine (`asyncio.iscoroutine(outcome)`) — this
  checkpointer instead owns its own `_pending_tasks` set so `aclose()`
  can await every write, matching the `PersistenceMixin` discipline
  exactly rather than relying on flow.py's fire-and-forget wrapper (whose
  tasks are never exposed back to any caller).
- `_build_checkpoint()` assembles `ContextSnapshot` from the public
  `FlowContext` fields only (never `agent_registry`/`synthesis_client`/
  `trace_context`); monotonic `checkpoint_id` + `parent_checkpoint_id`
  chain tracked on the instance, continuable via `starting_checkpoint_id`
  for the eventual resume path (TASK-2053).
- Write-through (`durable=True`) puts to both stores; each store write
  is wrapped in its own try/except — a durable-store failure never
  blocks/skips the ephemeral write or vice versa.
- `dump()` copies the ephemeral store's retained `history()` to the
  durable store, then writes one more `status="suspended"` checkpoint to
  both stores.
- Lease: `acquire_lease()` raises `FlowLockedError` on conflict and
  starts a heartbeat task renewing every `ttl/3`; `release_lease()`
  cancels the heartbeat and releases; both are idempotent/no-op-safe.

**Codebase Contract correction (flagged, not silent)**: this task's own
contract didn't need it, but the spec's model.py comment for
`ContextSnapshot.results` ("serialized via FlowStateSerializer") and
TASK-2047's original intent required a per-value JSON-safe transform
that TASK-2047 had only as a private `_encode_value` helper. Rather than
reach into `FlowStateSerializer`'s internals from another module, added
two small public methods to `serializer.py`
(`to_safe_with_meta()`/`from_safe()`) — a pure refactor: `encode_with_meta()`
now delegates to `to_safe_with_meta()` + `packb()`, no behavior change.
Updated this task's own Codebase Contract table first (see the `serializer.py`
row above) before making the change, per the anti-hallucination protocol.
All 14 pre-existing TASK-2047 serializer tests still pass unchanged, plus
the new checkpointer tests. Verified: `ContextSnapshot.results` now holds
tag-enveloped-but-JSON-safe dict values (e.g. `{"answer": 42}` passes
through untouched; a registered/unregistered model would tag-envelope)
rather than opaque encode() bytes — confirmed in
`test_checkpointer_results_only_vs_include_responses`.

Added `test_checkpointer.py` with a `FakeCheckpointStore` (in-memory,
records puts, dict-based lease) — 10 tests: node-completion writes with
parent chain, non-checkpoint events ignored, write-failure isolation
(caplog warning, no raise), results-only vs include_responses, write-through
to both stores, `dump()` suspends + copies history, `dump()` without a
durable store raises `ValueError`, lease acquire/conflict/release
lifecycle, heartbeat actually renews (observed via the fake store's lease
dict after `ttl/3` sleep), and memory_refs round-trip onto the
checkpoint. Full `tests/flows/checkpoint/` suite: 38 passed, 9 skipped
(Redis/pg/mongo integration tests requiring live services, unaffected by
this task). `ruff check` clean.

**Deviations from spec**: none (the serializer.py addition is a
capability the spec's own data model implied but TASK-2047 didn't
expose publicly — documented above, not a functional deviation).
