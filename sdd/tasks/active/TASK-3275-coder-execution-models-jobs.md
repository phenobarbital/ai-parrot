# TASK-3275: Execution payload contracts and scoped job ownership

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-3274
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3274 for ledger identity/policy types. Completes shared models/jobs edits before the runtime, roster and attribution tasks fan out.

## Context

Implements M2; §2 data models, public interfaces and job ownership. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Add ExecutionPoolView, PoolSeatView and ExecutionSnapshot with spec fields, validated UUID/scope/fingerprint, status, generation, fallback state and persistence metadata; runtime locks are not serialized.

- Import the dependency's ledger identity/policy/incident/receipt models. Add RosterConfig.suspension policy and structured per-model probe failure metadata on SeatProbeResult (including probe UID, observed time, duration and exception class), so roster wiring need not infer failures from prose.

- Add execution_id and generation/pool views where required in plans/jobs/native prep/attempts; add not_dispatched with a structured reason and no synthetic attempt.

- Define begin/end/suspend argument models; require execution_id on the seven scoped orchestration/review tools. Split read-only feedback-report arguments from CoderPlanArgs so reporting never starts or requires an execution.

- Extend JobTable.create with explicit execution_id and running_task_ids with an execution filter; preserve job_id uniqueness, copy isolation and caller-timeout shielding.

**NOT in scope**: Provider probing, engine methods, toolkit registration and runtime reservations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Execution models, arguments, policy and error codes |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py` | MODIFY | Execution ownership in jobs and running-task queries |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py` | MODIFY | Strict payload and compatibility tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_jobs.py` | MODIFY | Cross-execution job isolation tests |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, CoderJob, AttemptRecord
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:20` — TaskOutcome is a closed Literal; ERROR_CODES is closed; RosterConfig at 116 currently carries lint and feedback only.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:167` — CoderPlan; AttemptRecord at 181; NativePrep at 238; CoderJob at 251 currently lack execution_id.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:308` — _Args uses extra='forbid'. CoderPlanArgs at 333 is also used for repository-wide feedback_report.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py:25` — JobTable.create(feature_id, task_ids, runner) -> CoderJob immediately schedules; running_task_ids() at 59 is unscoped; wait at 69 shields the runner.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py:57` — TestAttemptRecordTelemetryFields checks pre-existing records remain parseable.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_jobs.py:9` — test_job_wait_returns_snapshot_on_timeout uses asyncio.Event; poll timeout preserves the job.

### Does NOT Exist

- ExecutionPoolView, ExecutionSnapshot, SuspendModelArgs and not_dispatched are new contracts.

- There is no execution ownership in the current JobTable; a chunk job UUID is not an execution UUID.

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

1. Keep existing fields and import paths intact. New structured models use ConfigDict(extra='forbid'). Legacy stored attempts may omit execution identity when parsed, but new operational calls must never mint an implicit ID.

2. Use SuspendModelArgs(execution_id, attempt_uid, reason, evidence_ref), with no caller backend/model override. Add all twelve execution error codes from spec §2 without weakening the known-code validator.

3. Store complete snapshot ownership/exclusions rather than summary text. Document probe-failure records as newly introduced payloads, not SuspensionRecords with invented execution attribution.

4. Thread execution_id through JobTable scheduling and snapshots; filter duplicate-task queries by execution while retaining explicit all-job inspection for shutdown only.

5. Update only models/jobs tests here; later engine/toolkit tasks migrate their callers. No broad compatibility bypass on public dispatch methods.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
JobTable.create(feature_id: str, task_ids: list[str], runner, *, execution_id: str) -> CoderJob
JobTable.running_task_ids(execution_id: str) -> set[str]
SuspendModelArgs: execution_id, attempt_uid, reason, evidence_ref
CoderFeedbackReportArgs: feature, worktree (no execution_id)
```

### Bounded implementation checklist

- [ ] Seven scoped tool schemas require execution_id; feedback_report and job wait/status do not require it.

- [ ] Two jobs with the same task ID in different executions do not collide in scoped running queries.

- [ ] New jobs retain execution_id in detached snapshots; old attempt payloads still parse for historical telemetry.

- [ ] Probe metadata can describe a failed primary even when a configured fallback succeeds.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-1, AC-6, AC-8, AC-11. Feature-wide criteria are shared with dependent tasks.

- [ ] Seven scoped tool schemas require execution_id; feedback_report and job wait/status do not require it.

- [ ] Two jobs with the same task ID in different executions do not collide in scoped running queries.

- [ ] New jobs retain execution_id in detached snapshots; old attempt payloads still parse for historical telemetry.

- [ ] Probe metadata can describe a failed primary even when a configured fallback succeeds.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3275-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_execution_models_reject_invalid_uuid_and_extra_fields`
- `test_missing_execution_rejected_by_scoped_args`
- `test_job_running_tasks_are_execution_scoped`
- `test_job_wait_returns_snapshot_on_timeout`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_jobs.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_jobs.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_jobs.py
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
8. On completion move this file to `sdd/tasks/completed/TASK-3275-coder-execution-models-jobs.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
