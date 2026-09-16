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

**Delivered by**: MCP coder, seat `minimax` (backend `nova`, model `minimax.minimax-m2.5`),
attempt_uid `aa122ec28306468387c61cedc721fbbd`, commit e1910367da02ef546cda4510d09a09202dff1096 — 2026-09-16.
**Reviewed and corrected by**: sdd-worker (Sonnet 5 orchestrator) — 2026-09-16.

**Implementation summary**: `begin_execution()` reads durable suspension history via `CoderSuspensionStore`
before probing eligible candidates, binds `execution_id` to the canonical worktree (single-owner
`execution_in_progress` guard), builds an `ExecutionPool` with the resolved `initial_exclusions`, and marks
`fallback_required`/`all_seats_exhausted` when no seat remains eligible. `end_execution()` refuses while
attempts/reservations are in flight and releases worktree ownership. `plan()` gained an optional
`execution_id` kwarg that routes to the execution's private cached assigner (legacy `open()`/no-execution
path unchanged). Added `explicit_model_roster`/`fake_utc_clock`/`isolated_suspension_store` fixtures.

**Review findings (confirmed, fixed)**:
1. `begin_execution()` wrapped the already-`async def` `CoderSuspensionStore.recent()` in ANOTHER
   `asyncio.to_thread(...)` — this runs the coroutine *function* in a worker thread without awaiting the
   coroutine it returns, silently discarding the real result (`RuntimeWarning: coroutine 'recent' was never
   awaited`, then `TypeError: 'coroutine' object is not iterable`), caught by the broad `except` as a false
   `suspension_history_unavailable` — broke all 3 of this task's own new lifecycle tests.
2. A confirmed dead-code stub: the resume-path roster-fingerprint check compared
   `existing.roster_fingerprint` against `ExecutionPool.roster_fingerprint.__get__(existing, ExecutionPool)`
   — the exact same value — so it always evaluated "equal" and silently skipped the spec-mandated
   `execution_config_mismatch` error on a genuine mismatch. Fixed by exposing `pool.py`'s roster-fingerprint
   helper publicly (`roster_fingerprint()`, was `_roster_fingerprint` — **disclosed scope exception**: this
   touches `pool.py`, owned by the already-merged TASK-3276, not in this task's own declared file list; the
   change is a minimal, backward-compatible rename + one new call site, needed to compare the CURRENT
   roster's fingerprint against the pool's stored one without constructing a throwaway `ExecutionPool`) and
   comparing against the live `self.roster`, now correctly raising `execution_config_mismatch`.
3. 6 PRE-EXISTING tests (`test_engine_plan_from_real_index`, `test_engine_plan_is_deterministic`,
   `test_engine_plan_dependency_cycle`, `test_engine_rejects_worktree_outside_base`,
   `test_engine_feature_not_found`, `test_engine_orphans_listed_not_merged`) broke as collateral from
   TASK-3277's (already-merged) mandatory `model_identity_required` rule: they used the shared
   `three_seat_roster` fixture (empty `model` fields), now correctly always excluded before any probe.
   Switched them to THIS task's own `explicit_model_roster` fixture rather than editing the shared
   `three_seat_roster` (also used by `test_toolkit.py`/`test_integration_chunk.py`, outside this task's
   scope — left untouched).
4. Two of this task's own new tests had authoring bugs: `test_plan_cache_is_execution_private` began TWO
   execution_ids on the SAME worktree, contradicting the single-owner invariant
   `test_same_worktree_has_single_execution_owner` already asserts — now ends the first execution before
   beginning the second, preserving the actual intent (private per-execution plan caches).
   `test_all_seats_exhausted`'s `SuspensionRecord` was missing the required `attempt_uid` field and used
   `now.replace(second=now.second + 1800)` (seconds must be 0..59) instead of
   `now + timedelta(seconds=...)`.

**Known, disclosed, OUT-OF-SCOPE collateral (not fixed here)**: running the full `sdd_coder` test directory
surfaces 20 additional failures in `test_engine_dispatch.py`, `test_feedback.py`
(`test_mcp_retry_refreshes_feedback_for_each_model`), `test_integration_chunk.py` and `test_toolkit.py` —
all trace to TASK-3275's mandatory `JobTable.create(execution_id=...)` / `CoderPlanArgs.execution_id` and
TASK-3277's `model_identity_required` rule, in files NOT in this task's (or TASK-3276/3277/3278's) declared
scope. `test_engine_dispatch.py` is explicitly TASK-3280's scope ("Execution-bound run_chunk/attempts...");
`test_toolkit.py` is TASK-3283's ("coder-pool-mcp-protocol"). Flagged for verification when those tasks are
consolidated, and again at TASK-3285's final regression gate.

**Verification evidence**:
- `pytest test_engine_plan_merge.py -q` → 21 passed (was 11 passed / 10 failed).
  Log: `artifacts/logs/task-3279-pytest.log`.
- `ruff check` → clean except pre-existing `lint.residual` (ASYNC240×5, B905×1, already flagged by the
  engine's own lint pass at delivery time, deferred to `/sdd-done`'s feature-wide pass per policy).
  `black --check` → clean. Logs: `artifacts/logs/task-3279-ruff.log`, `artifacts/logs/task-3279-black.log`.
- `git diff --check` → clean.
- Model feedback recorded: `coder-feedback:cb2d17c6b108dff24d5288da` (pattern
  `double-to-thread-on-async-def`, model `nova/minimax.minimax-m2.5`).
- Review measurement recorded: `coder-review:96fa5a89d43d3a583d4ec37f`, fix commit
  `7d49150abb0af3898407fe52553391b02ca5f562`.

Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 (MCP) + 1 (orchestrator review fix)
· Duration: 414.5s (MCP attempt) · Tokens: 3,086,422 in / 14,599 out (MCP attempt)
