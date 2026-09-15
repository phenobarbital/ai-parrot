# TASK-3285: Complete offline execution-pool regression and acceptance coverage

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (3-4h)
**Depends-on**: TASK-3284
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3284 prompt/documentation completion and transitively all runtime tasks. This is the full feature gate, not an artificial ordering edge: it checks final MCP/prompt agreement and shared regression files.

## Context

Implements M5; all §4 integration scenarios and §5 acceptance gates. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Extend TASK-3282 integration file to cover every spec §4 integration scenario with real temporary Git worktrees, isolated ledger roots, fake dispatchers and an aware fake clock.

- Prove a fake Codex timeout bars that exact model from all later chunks/retries, and that fresh engine/new execution during cooldown filters it before any smoke call.

- Cover A/B/C overlap semantics, expiry in a new versus existing execution, alias races, busy retries, closed/restarted UUIDs, cleanup isolation and unresolved native children.

- Migrate remaining tests only in the declared files to explicit UUIDs/model IDs/execution-qualified branch names; preserve prior lint, feedback, scheduling and telemetry assertions.

- Add automated prompt/schema consistency checks after TASK-3284; verify missing execution and degraded persistence cannot create paid calls.

- Run the complete offline sdd_coder suite plus ledger regression tests and scoped formatting/lint checks. Record AC coverage and logs; report source defects for their owning task rather than editing undeclared runtime files.

**NOT in scope**: Runtime bug fixes outside declared test scope, dispatcher stdin hotfix tests, new dependencies and live-provider benchmarks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py` | MODIFY | Timeout-next-chunk, new execution, races and prompt/schema cross-checks |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py` | MODIFY | Migrate existing chunk tests to explicit executions and new branch names |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Finish execution-aware migration of pre-existing dispatch tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | Finish execution-aware migration of plan/native/merge tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | Finish MCP adapter feedback call migration after protocol lands |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py` | MODIFY | Finish new-identity telemetry regression coverage |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py` | MODIFY | Final shared fixtures for two independent worktrees and fake clocks |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
from parrot.knowledge.wiki.ledger.log import LedgerLog
```

### Existing Signatures to Use

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py:35` — CommittingFakeDispatcher(mode='ok|fail|extra|dirty') and make_builder at 71 use real temporary Git commits.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py:18` — FakeDispatcher records calls; its blocking mode can use asyncio.Event to test reservations.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py:67` — git_sandbox_feature creates a five-task dependency DAG; TASK-3279 extends isolated store and explicit begin fixtures.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py:273` — test_feedback_tool_validates_source_through_mcp_adapter exercises actual adapter calls; update its required arguments.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py:20` — _row and TestProjection test historical row construction; preserve compatibility assertions.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:43` — Final registered schemas from TASK-3283 must agree with both TASK-3284 prompt copies.

### Does NOT Exist

- There is no existing cross-execution integration suite before TASK-3282; this task extends it, not creates it again.

- Missing historical measurements are not zero-correction evidence and test-only skips must not fake usage attempts.

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

1. Use immediate wrapped TimeoutError and invocation counters, never a real provider/deadline. Mark earlier tasks complete through the fixture index when advancing waves so next-chunk checks exercise real scheduling.

2. Start B before A's failure on a separate feature worktree and C only after durable append. Assert B's startup snapshot unchanged and C's exact key excluded before smoke.

3. Advance injected UTC clock to exact expiry boundaries. Original UUID keeps own/inherited bans; a new UUID may probe. Repeat record/begin/status and prove timestamps do not refresh.

4. Exercise failed append/read/partial-tail, zero-token summary, active native suspension and restart reconciliation with barriers and real on-disk store instances.

5. Compare registered tool schemas and both worker lifecycle sections without calling any provider. Keep historical telemetry/feedback samples readable.

6. Run pytest for packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ and the verified existing ledger tests listed below; black --check and ruff check only feature-owned Python files; git diff --check. Save logs under artifacts/logs/feat559-*.log.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
Test fixture protocol: explicit model roster + isolated CoderSuspensionStore + stable UUID + injectable aware UTC clock
Test race protocol: asyncio.Event/barrier, no sleeps or live provider probes
```

### Bounded implementation checklist

- [ ] All §4 required scenarios have named executable assertions; AC-1 through AC-15 map to passing evidence.

- [ ] Zero later invocations of the suspended model within the same execution or a new run's active cooldown.

- [ ] Full offline package suite and ledger regressions pass without QuerySource writes, network access or credentials.

- [ ] Black/scoped Ruff/git diff --check results and any pre-existing baseline findings are recorded accurately; do not weaken tests to mask a failure.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15. Feature-wide criteria are shared with dependent tasks.

- [ ] All §4 required scenarios have named executable assertions; AC-1 through AC-15 map to passing evidence.

- [ ] Zero later invocations of the suspended model within the same execution or a new run's active cooldown.

- [ ] Full offline package suite and ledger regressions pass without QuerySource writes, network access or credentials.

- [ ] Black/scoped Ruff/git diff --check results and any pre-existing baseline findings are recorded accurately; do not weaken tests to mask a failure.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3285-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_timeout_then_next_chunk`
- `test_new_execution_uses_durable_history`
- `test_new_execution_after_expiry`
- `test_overlapping_workers_isolated`
- `test_all_seats_exhausted`
- `test_model_aliases_and_parallel_admission`
- `test_review_and_feedback_coexist`
- `test_legacy_history_and_telemetry`
- `test_mcp_and_prompt_twins`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

The final gate additionally runs the entire package suite and the existing ledger regression files
(read and verified during decomposition; read-only test dependencies, not edit targets):

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q
pytest tests/knowledge/wiki/test_ledger_events.py tests/knowledge/wiki/test_ledger_log.py tests/knowledge/wiki/test_ledger_service.py tests/knowledge/wiki/test_ledger_integration.py -q
```

### Feature acceptance ownership

| Criteria | Primary implementation / verification owners |
|---|---|
| AC-1, AC-4, AC-8, AC-12 | TASK-3274, TASK-3275, TASK-3277, TASK-3279, TASK-3283, TASK-3284 |
| AC-2, AC-3, AC-5, AC-9 | TASK-3274, TASK-3276, TASK-3280, TASK-3282 |
| AC-6, AC-7, AC-10 | TASK-3276, TASK-3281, TASK-3282 |
| AC-11 | TASK-3275, TASK-3278, TASK-3280, TASK-3281, TASK-3283 |
| AC-13, AC-14 | TASK-3280, TASK-3285 |
| AC-15 | TASK-3283, TASK-3284, TASK-3285 |

This task verifies all criteria end to end; the owners above retain responsibility for runtime fixes.

Targeted migration checks:

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py -q
black --check packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py
ruff check packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py
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
8. On completion move this file to `sdd/tasks/completed/TASK-3285-coder-pool-regression-suite.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
