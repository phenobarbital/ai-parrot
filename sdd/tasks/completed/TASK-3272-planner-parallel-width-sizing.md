# TASK-3272: Size the planner pool from parallel wave width

**Feature**: FEAT-560 - Dev-Loop Pool Honours Exclusive Tasks
**Spec**: `sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-3269
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Imports parallel_width from TASK-3269 (task_scheduler.py). Owns planner.py and test_planner_node.py; may run with TASK-3270 and TASK-3271 after the helper exists.

## Context

Implement spec §3 Module 4. Provision only the concurrent capacity of wave 1, without counting exclusive tasks as parallel work.

## Scope

- Replace max(1, len(wave)) with max(1, parallel_width(wave)) in _resolve_pool.
- Retain development_pool_max cap, brief overrides, missing-index fallback, configured-backend distribution and log wording.
- Add header-aware index-backed sizing tests and keep the legacy fixtures defaulting to no header.

**NOT in scope**: Maximum capacity across future waves, backend-selection policy, development dispatch and model schema changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py` | MODIFY | Use parallel_width for derived pool count |
| `packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py` | MODIFY | Cover exclusive, mixed and legacy pool sizing |

## Codebase Contract (Anti-Hallucination)

Verified against dev on 2026-09-16. Re-read these references before implementation;
refresh this contract if a dependency changes it. Verify any additional API before use.

### Verified Imports

```python
from parrot.flows.dev_loop.task_scheduler import TaskScheduler  # nodes/planner.py:50
from parrot.flows.dev_loop.nodes.planner import PlannerNode  # tests/test_planner_node.py:20
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py:287` — async PlannerNode._resolve_pool(self, brief: FeatureBrief, planner_out: PlannerOutput) -> DevAgentPoolConfig.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py:336` — wave = scheduler.next_wave(); width = max(1, len(wave)); count = min(width, self._pool_max).
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:196` — TaskScheduler.next_wave(self) -> List[TaskRef]; TASK-3269 adds parallel_width(wave: Sequence[TaskRef]) -> int.
- `packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py:33` — _write_index(tmp_path: Path, slug: str, tasks: list[dict]) -> Path; _brief (41), _planner_output (52), _node (65).
- `packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py:167` — Existing brief-override, capped-width (185) and single-task (209) tests call _resolve_pool.

### Does NOT Exist

- parallel_width does not exist until TASK-3269 lands.
- DevAgentPoolConfig.respect_exclusive does not exist. There is no all-waves capacity helper to introduce here.

## Implementation Notes

Imports parallel_width from TASK-3269 (task_scheduler.py). Owns planner.py and test_planner_node.py; may run with TASK-3270 and TASK-3271 after the helper exists.

Keep changes limited to declared files. Follow AGENTS.md; add no dependencies.
Preserve existing public signatures and use the repository logging conventions.
Read-only reference files are not additional write targets.

## Implementation Blueprint

### Steps (in order)

1. Verify the helper from TASK-3269 and extend the task_scheduler import.
2. Update the unique width assignment in _resolve_pool; clarify its docstring to describe parallel width of wave 1.
3. Extend the local test index helper with an optional exclusive header preserving its existing default.
4. Add parameterized sizing cases and verify the sum of agent counts, cap and brief override; run existing planner tests.

This blueprint fixes the scope and sequence; implement in the existing files without
replacing their unrelated contents. No Delegation Contract is supplied: the normal
implementation route owns the bounded code and test details.

## Acceptance Criteria

- [ ] AC-4: exclusive-only wave sizes one slot; mixed wave sizes the number of parallel tasks.
- [ ] AC-5: legacy count and capped sizing remain unchanged.
- [ ] AC-9/11: formatting/lint checks pass and _resolve_pool signature stays unchanged.

## Test Specification

- test_resolve_pool_counts_only_parallel_tasks: [X1,X2] -> 1; [X1,P2,P3] -> 2; legacy three-task wave -> 3 or configured cap.
- Check empty wave -> one slot, cap=1, and brief override precedence.
- Run existing planner suite, including capped-width and configured fallback behavior.

### Validation

Run in the activated project environment and save test output under
`artifacts/logs/task-3272.log`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py -v
black --line-length 120 packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py
```

## Output

1. Implement and validate only this task's declared scope.
2. Move this artifact to `sdd/tasks/completed/TASK-3272-planner-parallel-width-sizing.md`.
3. Update this task in `sdd/tasks/index/dev-loop-pool-exclusive-tasks.json` with status, assignment/completion timestamps,
   and completed artifact path; do not use the historical monolithic index.
4. Add the completion evidence below and commit the scoped code plus SDD state.

## Completion Note

`PlannerNode._resolve_pool` now imports `parallel_width` from
`task_scheduler.py` (TASK-3269) and replaces `max(1, len(wave))` with
`max(1, parallel_width(wave))`, preserving the `development_pool_max`
cap and brief-override precedence. Docstring updated to describe
parallel width of wave 1.

Code review: 1 confirmed defect, fixed in commit
`73a6c6d72366747a4a42d013bb257bf3cd5fc291`. The 3 new pool-sizing tests
(`test_pool_sizing_exclusive_only`, `test_pool_sizing_mixed_wave`,
`test_pool_sizing_exclusive_with_cap`) wrote `"parallel": false` via the
legacy `_write_index` helper, which never emits the required
`"parallel_semantics": "exclusive"` header, so every task defaulted
back to `parallel=True`. 2 of the 3 failed outright when actually run
(`exclusive_only` expected count==1, got 2; `mixed_wave` expected
count==2, got 3); the cap test passed by coincidence (the cap masked
the wrong width). The delivery's own summary noted tests could not be
run locally (missing `.so` in the sub-worktree), so this went
unverified before merge. Added an `exclusive: bool` kwarg to
`_write_index` and set it on the 3 call sites that need real exclusive
semantics. Feedback recorded:
`coder-feedback:bd9fae3f475c60d38b590a3e`.

Verification: re-ran `test_planner_node.py` — all pass (was 2 failing).
Residual ruff findings from the engine's lint pass
(`planner.py:162` ASYNC240, `planner.py:375` B905) are pre-existing
style debt outside this task's diff scope; left for `/sdd-done`'s
feature-wide lint pass per the fallback loop's own rule.

Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 218.2s · Tokens: 1085760/7117
