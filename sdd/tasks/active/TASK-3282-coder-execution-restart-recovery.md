# TASK-3282: Persist execution snapshots and reconcile restart safely

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (3-4h)
**Depends-on**: TASK-3281
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3281 fully scoped ownership. Writes engine.py only after native/review isolation; creates the integration file that TASK-3285 later extends.

## Context

Implements M3; §2 lifecycle recovery and persistence failure behavior. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Write atomic per-execution snapshots at .sdd-coder/executions/<uuid>.json off-loop, preserving existing job journals and including scope/config/admission/native ownership/exclusions/job IDs.

- On same-ID begin after restart restore local suspensions regardless of expiry plus original inherited exclusions; validate canonical scope and roster fingerprint against durable execution metadata.

- Require recovery_required for unresolved prepared/running attempts. Reconcile only from existing job/worktree evidence plus confirmed worker completion/termination; no automatic replacement dispatch or native respawn.

- Make status/wait/end retry pending suspension persistence idempotently and expose the latest pool view. Convert engine status to async if needed for durable flush; TASK-3283 updates its toolkit caller.

- End rejects active/uncertain reservations, durably closes settled executions and releases worktree ownership without deleting branches or erasing history.

- Handle corrupt/missing expected snapshot and write/close failure explicitly. A successfully durably closed ID never becomes a fresh run even if an older snapshot says active.

**NOT in scope**: New public reconciliation tools not specified by FEAT-559, process management changes and automatic orphan deletion.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Atomic snapshot writes, replay/reconciliation, async status flush and close |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py` | CREATE | Restart, uncertain child and persistence failure integration cases |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, CoderFailure
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:823` — _journal(worktree, job) writes .sdd-coder/jobs/job_id.json off-loop; it has no reader.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:840` — status(job_id) is currently synchronous; wait(job_id, timeout_seconds) at 1176 reads/journals jobs.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py:63` — JobTable.get returns a deep copy; registry is memory-only and cannot recreate OS child state.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py:67` — git_sandbox_feature provides isolated Git/worktree state for restart tests.

### Does NOT Exist

- Current job journals are write-only and do not implement crash resume.

- No API can reconstruct a lost OS process from a model summary or recover an event never durably written.

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

1. Use temporary sibling file + atomic replace for ExecutionSnapshot, with off-loop I/O and explicit write failures. Keep existing job snapshots; persist pending incident payloads where possible.

2. Replay coder_execution scope/config metadata and TASK-3274 for_execution incidents; combine with saved startup exclusions without recency refresh. First begin without prior evidence is distinct from a missing snapshot for a known run.

3. Restore attribution and reservations conservatively. Lost running jobs become reconciliation evidence, not automatically scheduled coroutines; expose affected attempt/job IDs to the worker.

4. Re-run evidence checks on explicit resume/settlement; never treat a clean directory or missing in-memory task as proof a native process exited. If evidence is insufficient, remain recovery_required.

5. Flush pending incident writes at status/end; persisted=false remains visible until append actually succeeds. Complete known in-flight work may settle while new admission is disabled.

6. Record durable close before releasing ownership and waking waiters. If durable persistence was impossible before machine failure, report unrecoverable evidence honestly instead of fabricating clean history.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
async SddCoderEngine.status(job_id: str) -> CoderJobView (if required to perform off-loop flush)
begin_execution(existing UUID): resume/reconcile, never clear bans
end_execution(execution_id): busy/recovery guards, durable close, ownership release
```

### Bounded implementation checklist

- [ ] Original execution remains suspended after fake-clock TTL expiry; a fresh ID follows current durable cooldown.

- [ ] Uncertain live/prepared work blocks dispatch/cleanup/end until explicit reconciliation; no native child is auto-restarted.

- [ ] Interrupted snapshot/close cannot silently free worktree ownership or resurrect a closed UUID.

- [ ] Persistence retries keep stable IDs/expiry; status exposes degraded state and no further paid dispatch occurs.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-5, AC-7, AC-9, AC-10, AC-11. Feature-wide criteria are shared with dependent tasks.

- [ ] Original execution remains suspended after fake-clock TTL expiry; a fresh ID follows current durable cooldown.

- [ ] Uncertain live/prepared work blocks dispatch/cleanup/end until explicit reconciliation; no native child is auto-restarted.

- [ ] Interrupted snapshot/close cannot silently free worktree ownership or resurrect a closed UUID.

- [ ] Persistence retries keep stable IDs/expiry; status exposes degraded state and no further paid dispatch occurs.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3282-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_restart_same_execution`
- `test_close_then_new_execution`
- `test_persistence_failure_is_explicit`
- `test_restart_preserves_inherited_exclusions`
- `test_corrupt_execution_snapshot_requires_recovery`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py
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
8. On completion move this file to `sdd/tasks/completed/TASK-3282-coder-execution-restart-recovery.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
