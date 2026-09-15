---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Dev-Loop Pool Honours Exclusive Tasks

**Feature ID**: FEAT-560
**Date**: 2026-09-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor of `ai-parrot`

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Since 2026-09-15 a per-spec task index can declare **exclusive** tasks: when the
index header carries `"parallel_semantics": "exclusive"`, a task with
`parallel: false` mutates shared state outside its declared files (a Cython /
maturin rebuild, a lockfile or `pyproject.toml` edit, DDL against a shared
database, a `conftest.py` other tasks load) and must **never run concurrently
with any other task**, even when its `depends_on` are satisfied. The rules are
written in `/sdd-task` ("Task graph rules") and checked by
`scripts/sdd/check_task_graph.py`.

`TaskScheduler.from_index_file` already surfaces this as `TaskRef.parallel`
(always `True` for legacy indexes without the header), and the `sdd-coder` MCP
engine already honours it: `ChunkAssigner.assign` puts each exclusive task alone
in its own chunk, first.

The **dev-loop feature-mode flow does not**. Its multi-agent pool dispatches a
whole `TaskScheduler.next_wave()` at once:

- `DevelopmentNode._execute_pool` passes the full wave to `DevAgentPool.run_wave`,
  which `asyncio.gather`s one dispatch per task — an exclusive task runs next to
  every other task of its wave.
- `should_fan_out` counts exclusive tasks as parallel work.
- `PlannerNode._resolve_pool` sizes the pool from the raw wave-1 width, so a
  wave of exclusive tasks provisions seats that can never be used together.

The same index therefore behaves differently depending on which lane runs it:
safe under `sdd-worker` + `parrot-sdd-coder`, unsafe under the dev-loop flow.

### Goals
- G1: In the dev-loop pool path, an exclusive task is dispatched in a round that
  contains no other task (no concurrent `_dispatch_one` for any other task).
- G2: Dispatch order is identical to the `sdd-coder` engine's: within a wave,
  exclusive tasks first, one per round, ascending id; then all parallel tasks
  of the wave together.
- G3: One pure, shared definition of that partition (`partition_wave`) used by
  both `ChunkAssigner` and `DevelopmentNode`, so the two lanes cannot drift.
- G4: Pool sizing (`PlannerNode._resolve_pool`) and the fan-out hint
  (`should_fan_out`) count only tasks that can actually run together.
- G5: Legacy indexes (no `parallel_semantics` header) behave byte-for-byte as
  today — same rounds, same pool size, same logs.

### Non-Goals (explicitly out of scope)
- Changing what `parallel: false` means or how it is read — that is fixed by
  `TaskScheduler.from_index_file` and the `/sdd-task` rules.
- Running `check_task_graph.py` inside the dev-loop flow (PlannerNode already
  consumes an index produced by `/sdd-task`, which runs the check).
- File-overlap detection at runtime; overlapping tasks must already be
  serialized by `depends_on` (the checker's `file-overlap` error).
- Changes to `DevAgentPool.run_wave` itself: it keeps dispatching whatever list
  it is given concurrently.
- Telemetry, `DispatchLabels`, stream ids or `WorkerSummary` shape changes.

---

## 2. Architectural Design

### Overview

Add two pure helpers next to `TaskRef` in `task_scheduler.py`:

- `partition_wave(wave)` → ordered dispatch batches: each exclusive task alone
  (ascending id), then one batch holding every parallel task (ascending id).
  An all-parallel wave yields exactly `[sorted(wave)]`; an empty wave yields `[]`.
- `parallel_width(wave)` → how many tasks of the wave can run together:
  the number of parallel tasks, or `1` when the wave only has exclusive tasks,
  or `0` for an empty wave.

`DevelopmentNode._execute_pool` changes its loop from "dispatch the whole wave"
to "dispatch the **first batch** of `partition_wave(scheduler.next_wave())`,
record results, merge/refresh sub-worktrees, re-plan". Re-planning after every
batch is exactly what `sdd-worker` does with the engine (`coder_plan` → run
`chunks[0]` → re-plan), so both lanes share order and starvation behaviour, and
tasks unblocked by an exclusive task become visible in the very next round.
For a legacy index the first batch *is* the whole wave, so the loop performs
the same dispatches as today.

`ChunkAssigner.assign` replaces its inline exclusive/shared split with
`partition_wave`, then splits the parallel batch by seat count as it does now —
a behaviour-preserving refactor (G3).

`should_fan_out` and `PlannerNode._resolve_pool` use `parallel_width` instead
of `len(wave)` (G4). For legacy indexes every task is parallel, so the width is
unchanged (G5).

### Component Diagram
```
per-spec index ──→ TaskScheduler.from_index_file ──→ TaskRef.parallel
                                                        │
                         partition_wave / parallel_width (task_scheduler.py)
                          │                 │                    │
            ChunkAssigner.assign   DevelopmentNode._execute_pool   PlannerNode._resolve_pool
            (sdd-coder engine)     + should_fan_out                (pool sizing)
                                    │
                                    └──→ DevAgentPool.run_wave(batch)  (unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TaskRef` / `TaskScheduler` | extends (module-level helpers) | `parallel` field and exclusive-semantics loading already exist |
| `ChunkAssigner.assign` | refactor to use `partition_wave` | output must be identical for every wave |
| `DevelopmentNode._execute_pool` | modifies dispatch loop | one batch per round, merge/refresh per round |
| `should_fan_out` | modifies width computation | uses `parallel_width` |
| `PlannerNode._resolve_pool` | modifies width computation | uses `parallel_width` |
| `DevAgentPool.run_wave` | uses (unchanged) | receives a batch instead of a wave |
| `SubWorktreeManager.merge_sequential` / `refresh_all` | uses (unchanged) | now called once per batch |

### Data Models

No new models. `TaskRef.parallel: bool` (default `True`) already exists.

### New Public Interfaces
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
def partition_wave(wave: Sequence[TaskRef]) -> List[List[TaskRef]]: ...
def parallel_width(wave: Sequence[TaskRef]) -> int: ...
```

---

## 3. Module Breakdown

> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: wave partition helpers | yes | Signatures, ordering rule and return values fixed in §2 and the skeleton below | — |
| M2: ChunkAssigner uses `partition_wave` | yes | Behaviour-preserving; existing `test_roster.py` must pass unchanged | — |
| M3: DevelopmentNode round loop + `should_fan_out` | no | — | Round loop touches merge/refresh/progress-reporting interplay in a 1.7k-line node; needs judgement on log/progress wording and QA-repair re-entry paths |
| M4: PlannerNode pool sizing | yes | Replace `len(wave)` with `parallel_width(wave)`; log line keeps its format | — |
| M5: documentation | yes | Section text described in M5 | — |

### Module 1: Wave partition helpers
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py`
- **Responsibility**: Single definition of how a wave becomes dispatch batches and how wide it really is.
- **Depends on**: existing `TaskRef.parallel` (`task_scheduler.py:58`)
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py`
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py  (modifies; add after class TaskRef, verified: task_scheduler.py:32)
  from typing import Sequence  # extends the existing `from typing import Dict, List, Optional, Set`

  def partition_wave(wave: Sequence[TaskRef]) -> List[List[TaskRef]]:
      """Split a wave into ordered dispatch batches that respect exclusive tasks.

      Each exclusive task (``parallel=False``) forms its own single-task batch, in
      ascending id order, followed by one batch with every parallel task in
      ascending id order. Exclusive batches come first so an exclusive task can
      never starve behind parallel tasks that keep unblocking between rounds.

      Args:
          wave: Tasks whose dependencies are satisfied (``TaskScheduler.next_wave()``).

      Returns:
          The batches in dispatch order; ``[]`` for an empty wave. An all-parallel
          wave returns exactly one batch (legacy indexes always do).
      """

  def parallel_width(wave: Sequence[TaskRef]) -> int:
      """Number of tasks of ``wave`` that can run at the same time.

      Returns:
          The count of parallel tasks; ``1`` when the wave holds only exclusive
          tasks; ``0`` for an empty wave.
      """
  ```

### Module 2: ChunkAssigner uses `partition_wave`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py`
- **Responsibility**: Remove the inline exclusive/shared split (`roster.py:146-148`) in favour of M1, keeping output identical.
- **Depends on**: Module 1 (imports `partition_wave`)
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py` (existing tests, including `test_assign_exclusive_tasks_run_alone_and_first`, pass unchanged)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py  (modifies roster.py:10 import and roster.py:134 body)
  from parrot.flows.dev_loop.task_scheduler import TaskRef, partition_wave  # TaskRef verified: roster.py:10

  class ChunkAssigner:  # verified: roster.py:126
      def assign(self, wave: List[TaskRef], task_files: Dict[str, str]) -> List[PlanChunk]:  # verified: roster.py:134
          """Exclusive tasks alone first (via ``partition_wave``); the parallel batch is split
          into chunks of ``len(seats)``; seat rotation unchanged."""
  ```

### Module 3: DevelopmentNode dispatches one batch per round
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py`
- **Responsibility**: `_execute_pool` dispatches `partition_wave(scheduler.next_wave())[0]` per round, then marks results, merges (`isolated` mode) and refreshes, then re-plans. `should_fan_out` uses `parallel_width`. Log/progress lines report the batch actually dispatched; when a round is an exclusive task, the log says so (`exclusive`), so an operator can see why other ready tasks waited.
- **Depends on**: Module 1 (imports `partition_wave`, `parallel_width`)
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
  from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler, parallel_width, partition_wave  # verified: development.py:62

  def should_fan_out(wave: List[TaskRef], pool_cfg: DevAgentPoolConfig) -> bool:  # verified: development.py:77
      """True only when ``parallel_width(wave) >= 2`` AND the pool has more than one slot."""

  class DevelopmentNode(DevLoopNode):  # verified: development.py:104
      async def _execute_pool(
          self,
          shared: Dict[str, Any],
          research: ResearchOutput,
          pool_cfg: DevAgentPoolConfig,
          scheduler: TaskScheduler,
      ) -> DevelopmentOutput:  # verified: development.py:1364
          """Rounds: dispatch the first ``partition_wave`` batch of the current wave, record,
          merge/refresh, re-plan; stop when ``next_wave()`` is empty. Signature unchanged."""
  ```

### Module 4: PlannerNode sizes the pool from the parallel width
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py`
- **Responsibility**: `_resolve_pool` computes `width = max(1, parallel_width(wave))` instead of `max(1, len(wave))` (`planner.py:337`); the log line keeps its wording.
- **Depends on**: Module 1 (imports `parallel_width`)
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py
  from parrot.flows.dev_loop.task_scheduler import TaskScheduler, parallel_width  # verified: planner.py:50

  class PlannerNode(DevLoopNode):  # verified: planner.py:71
      async def _resolve_pool(self, brief: FeatureBrief, planner_out: PlannerOutput) -> DevAgentPoolConfig:  # verified: planner.py:287
          """Width is the wave-1 parallel width, capped at development_pool_max. Signature unchanged."""
  ```

### Module 5: Documentation
- **Path**: `docs/dev_loop/dev-flow-model-plan.md`
- **Responsibility**: Extend "## Planner interaction" (`dev-flow-model-plan.md:205`) with the parallel-width rule, and add a "## Exclusive tasks" section: what `parallel_semantics: exclusive` + `parallel: false` mean, dispatch order (exclusive first, alone, re-plan per round), identical behaviour in the `sdd-coder` engine, legacy indexes unchanged, and a pointer to `/sdd-task` "Task graph rules" and `scripts/sdd/check_task_graph.py`.
- **Depends on**: none (documents the behaviour fixed by this spec)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_partition_wave_all_parallel_is_one_sorted_batch` | M1 | shuffled all-parallel wave → `[[sorted ids]]` |
| `test_partition_wave_exclusive_first_each_alone` | M1 | `[P3, X2, P1, X4]` → `[[X2], [X4], [P1, P3]]` |
| `test_partition_wave_only_exclusive` | M1 | `[X2, X1]` → `[[X1], [X2]]` |
| `test_partition_wave_empty` | M1 | `[]` → `[]` |
| `test_parallel_width` | M1 | all-parallel → len; mixed → count of parallel; only exclusive → 1; empty → 0 |
| existing `test_roster.py` suite | M2 | passes unchanged (behaviour-preserving) |
| `test_should_fan_out_ignores_exclusive_tasks` | M3 | `[X1, P2]` with 2 slots → `False`; `[X1, P2, P3]` → `True` |
| `test_execute_pool_runs_exclusive_task_alone` | M3 | index with exclusive semantics, wave `[X1, P2, P3]`: `run_wave` called with `[X1]`, then `[P2, P3]`; no call ever mixes X1 with another task |
| `test_execute_pool_merges_after_exclusive_round` | M3 | `isolated` mode: `merge_sequential` + `refresh_all` run after the `[X1]` round, before the next `run_wave` |
| `test_execute_pool_failed_exclusive_task_skips_dependents` | M3 | X1 fails → its dependents are skipped, independent parallel tasks still run |
| `test_execute_pool_legacy_index_dispatches_whole_wave` | M3 | no header: `run_wave` receives the full wave, same call sequence as before |
| `test_resolve_pool_counts_only_parallel_tasks` | M4 | wave `[X1, X2]` → count 1; `[X1, P2, P3]` → count 2; legacy `[T1, T2, T3]` → 3 (capped by `development_pool_max`) |

### Integration Tests
| Test | Description |
|---|---|
| existing `packages/ai-parrot/tests/flows/dev_loop/integration/test_concurrency.py` and `test_pool_e2e.py` | pass unchanged (legacy indexes) |

### Test Data / Fixtures
```python
def _ref(task_id: str, *, parallel: bool = True, depends_on: list[str] | None = None) -> TaskRef:
    return TaskRef(id=task_id, status="pending", depends_on=depends_on or [], parallel=parallel)

# Index-backed scheduler with exclusive semantics (mirrors test_task_scheduler.py::_index):
# {"parallel_semantics": "exclusive", "tasks": [{"id": "TASK-1", "status": "pending", "parallel": False}, ...]}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1 (G1): With `"parallel_semantics": "exclusive"`, every `DevAgentPool.run_wave` call that includes an exclusive task receives exactly one task.
- [ ] AC-2 (G2): Within a wave, rounds dispatch exclusive tasks first in ascending id, one per round, then the wave's parallel tasks together; the scheduler is re-planned after every round.
- [ ] AC-3 (G3): `ChunkAssigner.assign` and `DevelopmentNode._execute_pool` both obtain batches from `partition_wave`; no other copy of the exclusive/parallel split remains (`grep -n "not t.parallel" packages/ai-parrot/src` finds only `task_scheduler.py`).
- [ ] AC-4 (G4): `should_fan_out` and `PlannerNode._resolve_pool` use `parallel_width`; a wave of only exclusive tasks sizes a 1-slot pool and does not fan out.
- [ ] AC-5 (G5): For an index without the header, `run_wave` call arguments, pool size and `should_fan_out` results are identical to the pre-change behaviour (asserted by the legacy tests above and the unchanged existing suites).
- [ ] AC-6: In `isolated` mode, `merge_sequential` and `refresh_all` run after each round, so a task unblocked by an exclusive task starts from the integrated branch.
- [ ] AC-7: Round logs identify an exclusive round (the word `exclusive` and the task id) so an operator can tell why other ready tasks waited.
- [ ] AC-8: All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py packages/ai-parrot/tests/flows/dev_loop/test_development_node.py packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py packages/ai-parrot/tests/flows/dev_loop/test_agent_pool.py packages/ai-parrot/tests/flows/dev_loop/integration -v`
- [ ] AC-9: `ruff check` on the changed files reports no new findings; changed files are formatted with `black`.
- [ ] AC-10: `docs/dev_loop/dev-flow-model-plan.md` documents exclusive tasks and the parallel-width sizing rule.
- [ ] AC-11: No public signature changes: `run_wave`, `_execute_pool`, `_resolve_pool`, `should_fan_out`, `ChunkAssigner.assign` keep their signatures.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler  # verified: nodes/development.py:62
from parrot.flows.dev_loop.task_scheduler import TaskScheduler  # verified: nodes/planner.py:50
from parrot.flows.dev_loop.task_scheduler import TaskRef  # verified: sdd_coder/roster.py:10
from parrot.flows.dev_loop.task_scheduler import PARALLEL_SEMANTICS_EXCLUSIVE  # verified: task_scheduler.py:29
from parrot.flows.dev_loop.agent_pool import DevAgentPool, WaveResult, aggregate_outputs  # verified: nodes/development.py:41
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
PARALLEL_SEMANTICS_EXCLUSIVE = "exclusive"                                   # line 29
class TaskRef(BaseModel):                                                    # line 32
    id: str; title: str; status: str; depends_on: List[str]; file: str
    parallel: bool = Field(default=True, ...)                                # line 58
class TaskScheduler:                                                         # line 69
    @classmethod
    def from_index_file(cls, path: Path) -> Optional["TaskScheduler"]:       # reads header, line 122
    def next_wave(self) -> List[TaskRef]:                                    # line 196 — "in no particular order"
    def mark_done(self, task_id: str) -> None:                               # line 214
    def mark_failed(self, task_id: str) -> None:                             # line 223 — propagates skipped
    def all_tasks(self) -> List[TaskRef]:                                    # line 253
    def pending(self) -> List[TaskRef]:                                      # line 266

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py
class ChunkAssigner:                                                         # line 126
    def assign(self, wave: List[TaskRef], task_files: Dict[str, str]) -> List[PlanChunk]:  # line 134
        # inline split today: exclusive / shared / batches                   # lines 146-148

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
class WaveResult:                                                            # line 119 (dataclass: completed, failed, worker_summaries)
class DevAgentPool:                                                          # line 135
    async def run_wave(self, tasks: List[TaskRef], *, research: ResearchOutput, run_id: str,
                       cwd_for: Callable[[str], str], escalate: bool = False,
                       session_host: Optional[Any] = None) -> WaveResult:    # line 435 — gathers one dispatch per task (line 489)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
def should_fan_out(wave: List[TaskRef], pool_cfg: DevAgentPoolConfig) -> bool:  # line 77 — `len(wave) < 2` at line 97
class DevelopmentNode(DevLoopNode):                                          # line 104
    async def _dispatch(self, shared, research) -> DevelopmentOutput:        # line 321 — first_wave line 361, should_fan_out call line 391
    def _collapse_for_single_task(self, shared, pool_cfg, scheduler, research) -> DevAgentPoolConfig:  # line 936 — uses total task count (line 974), NOT wave width; unchanged
    async def _execute_pool(self, shared, research, pool_cfg, scheduler) -> DevelopmentOutput:  # line 1364
        # loop: wave = scheduler.next_wave() line 1477; run_wave line 1497;
        # mark_done/mark_failed lines 1507-1510; merge_sequential line 1525; refresh_all line 1531

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py
class PlannerNode(DevLoopNode):                                              # line 71
    async def _resolve_pool(self, brief: FeatureBrief, planner_out: PlannerOutput) -> DevAgentPoolConfig:  # line 287
        # wave = scheduler.next_wave() line 336; width = max(1, len(wave)) line 337; count line 338

# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py
class SubWorktreeManager:
    async def create(self, worker_id: str) -> str:                           # line 146
    async def merge_sequential(self, *, resolver: Optional[Resolver] = None) -> MergeReport:  # line 181
    async def refresh_all(self) -> None:                                     # line 264
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `partition_wave` | `TaskRef.parallel` | attribute read | `task_scheduler.py:58` |
| `ChunkAssigner.assign` | `partition_wave` | function call | `sdd_coder/roster.py:134` |
| `DevelopmentNode._execute_pool` | `partition_wave` → `DevAgentPool.run_wave` | function call | `nodes/development.py:1477`, `:1497` |
| `should_fan_out` | `parallel_width` | function call | `nodes/development.py:97` |
| `PlannerNode._resolve_pool` | `parallel_width` | function call | `nodes/planner.py:337` |

### Existing tests to extend
- `packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py` — `_index(tmp_path, header)` helper and the two `parallel` semantics tests (end of file).
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py` — `_wave(n)`, `_roster(n)`, `test_assign_exclusive_tasks_run_alone_and_first`.
- `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py` — `_task_ref()` (line 185), `class TestShouldFanOut` (line 189).
- `packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py` — `_resolve_pool` calls at lines 178, 203, 223.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.flows.dev_loop.task_scheduler.partition_wave`~~ / ~~`parallel_width`~~ — created by M1.
- ~~`TaskScheduler.next_batch()`~~ / ~~`TaskScheduler.exclusive()`~~ — no such methods; do not add them (helpers are module-level, pure).
- ~~`TaskRef.exclusive`~~ — the field is `parallel` (inverted meaning).
- ~~`DevAgentPoolConfig.respect_exclusive`~~ or any opt-out flag — exclusivity is driven only by the index header.
- ~~`DevAgentPool.run_exclusive()`~~ — `run_wave` is reused unchanged.
- ~~`WaveResult.exclusive`~~ — `WaveResult` has only `completed`, `failed`, `worker_summaries`.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- Pure, deterministic helpers (no I/O, no logging) — same posture as `TaskScheduler`.
- Sort by `TaskRef.id` explicitly: `next_wave()` returns tasks "in no particular order".
- Keep the round loop's existing try/finally around `manager.cleanup(keep_on_conflict=True)`.
- `self.logger` with `%s` formatting, as in the surrounding `_execute_pool` logs.
- Google-style docstrings and strict type hints.

### Known Risks / Gotchas
- **More merges per wave**: a wave with k exclusive tasks now runs k+1 rounds, each followed by `merge_sequential` + `refresh_all` in `isolated` mode. This is the intended cost of exclusivity; legacy indexes still do one merge per wave.
- **Failure of an exclusive task**: `mark_failed` propagates `skipped` to dependents before the next re-plan; parallel tasks of the same wave do not depend on it (they were ready together) and must still run.
- **Stale wave between rounds**: never dispatch later batches of a previously computed partition — always re-plan from `scheduler.next_wave()`, or a task skipped by a failure could be dispatched.
- **Idle seats**: during an exclusive round, all but one worker idle. Pool sizing uses parallel width, so seats are not over-provisioned for exclusive-only waves.
- **QA repair re-entry** (`_dispatch`, `development.py:379`) and single-task collapse (`_collapse_for_single_task`) are unaffected: neither depends on wave width.
- **Progress text**: `report_progress` currently says `Wave N: k task(s)`; keep the "Wave" wording but report the batch actually dispatched so counts stay truthful.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none |

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-560; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph**:
  - M2 → M1 (imports `partition_wave`)
  - M3 → M1 (imports `partition_wave`, `parallel_width`)
  - M4 → M1 (imports `parallel_width`)
  - M1 and M5 have no dependencies. Expected rounds: {M1, M5} then {M2, M3, M4}.
- **Shared files**: none — each module owns its source file and its test file.
- **Exclusive resources**: none (no extension rebuild, lockfile, migration or shared `conftest.py` edit).
- **Cross-feature dependencies**: the `TaskRef.parallel` / `PARALLEL_SEMANTICS_EXCLUSIVE` / `ChunkAssigner` exclusive split already on `dev` (commit landed 2026-09-15).

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Should `PlannerNode._resolve_pool` size from the maximum parallel width across all waves instead of wave 1? Today it uses wave 1 only; this spec keeps that and only changes how the width is counted. — *Owner: Jesus Lara*: suggested default.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (no accepted exploration document — spec scaffolded from inline notes)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-16 | Jesus Lara (with Claude) | Initial draft |
