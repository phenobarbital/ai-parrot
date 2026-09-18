# TASK-3270: Use the shared wave partition in ChunkAssigner

**Feature**: FEAT-560 - Dev-Loop Pool Honours Exclusive Tasks
**Spec**: `sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-3269
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Imports partition_wave from TASK-3269 (task_scheduler.py). Owns only sdd_coder/roster.py; may run alongside TASK-3271 and TASK-3272 after the helper lands.

## Context

Implement spec §3 Module 2: preserve the sdd-coder engine behavior while removing its duplicate exclusive/shared partition.

## Scope

- Import partition_wave from task_scheduler and use it in ChunkAssigner.assign.
- Split each returned batch into chunks of at most len(seats), retaining singleton exclusive batches.
- Preserve chunk indexes, task-file fallback, seat mapping, native flags and rotation of the starting seat once per emitted chunk.
- Run the existing roster suite unchanged, including exclusive ordering and seat rotation coverage.

**NOT in scope**: Scheduler helpers, pool node, planner node, roster retry logic and changes to existing tests.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py` | MODIFY | Replace inline partition with the shared helper |

## Codebase Contract (Anti-Hallucination)

Verified against dev on 2026-09-16. Re-read these references before implementation;
refresh this contract if a dependency changes it. Verify any additional API before use.

### Verified Imports

```python
from parrot.flows.dev_loop.task_scheduler import TaskRef  # sdd_coder/roster.py:10
from parrot.flows.dev_loop.sdd_coder import ChunkAssigner, RosterConfig, RosterProbe, RosterSeat, available_seats  # tests/sdd_coder/test_roster.py:6
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:134` — ChunkAssigner.assign(self, wave: List[TaskRef], task_files: Dict[str, str]) -> List[PlanChunk]. Current split is at lines 146-148.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:126` — ChunkAssigner retains self._seats and self._start; start advances by one per emitted chunk.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py:9` — _roster(n), _wave(n) (line 19), rotation test (line 31), exclusive-ordering test (line 86).
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:58` — TaskRef.parallel is the exclusivity source; TASK-3269 adds partition_wave(wave: Sequence[TaskRef]) -> list[list[TaskRef]].

### Does NOT Exist

- partition_wave is absent at decomposition time; verify TASK-3269 has landed before importing it.
- TaskRef.exclusive and TaskScheduler.next_batch() do not exist.

## Implementation Notes

Imports partition_wave from TASK-3269 (task_scheduler.py). Owns only sdd_coder/roster.py; may run alongside TASK-3271 and TASK-3272 after the helper lands.

Keep changes limited to declared files. Follow AGENTS.md; add no dependencies.
Preserve existing public signatures and use the repository logging conventions.
Read-only reference files are not additional write targets.

## Implementation Blueprint

### Steps (in order)

1. Extend the existing task_scheduler import with partition_wave after verifying TASK-3269.
2. Replace ordered/exclusive/shared list construction with partition_wave(wave), subdividing batches by seat count.
3. Keep the existing PlannedTask construction and rotation loop intact, and update the assign docstring to identify the shared partition.
4. Run test_roster.py unchanged; inspect that the inline exclusive split was removed.

This blueprint fixes the scope and sequence; implement in the existing files without
replacing their unrelated contents. No Delegation Contract is supplied: the normal
implementation route owns the bounded code and test details.

## Acceptance Criteria

- [ ] AC-3: ChunkAssigner obtains dispatch batches through partition_wave without duplicating exclusive classification.
- [ ] AC-5/11: existing chunk ordering, seat rotation and public signature remain unchanged.
- [ ] AC-8/9: unchanged roster suite and source formatting/lint checks pass.

## Test Specification

- Run the unchanged parameterized distinct-seats suite, single-seat case, rotation test and test_assign_exclusive_tasks_run_alone_and_first.
- Do not weaken existing assertions or edit test_roster.py for this behavior-preserving task.

### Validation

Run in the activated project environment and save test output under
`artifacts/logs/task-3270.log`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -v
black --line-length 120 packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py
```

## Output

1. Implement and validate only this task's declared scope.
2. Move this artifact to `sdd/tasks/completed/TASK-3270-roster-shared-wave-partition.md`.
3. Update this task in `sdd/tasks/index/dev-loop-pool-exclusive-tasks.json` with status, assignment/completion timestamps,
   and completed artifact path; do not use the historical monolithic index.
4. Add the completion evidence below and commit the scoped code plus SDD state.

## Completion Note

`ChunkAssigner.assign` in `roster.py` now imports and uses
`partition_wave` from `task_scheduler.py` (TASK-3269) instead of its
duplicated inline exclusive/shared classification. Each batch returned
by `partition_wave` is subdivided into chunks of at most `len(seats)`
tasks; singleton exclusive batches, chunk indexes, task-file fallback,
seat mapping, native flags, and starting-seat rotation are all
preserved. Attempt 1 (mistral) hit a `dirty_task_worktree` error from an
unrelated modified `Cargo.lock` in its sub-worktree and was discarded;
attempt 2 (qwen) delivered cleanly and merged.

Code review: PASS. Re-ran
`pytest packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py
packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py` in the
full integration sweep (238 passed, 2 skipped) — no corrections needed
for this task's own diff.

Seat: qwen · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct · Attempts: 2 (1 discarded: dirty_task_worktree) · Duration: 131.9s · Tokens: 620383/4528
