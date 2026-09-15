# TASK-3276: Private execution pool and atomic admission reservations

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (3-4h)
**Depends-on**: TASK-3275
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3275 payloads (and transitively TASK-3274 store). Can run beside TASK-3277 and TASK-3278: only owns pool.py and test_pool.py; reads but does not edit roster.py.

## Context

Implements M2; §2 admission, concurrency and pool semantics. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Create ExecutionPool with private eligible seats, assigner, cached plan, generation, exclusions and reservation ownership; use the new snapshot/view types from TASK-3275.

- Serialize membership/generation/admission with one asyncio.Condition per pool; return a reservation UID before invoking a child, and release/wake on actual settlement.

- Suspend every alias of all blocked ModelKeys locally before awaiting the store; persist before the caller can retry. A persistence failure keeps local exclusion and requires worker fallback.

- Wait for busy healthy retry models; enforce one active reservation per ModelKey; wake on settlement/suspension/cancellation/close. Do not auto-dispatch native retries.

- Make inherited exclusions immutable for this execution, preserve own incidents after TTL, and represent exhausted/recovery_required/closed without constructing an empty ChunkAssigner.

**NOT in scope**: Engine lifecycle integration, provider probing and filesystem snapshot persistence.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py` | CREATE | Per-execution runtime, condition, reservations and views |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py` | CREATE | Deterministic state-machine and race tests |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.models import RosterSeat, PlannedTask
from parrot.flows.dev_loop.sdd_coder.roster import ChunkAssigner
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:126` — ChunkAssigner(seats) owns mutable rotation; constructor rejects an empty list. assign(wave, task_files) is at 134.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:45` — RosterSeat label is not model identity; native backend is omitted in config.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_jobs.py:9` — Use asyncio.Event-controlled completion rather than sleeps for race assertions.

### Does NOT Exist

- ExecutionPool and its asyncio.Condition do not exist before this task.

- A process-global assigner or TTL timer that revives a running pool is not an acceptable substitute.

New symbols mentioned below are target declarations, not claims about existing APIs. Dependency-produced symbols
must be verified in the feature worktree before import. Never guess a replacement when a contract has changed.

## Implementation Notes

- Python implementations use Pydantic v2 and existing dependencies; no provider SDK or dependency additions.
- Preserve concurrent lint, feedback and exclusive-task scheduling work; do not weaken those gates.
- Run filesystem/ledger work off the event loop. Tests use isolated temporary repositories and no live providers.
- Operational suspension is separate from reviewed code feedback; lint, polling deadlines, cancellation and host
  Git failures do not become model lessons or automatically model suspensions.
- This task has no Delegation Contract: the blueprint fixes boundaries, but complete verified implementation
  blocks are not supplied. Use the normal reasoning-capable implementation route, not a mechanical writer packet.

## Implementation Blueprint

### Steps (in order)

1. Bind constructor state to the explicit execution UUID, canonical scope and roster fingerprint. Copy mutable seat/rotation collections; never mutate RosterConfig.

2. Implement view/admit/release/suspend using the spec signatures. Admission rejects excluded keys and closed/degraded/recovery states atomically, while busy healthy keys await the condition.

3. Increment generation exactly when eligibility changes; invalidate cached plans. Suspension must not release a live reservation and release must not revive its key.

4. Keep pending persistence receipts available for idempotent flush; signal degraded state before returning. Disk I/O and provider calls never hold the condition.

5. Expose snapshot capture/restore hooks consumed by TASK-3282, without owning filesystem journals here. Treat a restored unresolved reservation as recovery_required.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
ExecutionPool.view() -> ExecutionPoolView
async ExecutionPool.admit(task_id: str, key: ModelKey) -> str
async ExecutionPool.release(attempt_uid: str) -> None
async ExecutionPool.suspend(record: SuspensionRecord) -> SuspensionReceipt
```

### Bounded implementation checklist

- [ ] Different pools share no mutable rotations, caches or exclusions; a suspension in A cannot modify active B.

- [ ] Race-controlled admission after the local suspension transition invokes no child; aliases cannot double-book.

- [ ] A busy healthy seat becomes usable only after release; exhaustion wakes waiters without looping.

- [ ] Duplicate suspend returns the same incident receipt, does not extend expiry, and an append failure requires fallback until durably resolved.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-2, AC-5, AC-6, AC-7, AC-8, AC-9. Feature-wide criteria are shared with dependent tasks.

- [ ] Different pools share no mutable rotations, caches or exclusions; a suspension in A cannot modify active B.

- [ ] Race-controlled admission after the local suspension transition invokes no child; aliases cannot double-book.

- [ ] A busy healthy seat becomes usable only after release; exhaustion wakes waiters without looping.

- [ ] Duplicate suspend returns the same incident receipt, does not extend expiry, and an append failure requires fallback until durably resolved.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3276-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_pool_private_state`
- `test_suspend_first_failure`
- `test_expiry_is_new_execution_only`
- `test_suspension_wakes_retry_waiter`
- `test_persistence_failure_is_explicit`
- `test_suspension_does_not_release_reservation`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py
git diff --check
```

Run only relevant subsets while upstream/downstream migration is in progress; do not claim the entire feature is green
from a subset. TASK-3285 runs the final offline package and ledger regression gate. If a runtime defect is discovered
outside this task's scope, report it for the owning task instead of broadening file ownership silently.

## Agent Instructions

1. Read the approved spec and this task completely.
2. Verify dependency entries are done in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json` and their task artifacts are completed.
3. Reverify existing imports/signatures and dependency-produced contracts in the worktree; update stale anchors first.
4. Outline implementation steps and risks; preserve edits from others and touch only declared files.
5. Mark this task in-progress in its per-spec index with the session assignment; do not use the historical monolithic index.
6. Implement the blueprint completely and run the scoped acceptance tests.
7. Record actual results, reviewed fixes, incident IDs if applicable, and any blocked criterion in the Completion Note.
8. On completion move this file to `sdd/tasks/completed/TASK-3276-coder-execution-pool-runtime.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
