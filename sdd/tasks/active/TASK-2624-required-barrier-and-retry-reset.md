# TASK-2624: Required Checkpoint Barrier in the Scheduler and Retry-Safe Reset

**Feature**: FEAT-480 — Dev Flow Node Checkpoint Recovery
**Spec**: `sdd/specs/dev-flow-node-caching.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2623
**Assigned-to**: unassigned

---

## Context

Implements the execution half of spec §3 Module 2. With the awaited
`checkpoint()` call available (TASK-2623), the `AgentsFlow` scheduler must gate
downstream routing on it when `checkpoint_required=True`: the write happens
after `ctx.mark_completed()` and after computing any retry invalidation, but
BEFORE spawning any outgoing normal or back-edge target. This is a core
execution barrier, not a telemetry listener — listener failures stay swallowed
(spec §2 Overview, §7 Patterns). A bounded-retry transition must also reset
invalidated nodes in both scheduler-local state and `FlowContext`, so the
persisted frontier requests the next attempt instead of restoring stale
completions.

---

## Scope

- Add `checkpoint_required: bool = False` to `AgentsFlow.__init__` (default
  keeps generic best-effort behavior byte-for-byte).
- In the explicit-mode scheduler, when required: after `ctx.mark_completed()`
  (`flow.py:1980`) and after retry-reset computation, await
  `FlowCheckpointer.checkpoint(ctx)` before `_spawn(...)` of any downstream
  target (`flow.py:1855`, routing at `flow.py:2006`). On
  `CheckpointPersistenceError`: fail the job — cancel/settle already-active
  siblings, release the lease, dispatch no new work.
- Add `FlowContext.reset_completed(node_ids: set[str]) -> None` and call it
  when a back-edge reset fires (`flow.py:1812`/`1836`), so reset members leave
  both scheduler state and recoverable context state before the barrier write.
- Make checkpoint completion monotonic: the in-memory parent checkpoint ID
  advances only after the required store write succeeds.
- Surface lease-heartbeat loss as a hard failure to the active job in required
  mode (today it only logs from a background task).
- Unit tests for barrier ordering, failure containment, retry-frontier
  persistence, and unchanged default behavior.

**NOT in scope**: fingerprint computation, dev workflow wiring (TASK-2625+),
`AgentCrew` (explicit non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `checkpoint_required` param; awaited barrier in scheduler; failure containment; heartbeat surfacing |
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | MODIFY | `reset_completed()` |
| `packages/ai-parrot/tests/flows/checkpoint/test_required_barrier.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows import AgentsFlow, FlowContext
from parrot.bots.flows.core.checkpoint import FlowCheckpointer, CheckpointStore
# plus from TASK-2623: CheckpointPersistenceError (checkpoint/errors.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:209  class AgentsFlow(PersistenceMixin)
# Scheduler anchors (verified 2026-08-31):
#   line 1812: def _resolve_retries() -> bool:        — retry/back-edge reset computation
#   line 1836: for member in members:                 — reset-member iteration
#   line 1855: _spawn(tgt)                            — downstream dispatch point
#   line 1980: ctx.mark_completed(                    — node completion
#   line 2006: if explicit_mode:                      — explicit-mode routing branch

# packages/ai-parrot/src/parrot/bots/flows/core/context.py:177
class FlowContext:
    def mark_completed(self, ...) -> ...: ...

# From TASK-2623:
#   async FlowCheckpointer.checkpoint(ctx, *, status="running") -> FlowCheckpoint
```

### Does NOT Exist
- ~~`AgentsFlow(checkpoint_required=True)`~~ — added by THIS task.
- ~~`FlowContext.reset_completed()`~~ — added by THIS task.
- ~~A per-node "checkpoint pending" queue~~ — do not invent one; the barrier is
  an awaited inline call at the completion/routing seam.
- Line numbers above drift as flow.py is edited — re-grep the anchors
  (`_resolve_retries`, `mark_completed(`, `_spawn(`) before patching.

---

## Implementation Notes

### Key Constraints
- Ordering is the whole task: mark-completed → compute+apply retry reset
  (scheduler AND `FlowContext`) → awaited checkpoint → only then spawn
  targets. A crash between checkpoint and spawn must restore a frontier that
  re-runs the not-yet-spawned target (at-least-once).
- Failed or cancelled nodes are never added to `completed_tasks` / never
  checkpointed as complete.
- Keep telemetry listener shielding untouched; required persistence must not
  run through `make_listener()`.
- Preserve gate parking semantics and exactly-once semaphore release
  bookkeeping in the scheduler.

---

## Acceptance Criteria

- [ ] `test_required_checkpoint_awaits_put_before_routing` — downstream node
  cannot start until `put()` succeeds
- [ ] `test_required_checkpoint_put_failure_raises` — failure raises
  `CheckpointPersistenceError`, downstream dispatch count stays zero
- [ ] `test_retry_checkpoint_restores_post_reset_frontier` — crash after a
  repair back-edge restores the invalidated cycle and reruns it
- [ ] `test_best_effort_checkpoint_behavior_unchanged` still passes
- [ ] Lease-heartbeat loss fails the active required-mode job
- [ ] Full flow test suite passes: `pytest packages/ai-parrot/tests -k "flow or checkpoint" -x -q`; `ruff check` clean

---

## Test Specification

```python
async def test_required_checkpoint_awaits_put_before_routing(checkpoint_store):
    """Block put() with an event; assert downstream node has not started."""

async def test_required_checkpoint_put_failure_raises(failing_checkpoint_store):
    """ConnectionError in put() -> CheckpointPersistenceError; dispatch count == 0."""

async def test_retry_checkpoint_restores_post_reset_frontier(checkpoint_store):
    """QA-fail back-edge fires, process 'crashes', resume reruns the repair
    cycle instead of skipping it (reset members absent from completed set)."""
```

Use execution counters; assertions must not pass vacuously.

---

## Agent Instructions

1. Read spec §2 Overview (barrier paragraph), §3 Module 2, §7 Known Risks.
2. Re-verify all flow.py anchors by grep — they WILL have drifted after
TASK-2622/2623. 3. Depends-on tasks must be in `sdd/tasks/completed/`.
4. Index → `in-progress`; implement; move to completed; index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
