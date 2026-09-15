# TASK-3271: Dispatch exclusive tasks alone in development pool rounds

**Feature**: FEAT-560 - Dev-Loop Pool Honours Exclusive Tasks
**Spec**: `sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3269
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Imports partition_wave and parallel_width from TASK-3269 (task_scheduler.py). Owns development.py and test_development_node.py; no write overlap with roster or planner tasks.

## Context

Implement spec §3 Module 3. The pool currently gathers the full ready wave; exclusive tasks must execute alone and changes must be integrated before re-planning.

## Scope

- Use parallel_width(wave) >= 2 in should_fan_out while retaining the effective-slot check.
- Each _execute_pool round obtains the current next_wave, exits if empty, and dispatches only partition_wave(wave)[0].
- Mark results, await merge_sequential and refresh_all in isolated mode, then re-plan; never dispatch cached later batches.
- Keep Wave progress wording and report the actual dispatched batch. Exclusive rounds must log the word exclusive and the task id.
- Preserve cleanup, aggregation, session_host, escalation, partial/all-failure behavior and existing public signatures.

**NOT in scope**: DevAgentPool.run_wave implementation, worktree-manager code, shared models, QA repair re-entry, _collapse_for_single_task and planner sizing.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | Dispatch one batch per round and use parallel width |
| `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py` | MODIFY | Cover exclusive rounds, failure propagation, merge ordering and legacy behavior |

## Codebase Contract (Anti-Hallucination)

Verified against dev on 2026-09-16. Re-read these references before implementation;
refresh this contract if a dependency changes it. Verify any additional API before use.

### Verified Imports

```python
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler  # nodes/development.py:62
from parrot.flows.dev_loop.agent_pool import DevAgentPool, WaveResult, aggregate_outputs  # nodes/development.py:41
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager  # nodes/development.py:63
from parrot.flows.dev_loop.nodes import development as development_module  # tests/test_development_node.py:29
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:77` — should_fan_out(wave: List[TaskRef], pool_cfg: DevAgentPoolConfig) -> bool; effective slots sum spec.count.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:1364` — DevelopmentNode._execute_pool(self, shared: Dict[str, Any], research: ResearchOutput, pool_cfg: DevAgentPoolConfig, scheduler: TaskScheduler) -> DevelopmentOutput is async.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:1477` — Current loop: next_wave, run_wave (1497), mark_done/mark_failed (1507-1510), merge_sequential (1525), refresh_all (1531), cleanup in finally.
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:214` — mark_done(self, task_id: str) -> None; mark_failed(self, task_id: str) -> None (223) propagates skipped transitively.
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py:435` — async run_wave(self, tasks: List[TaskRef], *, research: ResearchOutput, run_id: str, cwd_for: Callable[[str], str], escalate: bool = False, session_host: Optional[Any] = None) -> WaveResult.
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py:119` — WaveResult dataclass fields: completed: Dict[str, DevelopmentOutput], failed: List[str], worker_summaries: List[WorkerSummary].
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:181` — async merge_sequential(self, *, resolver: Optional[Resolver] = None) -> MergeReport; async refresh_all(self) -> None (264).
- `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py:73` — _write_index(worktree_path: Path, feat_id: str, feature_slug: str, tasks: list) -> None currently writes a legacy index.
- `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py:129` — FakeManager records merge/refresh counts and cleanup; extend local test doubles with an event trace to assert temporal order.
- `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py:185` — _task_ref(task_id: str) -> TaskRef; TestShouldFanOut at 189 and TestPoolPath at 661 provide existing fixtures.

### Does NOT Exist

- partition_wave and parallel_width are created by TASK-3269; re-verify their signatures before implementation.
- DevAgentPool.run_exclusive(), WaveResult.exclusive, TaskRef.exclusive and DevAgentPoolConfig.respect_exclusive do not exist; do not add them.

## Implementation Notes

Imports partition_wave and parallel_width from TASK-3269 (task_scheduler.py). Owns development.py and test_development_node.py; no write overlap with roster or planner tasks.

Keep changes limited to declared files. Follow AGENTS.md; add no dependencies.
Preserve existing public signatures and use the repository logging conventions.
Read-only reference files are not additional write targets.

## Implementation Blueprint

### Steps (in order)

1. Import both helpers and replace only the fan-out width check, retaining pool slot semantics and its advisory role.
2. Inside the existing while loop, select the first partition batch after the empty-wave guard. Use that batch consistently for run_wave, log labels and progress counts.
3. Add exclusive-round logging without changing normal parallel-round wording. Keep result recording, merge/refresh and finally cleanup in the current sequence.
4. Extend local index fixtures with an optional header that defaults to legacy behavior. Use real TaskScheduler instances plus fake pool results to capture dispatch arguments and ordering.
5. Verify an exclusive success can unblock a new task for the immediately next round; verify failure skips dependents without preventing independent work.
6. Run targeted development tests. Once all feature tasks land, run the complete spec AC-8 suite as the feature integration gate.

This blueprint fixes the scope and sequence; implement in the existing files without
replacing their unrelated contents. No Delegation Contract is supplied: the normal
implementation route owns the bounded code and test details.

## Acceptance Criteria

- [ ] AC-1/2: every exclusive dispatch is a singleton, ascending-id exclusive tasks run first, and every round re-plans.
- [ ] AC-3/4: use shared helpers; exclusive-only waves do not fan out.
- [ ] AC-5: legacy indexes still dispatch the entire ready wave per round with unchanged pool-slot decisions and ordinary log wording.
- [ ] AC-6: isolated merge and refresh complete before the next dispatch, including after an exclusive round.
- [ ] AC-7: exclusive logs identify both exclusive and the task id; progress counts match the dispatched batch.
- [ ] AC-8/9/11: tests and quality checks pass; run_wave, _execute_pool and should_fan_out signatures stay unchanged.

## Test Specification

- test_should_fan_out_ignores_exclusive_tasks: [X1,P2] with two slots is False; [X1,P2,P3] is True; exclusive-only is False.
- test_execute_pool_runs_exclusive_task_alone: assert run_wave receives [X1], then [P2,P3]; also exercise multiple exclusive tasks and immediate re-planning after newly unblocked work.
- test_execute_pool_merges_after_exclusive_round: assert event trace run(X1), merge, refresh, run(next batch), merge, refresh; counts alone are insufficient.
- test_execute_pool_failed_exclusive_task_skips_dependents: X1 fails, transitive dependents never dispatch, independent parallel tasks complete.
- test_execute_pool_legacy_index_dispatches_whole_wave: header omitted, including legacy parallel:false flags, all ready tasks remain in one call.
- Capture exclusive-round logs and progress to check task id and actual batch size; preserve existing cleanup, aggregation and session-host tests.

### Validation

Run in the activated project environment and save test output under
`artifacts/logs/task-3271.log`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/test_development_node.py -v
black --line-length 120 packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py packages/ai-parrot/tests/flows/dev_loop/test_development_node.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py packages/ai-parrot/tests/flows/dev_loop/test_development_node.py
```

## Feature Integration Gate (after all tasks land)

Spec AC-8 requires the following full suite; this is a closeout check, not an added
implementation dependency on the roster, planner or documentation tasks:

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py packages/ai-parrot/tests/flows/dev_loop/test_development_node.py packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py packages/ai-parrot/tests/flows/dev_loop/test_agent_pool.py packages/ai-parrot/tests/flows/dev_loop/integration -v
```

Save output to `artifacts/logs/feat-560-integration.log`. Also verify AC-3 across
all changed source: exclusive/parallel classification is centralized in
`task_scheduler.py`. The scheduler currently returns an unordered ready set;
the spec explicitly requires sorted partition output. Regression tests must
check full legacy-wave dispatch and unchanged round counts, and must not assume
an undocumented ordering from `TaskScheduler.next_wave()`.

## Output

1. Implement and validate only this task's declared scope.
2. Move this artifact to `sdd/tasks/completed/TASK-3271-pool-exclusive-dispatch-rounds.md`.
3. Update this task in `sdd/tasks/index/dev-loop-pool-exclusive-tasks.json` with status, assignment/completion timestamps,
   and completed artifact path; do not use the historical monolithic index.
4. Add the completion evidence below and commit the scoped code plus SDD state.

## Completion Note

Pending implementation.
