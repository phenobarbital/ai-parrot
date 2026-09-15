# TASK-3281: Scope native delivery, reviews, merge and cleanup to execution

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (3-4h)
**Depends-on**: TASK-3280
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3280 naming/admission and transitively TASK-3278 review payloads. Serializes shared engine.py, test_engine_plan_merge.py and test_feedback.py edits before TASK-3282.

## Context

Implements M3; §2 native reservations, attempt-bound reports and cleanup ownership. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Require execution_id on prepare_native, merge, cleanup, record_feedback and record_review; namespace managers/latest attempts/native inflight/source attribution/feedback contexts by execution.

- Use TASK-3280 derived worker IDs consistently for native and MCP branches; parse both new and legacy orphan names for reporting, never auto-delete/adopt ambiguous legacy state.

- Implement suspend_model with explicit execution_id/attempt_uid/reason/evidence_ref; derive target identity from a known attempt, reject cross-execution or invented models and constrain worker reports to valid native/critical-review sources.

- Protect live native reservations after suspension. Only verified completion or explicit confirmed termination permits settlement, merge/cleanup/end; an error report alone is insufficient.

- Preserve per-handoff reviewed-code feedback and zero-fix review measurements; engine attaches execution identity, rejects conflicting caller identity and keeps operational incidents separate.

- Cleanup may remove only settled owned managers; active MCP work, other executions and unresolved native agents remain protected.

**NOT in scope**: MCP tool registration, provider status polling, process killing, and crash-recovery persistence.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Native admission/reporting, review authentication, scoped merge/cleanup |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | Native and cross-execution cleanup regressions |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | Execution-bound review/feedback and critical-defect tests |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, CoderFailure
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReviewStore
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:504` — _manager_for keys TASK.aN; prepare_native at 512 records a native attempt_uid and model, but no execution.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:538` — record_feedback authenticates worktree/task/backend/model; record_review at 572 checks reachable fix(...) TASK review fixes commits and actual exposure.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:727` — merge derives latest attempt from manager key strings; cleanup at 777 currently enumerates all managers; _orphan_branches at 794 parses legacy names.

- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:134` — _branch_suffix(worker_id) replaces dots; create(worker_id) at 146 returns the path and records branch ownership.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py:90` — test_native_handoff_records_then_recalls_verified_correction covers native attribution; other tests cover unknown attempts and review commit verification.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py:300` — test_engine_cleanup_keeps_native_task_until_merged protects existing live native worktrees.

### Does NOT Exist

- No native Agent polling tool exists; an assistant text claim is not evidence that its process exited.

- Current cleanup has no execution filter and current feedback source tuples cannot authenticate an execution.

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

1. Migrate manager/source lookups to execution-owned mappings, using TASK-3280 naming helper everywhere. Never parse an attempt number from a UUID-bearing string with the old rsplit('.a') expression.

2. Gate prepare_native on current generation/model availability, reserve before handing out the worktree and return execution_id/model/attempt_uid/feedback. Duplicate preparation must not create a second child reservation.

3. Validate suspension reports against issued attempt ownership and bounded evidence. Build the source and blocked keys server-side; repeat returns the original receipt.

4. Keep reporting and settlement separate. Native completion is acknowledged only after the worker has received the child result; uncertain or merely timed-out waits cannot unlock cleanup.

5. Scope _consolidate/merge locking to ownership-safe execution work and preserve ancestry/fidelity checks. Keep conflicted branches and legacy orphans unless explicitly safely adopted.

6. Authenticate feedback/review within the execution and attach its ID before store recording. A critical reviewed code defect may produce both a suspension and valid model lesson; a platform timeout never creates a lesson.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
async SddCoderEngine.suspend_model(execution_id: str, attempt_uid: str, reason: str, evidence_ref: str) -> SuspensionReceipt
prepare_native / merge / cleanup / record_feedback / record_review: add explicit execution_id
NativePrep: execution_id + attempt_uid + model + existing coder_feedback
```

### Bounded implementation checklist

- [ ] A report for an unknown/wrong-execution attempt changes no model pool and writes no event.

- [ ] A suspended but live native agent still blocks cleanup/end; prepared work cannot be deleted under it.

- [ ] A cleanup cannot enumerate/delete B's managers, jobs, native reservations or latest-attempt data.

- [ ] Review/feedback validates original backend/resolved model and preserves review-fix source checks; timeouts never pollute lessons.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-1, AC-2, AC-3, AC-6, AC-7, AC-11. Feature-wide criteria are shared with dependent tasks.

- [ ] A report for an unknown/wrong-execution attempt changes no model pool and writes no event.

- [ ] A suspended but live native agent still blocks cleanup/end; prepared work cannot be deleted under it.

- [ ] A cleanup cannot enumerate/delete B's managers, jobs, native reservations or latest-attempt data.

- [ ] Review/feedback validates original backend/resolved model and preserves review-fix source checks; timeouts never pollute lessons.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3281-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_native_report_is_attempt_bound`
- `test_suspension_does_not_settle_native`
- `test_cleanup_cannot_cross_execution`
- `test_review_and_feedback_coexist`
- `test_execution_qualified_attempt_branch_names`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
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
8. On completion move this file to `sdd/tasks/completed/TASK-3281-coder-native-review-ownership.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
