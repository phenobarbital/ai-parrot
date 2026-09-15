# TASK-3269: Add shared exclusive-wave partition and width helpers

**Feature**: FEAT-560 - Dev-Loop Pool Honours Exclusive Tasks
**Spec**: `sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: No dependencies: owns task_scheduler.py and its tests; only adds pure helpers, with no shared resource mutation. Can run alongside TASK-3273 documentation.

## Context

Implement spec §3 Module 1. Centralize the exclusive/parallel partition so both execution lanes and pool sizing use one definition.

## Scope

- Add partition_wave(wave: Sequence[TaskRef]) -> list[list[TaskRef]] and parallel_width(wave: Sequence[TaskRef]) -> int beside TaskRef.
- Sort by TaskRef.id; return one singleton per exclusive task first, then one sorted parallel batch. Return [] for an empty wave.
- Return the number of parallel tasks as width; return 1 for nonempty exclusive-only waves and 0 for empty waves.
- Keep TaskScheduler loading, dependency resolution and TaskRef fields unchanged.

**NOT in scope**: Pool dispatch, roster integration, planner sizing and documentation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` | MODIFY | Add module-level pure helpers |
| `packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py` | MODIFY | Add partition and width tests |

## Codebase Contract (Anti-Hallucination)

Verified against dev on 2026-09-16. Re-read these references before implementation;
refresh this contract if a dependency changes it. Verify any additional API before use.

### Verified Imports

```python
from parrot.flows.dev_loop.task_scheduler import TaskScheduler  # tests/test_task_scheduler.py:9
from pydantic import BaseModel, Field  # task_scheduler.py:20
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:32` — TaskRef(BaseModel): id: str, title: str, status: str, depends_on: List[str], file: str; parallel: bool defaults to True (line 58).
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:29` — PARALLEL_SEMANTICS_EXCLUSIVE = "exclusive".
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:104` — TaskScheduler.from_index_file(cls, path: Path) -> Optional["TaskScheduler"] reads parallel only under the exclusive header.
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:196` — TaskScheduler.next_wave(self) -> List[TaskRef] returns ready tasks in no particular order.
- `packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py:155` — _index(tmp_path, header: dict) -> TaskScheduler provides header-driven fixtures; legacy/exclusive tests are at lines 167 and 173.

### Does NOT Exist

- partition_wave and parallel_width do not exist yet; this task creates them as module-level functions.
- TaskRef.exclusive, TaskScheduler.next_batch() and TaskScheduler.exclusive() do not exist and must not be added.

## Implementation Notes

No dependencies: owns task_scheduler.py and its tests; only adds pure helpers, with no shared resource mutation. Can run alongside TASK-3273 documentation.

Keep changes limited to declared files. Follow AGENTS.md; add no dependencies.
Preserve existing public signatures and use the repository logging conventions.
Read-only reference files are not additional write targets.

## Implementation Blueprint

### Steps (in order)

1. Add Sequence to the module typing imports and define the two public helpers near TaskRef, with strict type hints and Google-style docstrings.
2. Partition a sorted copy of the input into exclusive singletons and the nonempty parallel batch; do not mutate the caller sequence or task objects.
3. Compute parallel_width from the shared semantics, preserving the specified empty and exclusive-only cases.
4. Extend the existing test module using TaskRef fixtures and parameterized cases; keep header-loading regression tests unchanged.

This blueprint fixes the scope and sequence; implement in the existing files without
replacing their unrelated contents. No Delegation Contract is supplied: the normal
implementation route owns the bounded code and test details.

## Acceptance Criteria

- [ ] AC-2/3 foundation: deterministic exclusive-first batches are available for downstream consumers.
- [ ] All-parallel inputs produce exactly one sorted batch; empty inputs produce no batches.
- [ ] Width matches every case in spec §4; existing legacy header behavior is preserved.
- [ ] AC-9/11: typed pure helpers, formatting/lint checks pass; existing signatures are unchanged.

## Test Specification

- test_partition_wave_all_parallel_is_one_sorted_batch: shuffled parallel tasks produce one ascending-id batch.
- test_partition_wave_exclusive_first_each_alone: [P3, X2, P1, X4] produces [[X2], [X4], [P1, P3]].
- test_partition_wave_only_exclusive: [X2, X1] produces [[X1], [X2]].
- test_partition_wave_empty: [] produces [].
- test_parallel_width: parameterize all-parallel, mixed, exclusive-only and empty cases.
- Assert caller input ordering is not mutated and existing header semantics tests still pass.

### Validation

Run in the activated project environment and save test output under
`artifacts/logs/task-3269.log`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py -v
black --line-length 120 packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py
```

## Output

1. Implement and validate only this task's declared scope.
2. Move this artifact to `sdd/tasks/completed/TASK-3269-exclusive-wave-helpers.md`.
3. Update this task in `sdd/tasks/index/dev-loop-pool-exclusive-tasks.json` with status, assignment/completion timestamps,
   and completed artifact path; do not use the historical monolithic index.
4. Add the completion evidence below and commit the scoped code plus SDD state.

## Completion Note

Added `partition_wave` and `parallel_width` as module-level pure helpers in
`task_scheduler.py`, beside `TaskRef`. `partition_wave` sorts a copy of the
input wave by `TaskRef.id`, returns one singleton batch per exclusive task
(ascending id) followed by a single sorted parallel batch, and `[]` for an
empty wave; the caller's input ordering is not mutated. `parallel_width`
returns the count of parallel tasks, `1` for a nonempty exclusive-only wave,
and `0` for an empty wave. `TaskScheduler` loading, dependency resolution
and `TaskRef` fields are unchanged.

Added 9 new tests in `test_task_scheduler.py` (`TestPartitionWave`,
`TestParallelWidth`) covering all-parallel, exclusive-first, exclusive-only,
empty, and input-order-preservation cases; all 24 tests in the module pass
(15 pre-existing + 9 new). Validated with `black --line-length 120` and
`ruff check` on both changed files.

Code review: PASS. Re-ran
`pytest packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py -v`
in this worktree (24/24 passed) — no corrections needed.

Seat: glm · Backend: nova · Model: zai.glm-4.7-flash · Attempts: 1 · Duration: 222.8s · Tokens: 1527884/4127
