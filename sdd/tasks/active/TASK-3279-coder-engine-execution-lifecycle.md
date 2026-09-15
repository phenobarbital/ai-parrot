# TASK-3279: Begin execution and plan from private history-gated pools

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (3-4h)
**Depends-on**: TASK-3276, TASK-3277, TASK-3278
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Fan-in after TASK-3276 runtime, TASK-3277 probe gates and TASK-3278 attribution. Begins the ordered engine.py edit sequence; no concurrent engine edits are permitted.

## Context

Implements M3; §2 startup, scope binding and cached planning. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Replace global availability with an execution registry; open initializes only and makes zero probes. Bind UUID to canonical shared root, feature/worktree and roster fingerprint.

- Implement begin_execution: acquire worktree ownership, retrieve strict durable history first, reconstruct inherited exclusions, then probe only eligible candidates. Record actual probe failures and begin metadata through TASK-3274.

- Make repeated begin idempotent for matching live scope/config, reject second active UUID on the same canonical worktree, and expose scope/config/closed errors.

- Move plan caches and rotation into the TASK-3276 pool. Plans carry execution_id/generation/full pool view; exhausted/history-unavailable states retain pending tasks and request worker fallback.

- Provide end_execution's in-memory busy/close guards and durable close semantics for settled executions. Full persisted resume/reconciliation is TASK-3282; no deployment before downstream lifecycle tasks land.

**NOT in scope**: Dispatch retry wiring, native reservation/reporting, full crash recovery and public MCP registration.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Execution registry, begin/end guards, history-gated startup and plans |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py` | MODIFY | Explicit model IDs, isolated history and begin-execution fixtures |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | Lifecycle and plan tests; later native assertions stay owned by the next task |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, CoderFailure
from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe, available_seats, ChunkAssigner
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:301` — Constructor holds process-wide seats/_assigner/_plan_cache; open() at 367 probes before any feature context.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:379` — _resolve_feature(feature, worktree) resolves canonical worktree and per-spec index; _scheduler_for at 448 uses TaskScheduler.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:457` — plan(feature, worktree) mutates assigner rotation; _cached_plan at 490 must preserve the last visible assignment.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py:67` — git_sandbox_feature returns worktree, branch, base_path, index_path; three_seat_roster at 120 currently has empty MCP models.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py:34` — test_engine_plan_from_real_index asserts pending/blocked and chunk assignments against a real temporary Git repository.

### Does NOT Exist

- Current engine has no begin/end or execution registry; these are new APIs.

- The previous code-feedback prerequisite is now committed at verified dev; do not recreate CoderFeedbackStore.

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

1. Use TASK-3274 store resolution off-loop and TASK-3276 private pool; validate feature/worktree binding before any model operation. Keep registry ownership changes atomic across concurrent begin calls.

2. Read history snapshot before invoking TASK-3277 RosterProbe.probe. On strict-read failure return fallback_required with suspension_history_unavailable and zero smoke calls.

3. Persist each new actual failed probe once with execution+probe identity; if writing fails mark degraded/fallback and do not continue speculative provider calls.

4. Require explicit execution_id on plan; preserve cached assignment stability without recomputing on run/prepare. Return empty chunks with pending/fallback rather than constructing an empty assigner.

5. Add a reusable begin helper/fake UTC clock/isolated store fixture in conftest; assign deterministic explicit synthetic model IDs. Avoid touching the user's real repository ledger in tests.

6. Initially cover no-inflight close and repeated begin in memory. TASK-3282 replaces restart assumptions with durable snapshot recovery; never expose a production-ready claim before the full feature is complete.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
async SddCoderEngine.begin_execution(feature: str, worktree: str, execution_id: str) -> ExecutionPoolView
async SddCoderEngine.end_execution(execution_id: str) -> ExecutionPoolView
async SddCoderEngine.plan(feature: str, worktree: str, execution_id: str) -> CoderPlan
```

### Bounded implementation checklist

- [ ] open and invalid/missing execution calls make zero model probes.

- [ ] Repeated begin does not clear exclusions or extend expiry; mismatched scope/config and closed UUIDs fail explicitly.

- [ ] A fresh execution uses all structured history even when history_max_tokens=0.

- [ ] Unavailable history gives fallback with pending tasks intact; independent worktrees have independent rotation/cache state.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-1, AC-4, AC-5, AC-6, AC-8, AC-12. Feature-wide criteria are shared with dependent tasks.

- [ ] open and invalid/missing execution calls make zero model probes.

- [ ] Repeated begin does not clear exclusions or extend expiry; mismatched scope/config and closed UUIDs fail explicitly.

- [ ] A fresh execution uses all structured history even when history_max_tokens=0.

- [ ] Unavailable history gives fallback with pending tasks intact; independent worktrees have independent rotation/cache state.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3279-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_begin_reads_history_before_probe`
- `test_begin_idempotent_scope_and_roster_binding`
- `test_same_worktree_has_single_execution_owner`
- `test_all_seats_exhausted`
- `test_plan_cache_is_execution_private`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py
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
8. On completion move this file to `sdd/tasks/completed/TASK-3279-coder-engine-execution-lifecycle.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
