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
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `checkpoint_required` param; awaited barrier in scheduler; failure containment; reads heartbeat-loss state |
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | MODIFY | `reset_completed()` |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py` | MODIFY | Contract correction (added during implementation): "heartbeat surfacing" requires exposing the failure FROM `FlowCheckpointer._heartbeat_loop()` — the only place the renewal outcome is observed — TO the scheduler. Added `lease_lost` (bool property) + `raise_if_lease_lost()`; `_heartbeat_loop()` now also sets `self._lease_lost`/`self._lease_lost_exc` on a renewal exception or a `renew_lease()` that returns `False`, in addition to its existing (unchanged) logging-only behavior. `flow.py`'s barrier calls `raise_if_lease_lost()` before every required checkpoint. No file not already implied by "heartbeat surfacing" was touched. |
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
- ~~`FlowCheckpointer.lease_lost`~~, ~~`FlowCheckpointer.raise_if_lease_lost()`~~ —
  added by THIS task (contract correction, see Files table above).
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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-31
**Notes**: Re-grepped every anchor before patching, as instructed (line
numbers had already drifted from TASK-2622/2623).

`AgentsFlow.__init__` gained `checkpoint_required: bool = False`. In the
explicit-mode scheduler, `_resolve_ready_targets()` and `_resolve_retries()`
were refactored to COMPUTE eligible targets/the retry decision (applying
skips and — for retries — `ctx.reset_completed()` — immediately, since those
never need the barrier) WITHOUT spawning; the main loop then awaits a new
`_await_required_barrier()` closure (only when `required and
event.error is None` — the barrier is success-only, spec §7) before spawning
everything the event made eligible. `_await_required_barrier()` calls
`checkpointer.raise_if_lease_lost()` then `await checkpointer.checkpoint(ctx)`;
on `CheckpointPersistenceError` it cancels/awaits every still-active sibling
task before re-raising — `run_flow()`'s existing `finally: await
checkpointer.aclose()` already releases the lease, so no separate release
logic was needed. `_ensure_checkpointer()` now skips attaching the
fire-and-forget listener entirely when `checkpoint_required=True` (both the
fresh-build and the resume-reuse branch), matching the spec §7 instruction
literally: required persistence never runs through `make_listener()`.

`FlowContext.reset_completed()` removes a set of node ids from
`completed_tasks`/`completion_order`/`active_tasks`/`results`/`responses`/
`node_metadata`/`errors` — deliberately NOT touching `shared_data`, which is
exactly what let the retry-frontier test demonstrate a resumed run
continuing the SAME bounded retry (via a shared_data-persisted attempt
counter) instead of restarting the whole cycle from scratch.

**Contract correction** (documented in the Files table above): "heartbeat
surfacing" cannot be implemented inside `flow.py` alone — the renewal
outcome is only ever observed inside `FlowCheckpointer._heartbeat_loop()`
(`checkpointer.py`), which the task's original Files table omitted. Added
`FlowCheckpointer.lease_lost` (property) and `raise_if_lease_lost()`;
`_heartbeat_loop()` now sets `_lease_lost`/`_lease_lost_exc` on a renewal
exception OR a `renew_lease()` that returns `False` (a real split-brain
signal, not just a network blip), in addition to its unchanged logging-only
behavior for generic (non-required) callers. `checkpoint()` itself also
calls `raise_if_lease_lost()` first, so the check applies uniformly whether
triggered from the scheduler barrier or a direct `checkpoint()` call.

While writing the failure-containment test I found and fixed a real bug:
`flow.py` imported `CheckpointFingerprintMismatchError`/
`CheckpointNotFoundError`/`FlowNotExportableError` from `checkpoint/errors.py`
in TASK-2623 but never imported `CheckpointPersistenceError` — the new
`_await_required_barrier()`'s `except CheckpointPersistenceError:` raised
`NameError` at runtime. `test_required_checkpoint_put_failure_raises` caught
it immediately; fixed by adding the missing import.

9 new tests in `test_required_barrier.py`: barrier ordering (blocks a real
downstream node until `put()` lands, via an `asyncio.Event`-gated store),
put-failure propagation + zero downstream dispatch, active-sibling
cancellation on barrier failure, the retry-frontier resume scenario (full
end-to-end: run → crash → resume from the exact post-reset checkpoint →
verify the repair cycle genuinely re-executes rather than being skipped),
best-effort-unchanged, required-mode-skips-the-listener,
non-required-mode-keeps-the-listener, and two lease-heartbeat-loss tests
(one exercising the real 1s heartbeat interval end-to-end on
`FlowCheckpointer` directly, one driving the scheduler barrier itself with
a pre-flipped `lease_lost` flag for speed). Full
`packages/ai-parrot/tests/flows` suite: 1482 passed (up from 1473 at
TASK-2623, +9), same 5 pre-existing failures (2 postgres-integration + 3
unrelated dev-loop QA/secondopinion prompt tests, both confirmed pre-existing
in TASK-2622/2623's notes). Also ran `packages/ai-parrot/tests/bots/flows`
(491 passed) and `packages/ai-parrot/tests/test_flow_primitives` (234
passed) for broader regression coverage, since this task touches the core
scheduler shared by every `AgentsFlow` caller, not just the checkpoint
plane.

**Pre-existing environment issue found, not fixed (out of scope)**:
`packages/ai-parrot/tests/bots/flows/test_result_fidelity.py`'s
`TestCrewFlowParity` class (3 of its 5 tests) hangs indefinitely when
collected in the SAME pytest session as any other file/directory under
`tests/bots/flows/` — reproducible standalone in under a second, but never
completes as part of a larger run. Confirmed via `git stash` against a
clean pre-TASK-2624 checkout of this worktree (i.e. also present on `dev`
before this feature): identical hang with zero flow.py/context.py/
checkpointer.py changes applied. Root cause not investigated further (out
of scope for FEAT-480); worth a dedicated look before this file is next
touched. The acceptance criterion's literal
`pytest packages/ai-parrot/tests -k "flow or checkpoint" -x -q` also cannot
run to completion in this environment for two independent pre-existing
reasons: (1) 25 unrelated collection errors across the wider `tests/`
tree (documented in TASK-2622's notes — needs
`--continue-on-collection-errors`), and (2) this hang, once that flag is
added. Verified equivalent coverage via the scoped suites listed above
instead.

**Deviations from spec**: none (one Codebase Contract correction — a missing
file in the Files table — documented above and in the task file itself).
