# TASK-3280: Gate dispatch and retries and classify terminal failures

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (3-4h)
**Depends-on**: TASK-3279
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3279 engine lifecycle; modifies engine.py after it. TASK-3281 must wait because native/merge paths reuse the execution naming and attempt attribution introduced here.

## Context

Implements M3; §2 failure matrix and admission races. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Require execution_id in run_chunk and carry it into every job/attempt; retain dispatcher run_id=job_id.

- Reject stale plan generation before job/worktree creation, then recheck admission in each scheduled coroutine and retry. A seat lost before admission produces not_dispatched with no attempt or usage row.

- Classify qualifying terminal failures at known phases: wrapped dispatch timeout, dispatch failure, invalid/exhausted output, coder-owned dirty delivery and fidelity violation. Exclude lint/autofix, Git/setup failures, cancellation and wait timeout.

- Suspend configured route and different resolved model as one incident; persist before scheduling replacement. Preserve already-admitted siblings and enforce at most two actual MCP attempts.

- Select retry from healthy not-yet-tried ModelKeys; wait on busy healthy seats through the pool condition. Exhaustion/degraded persistence requests worker fallback without infinite replanning.

- Introduce centralized execution-qualified worker/branch/path naming used here and by TASK-3281, retaining SubWorktreeManager's existing protocol.

**NOT in scope**: Native worker reports, public tool schemas, recovery journal reader and the separate Codex stdin fix.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Execution-bound run_chunk/attempts, classifier, admission and retry loop |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Fake dispatch tests for timeout, aliases, stale plans and retry races |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, CoderFailure
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError, DispatchOutputValidationError
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:871` — _run_attempt(ctx, task, seat, *, attempt, job_id) creates manager/worktree before dispatcher.dispatch; broad exception catch currently loses phase information.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1057` — _run_task(ctx, task, seat, *, job_id) allows two MCP attempts and excludes only the first failed label.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1138` — run_chunk(feature, worktree, task_ids) validates first cached chunk then schedules JobTable.create; _emit_outcome at 1006 emits per-attempt rows.

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:418` — DispatchExecutionError wraps failures; DispatchOutputValidationError at 427 has raw_payload, which must not be persisted.

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:168` — Codex dispatch raises DispatchExecutionError from TimeoutError; inspect bounded cause chains, not error strings.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py:18` — FakeDispatcher supports ok/fail/block; fake_builder_factory at 70 supplies injected profiles and dispatchers.

### Does NOT Exist

- Current _run_attempt has no phase-aware classifier; diagnostic text matching cannot provide reliable attribution.

- There is no authorization to change Codex stdin/deadline/process termination code in this task.

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

1. Validate scope and cached generation under the pool admission boundary before JobTable.create. Recheck when the runner enters, so selected-but-not-admitted tasks cannot slip past a suspension.

2. Reserve the ModelKey and reuse that reservation UID as the engine attempt attribution key. Capture phase explicitly around manager/build/dispatch/consolidation, releasing only when the attempt really settles.

3. Traverse a bounded cycle-safe __cause__/__context__ chain for TimeoutError. Do not classify a tool polling deadline or build/setup error as a model timeout.

4. At failure observation build SuspensionRecord with fixed timestamps, observed duration, sanitized evidence and both configured/resolved keys. Atomically suspend first, then await persistence before retry.

5. Emit allowlisted telemetry with execution_id; preserve exactly one attempt outcome per real failed attempt and no fabricated counters for skips. Keep feedback refresh per actual model attempt.

6. Centralize worker_id as TASK-N.a<attempt>.<execution_uuid_hex>. Prevent same-execution redispatch from reusing an owned active branch; do not change the standalone worktree manager or dispatcher hotfix.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
async SddCoderEngine.run_chunk(feature: str, worktree: str, task_ids: list[str], execution_id: str) -> CoderJob
_run_task and _run_attempt: explicit execution ownership propagated with job_id
Dispatcher.dispatch(..., run_id=job_id): unchanged boundary
```

### Bounded implementation checklist

- [ ] Fake wrapped timeout is observed immediately and bars later admission; no test waits 1800 seconds.

- [ ] A raced stale plan creates neither job nor worktree; a later lost queued admission has attempts=[].

- [ ] A busy retry seat is never double-booked; exhausted/degraded pool cannot continue dispatching.

- [ ] Cancellation/poll timeout/Git conflict/lint alone produce no suspension. Dirty/fidelity failures are attributed only to coder changes, not engine journals.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-1, AC-2, AC-3, AC-7, AC-8, AC-9, AC-11, AC-13. Feature-wide criteria are shared with dependent tasks.

- [ ] Fake wrapped timeout is observed immediately and bars later admission; no test waits 1800 seconds.

- [ ] A raced stale plan creates neither job nor worktree; a later lost queued admission has attempts=[].

- [ ] A busy retry seat is never double-booked; exhausted/degraded pool cannot continue dispatching.

- [ ] Cancellation/poll timeout/Git conflict/lint alone produce no suspension. Dirty/fidelity failures are attributed only to coder changes, not engine journals.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3280-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_timeout_cause_classification`
- `test_non_model_failures_do_not_suspend`
- `test_stale_plan_admits_nothing`
- `test_retry_uses_only_healthy_free_model`
- `test_model_aliases_and_parallel_admission`
- `test_cooldown_starts_at_failure_observation`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py
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
8. On completion move this file to `sdd/tasks/completed/TASK-3280-coder-engine-admission-retries.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

**Delivered by**: MCP coder, seat `glm5` (backend `nova`, model `zai.glm-5`),
attempt_uid `62b22afaf6e74838b5d8f6bd5b36f9ef`, commit f561f3b35844e2276722428d178b5319ec5ebe26 — 2026-09-16.
**Reviewed and corrected by**: sdd-worker (Sonnet 5 orchestrator) — 2026-09-16.

**Implementation summary**: `run_chunk()` now gates each dispatch through `pool.admit()`/`pool.release()`;
`_classify_failure_reason()` maps a failure's bounded exception cause chain to a `SuspensionReason`
(`timeout`/`dispatch_error`/`invalid_output`/`dirty_delivery`/`fidelity_violation`), distinguishing a wrapped
dispatch-deadline `TimeoutError` from a `coder_wait` polling timeout; `_classify_and_suspend()` builds and
persists the `SuspensionRecord` before scheduling a retry; `_select_retry_seat()` picks a healthy,
not-yet-tried model, waiting on the pool's condition when busy; stale plans are rejected (`plan_stale`)
before any job/worktree is created; `_run_attempt()`/`_run_task()` carry `execution_id`/`pool` end-to-end.

**Review findings (confirmed, fixed)**: `engine.py`'s own new logic was correct — the actual defect was
entirely in the TEST FILE. `test_engine_dispatch.py`'s local `_roster(*labels_backends)` helper built every
seat with no `model=` (default `""`), used by nearly every test in the file including almost all of this
task's own new tests (`TestStalePlanAdmitsNothing`, `TestRetryUsesOnlyHealthyFreeModel`,
`TestModelAliasesAndParallelAdmission`, `TestCooldownStartsAtFailureObservation`). TASK-3277's (already-
merged) mandatory `model_identity_required` rule now always excludes an empty-model seat before any
probe/smoke call, so 19 of 29 tests failed with `roster_empty`. Added an explicit, distinct-per-label
`model=f"model-{lbl}"` to `_roster()` and to two hand-built inline rosters
(`test_plan_then_dispatch_uses_consistent_seat_assignment`). As a side effect, this also resolved the
previously-deferred `test_feedback.py::test_mcp_retry_refreshes_feedback_for_each_model` collateral failure
(now genuinely fixed by this task's own `run_chunk`/`JobTable.create(execution_id=...)` threading, not
merely reformulated).

**Verification evidence**:
- `pytest test_engine_dispatch.py -q` → 29 passed (was 10 passed / 19 failed).
  Log: `artifacts/logs/task-3280-pytest.log`.
- Full `tests/flows/dev_loop/sdd_coder/` sweep (excluding `test_mcp_local.py`): 263 passed, 5 failed — all 5
  in files outside this task's scope (`test_integration_chunk.py` ×3 → confirmed owned by TASK-3285;
  `test_toolkit.py` ×2 → confirmed owned by TASK-3283, `CoderPlanArgs.execution_id` not yet threaded through
  the MCP toolkit). Flagged for verification when those tasks are consolidated.
- `ruff check` → clean except pre-existing `lint.residual` (ASYNC240×5, B905×1, already flagged by the
  engine's own lint pass, deferred to `/sdd-done`'s feature-wide pass per policy). `black --check` → clean.
  Logs: `artifacts/logs/task-3280-ruff.log`, `artifacts/logs/task-3280-black.log`.
- `git diff --check` → clean. Only `test_engine_dispatch.py` changed (declared scope).
- Model feedback recorded: `coder-feedback:bd774ff2ff65fb16d459c060` (pattern
  `empty-model-roster-fixture-vs-model-identity-required`, model `nova/zai.glm-5`).
- Review measurement recorded: `coder-review:69288535cfdb75cee377eb43`, fix commit
  `699a38e7738fbbaae7200d9f9d34163e3661aefb` (marker commit `10a645f381fc410cff752c0b83c69159f08cae9a`
  carries the exact `fix(...): TASK-3280 review fixes` message the review tool requires; the real diff is
  in the referenced commit).

Seat: glm5 · Backend: nova · Model: zai.glm-5 · Attempts: 1 (MCP) + 1 (orchestrator review fix) · Duration:
635.0s (MCP attempt) · Tokens: 3,447,906 in / 16,892 out (MCP attempt)
