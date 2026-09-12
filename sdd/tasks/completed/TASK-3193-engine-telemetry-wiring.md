# TASK-3193: Wire attempt identity, telemetry capture and outcome events into the engine

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3188, TASK-3191, TASK-3192
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (engine) and the resolutions of §10 R3/R4/R7. This is where
the pieces meet: the collector grows a hook to receive `AttemptTelemetry`, each
attempt gets a unique id, the declared-file count is captured while the task
file still exists, the telemetry root is validated, and outcome rows are emitted
from the paths that actually own each exit.

Two engine facts drive the design and must not be worked around:

- `_run_task` hard-codes `attempt=1` per invocation (`engine.py:592`) and
  `run_chunk` rejects only *currently running* tasks (`engine.py:622-625`), so
  `(feature, task, attempt)` recurs across jobs.
- The both-attempts-failed path returns at `engine.py:602-611` **without**
  calling `_consolidate`, and `merge()` deliberately supports re-merging after a
  manual conflict repair (`engine.py:407`).

---

## Scope

- `AttemptTelemetryCollector`: add `on_attempt_telemetry`, mint `attempt_uid`,
  carry `job_id`/`declared_files` into `record()`.
- `SddCoderEngine.__init__`: accept `telemetry_dir`, resolve it through
  `resolve_durable_root`, build the sink.
- `_run_attempt`: capture the declared-file count from the task file; write the
  `attempt` row after `collector.record()`.
- `_run_task` and `merge()`: emit `outcome` rows per attempt with a monotonic
  `event_seq`.
- `SddCoderToolkit`: pass `telemetry_dir` through.
- Tests for identity, both-failed outcomes, failed-then-merged attribution and
  conflict-then-remerge.

**NOT in scope**: the sink internals (TASK-3191), the dispatcher side
(TASK-3189/3190), the analysis (TASK-3194).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Hook, uid, declared files, sink, outcome events |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | Pass `telemetry_dir` through |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Identity + outcome-event tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models.telemetry import AttemptTelemetry        # TASK-3188
from parrot.flows.dev_loop.sdd_coder.telemetry import (                    # TASK-3191
    CoderTelemetrySink, OutcomeRow, build_attempt_row, resolve_durable_root,
)
from parrot.flows.dev_loop.sdd_coder.fidelity import parse_task_files      # verified: sdd_coder/fidelity.py:25
from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, TaskResult, CoderJob  # verified: sdd_coder/models.py:115,129,153
from parrot import conf                                                    # verified: sdd_coder/roster.py:9
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
class AttemptTelemetryCollector:                                      # line 91
    def __init__(self, *, attempt: int, seat: RosterSeat) -> None:    # line 101
    def apply(self, action: Any, origin: Any = None) -> None:         # line 108
    def record(self) -> AttemptRecord:                                # line 125

class SddCoderEngine:
    def __init__(self, *, roster, probe=None, redis_url=None,
                 worktree_base_path=None, dispatcher_builder=build_dispatcher,
                 stream_ttl_seconds=3600) -> None:                    # line 149
        self._base_path = os.path.realpath(worktree_base_path or conf.WORKTREE_BASE_PATH)  # line 162
    async def _consolidate(self, ...) -> TaskResult:                  # line 337
    async def merge(self, feature, worktree, task_id) -> TaskResult:  # line 407
    async def _journal(self, worktree: str, job: CoderJob) -> None:   # line 472
    def _labels_for(self, task, seat, attempt) -> DispatchLabels:     # line 508
    async def _run_attempt(self, ctx, task, seat, *, attempt, job_id
        ) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str,
                   SubWorktreeManager, str, str]:                     # line 520
        collector = AttemptTelemetryCollector(attempt=attempt, seat=seat)  # line 533
        collector.error = error                                        # line 583
        return collector.record(), output, error, manager, branch, path  # line 586
    async def _run_task(self, ctx, task, seat, *, job_id) -> TaskResult:  # line 588
        attempts: List[AttemptRecord] = []                             # line 591
        rec, out, err, manager, branch, path = await self._run_attempt(ctx, task, seat, attempt=1, job_id=job_id)  # line 592
        # both-failed early return WITHOUT _consolidate                # lines 602-611
        result = await self._consolidate(ctx, manager, task, branch=branch, path=path)  # line 611
        return result.model_copy(update={"attempts": attempts, "development_output": out})  # line 612
    async def run_chunk(self, feature, worktree, task_ids) -> CoderJob:  # line 614
        if task_id in running: raise CoderFailure("task_already_running", ...)  # lines 622-625

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py
def __init__(self, ..., worktree_base_path: Optional[str] = None, ...):  # line 46
    self._engine = SddCoderEngine(roster=cfg, redis_url=redis_url, worktree_base_path=worktree_base_path)  # line 56

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py
job_id=f"job-{uuid.uuid4().hex[:12]}"                                 # line 30

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py
def parse_task_files(task_md: str) -> List[str]:                      # line 25
```

### Does NOT Exist
- ~~A unique attempt identifier anywhere today~~ — `attempt` restarts at 1 per
  `_run_task` (`engine.py:592`); `job_id` alone is not enough either, since both
  attempts of one task share it. Mint `attempt_uid` in `_run_attempt`.
- ~~`_consolidate` receiving an attempt number or record~~ — it does not take one, and
  `attempts` is attached afterwards by `model_copy` (`engine.py:612`). Do NOT emit the
  outcome row from inside `_consolidate`: it cannot know which attempt produced it.
- ~~`SddCoderEngine.telemetry_dir` / `.sink`~~ — added here.
- ~~`TaskResult.event_seq`~~ — the sequence is per `attempt_uid` and lives on the row,
  not on the result model.
- ~~`conf.BASE_DIR` as the telemetry root~~ — see TASK-3191's contract; use
  `resolve_durable_root`.

---

## Implementation Notes

### Key Constraints
- **One outcome row per outcome event, from the owner of that exit.**
  `_run_task` owns the both-failed return and the consolidated success;
  `merge()` owns a later re-merge. Never emit from `_consolidate`.
- `event_seq` is monotonic per `attempt_uid`, starting at 1. The analysis takes
  the highest. Keep the counter with the engine's per-attempt state, not global.
- **Capture `declared_files` during the attempt.** `parse_task_files` reads the
  task file inside the worktree that `/sdd-done` later removes; a row holding
  only `task_file` could never reproduce its bucket. Set
  `declared_files_known=False` when the file is unreadable rather than guessing 0.
- Telemetry failures never change an outcome: the sink already swallows, and the
  engine must not add a raising path around it.
- A bad telemetry root must fail at construction (`resolve_durable_root` raises)
  rather than at the first write — an operator finds out immediately.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:472-488` —
  `_journal`'s `asyncio.to_thread` pattern.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:568-576` —
  the existing comment explaining why the collector is bound as `session_host`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `on_attempt_telemetry` to the collector and widen `record()` — *why*: the dispatcher calls the hook by name, and `record()` is the only place `AttemptRecord` is built.
2. Mint `attempt_uid` in `_run_attempt` and pass it (plus `job_id`) to the collector — *why*: it must exist before the dispatch so the record and every outcome row share it.
3. Capture the declared-file count before dispatching — *why*: the task file is readable now and gone after `/sdd-done`.
4. Write the `attempt` row right after `collector.record()` — *why*: the measurement is then durable even if the server dies during consolidation.
5. Emit outcome rows from `_run_task`'s two exits and from `merge()` — *why*: those are the only places that know which attempt produced which fate.
6. Thread `telemetry_dir` through `__init__` and the toolkit — *why*: the root must be injected and validated, never inferred from a worktree path.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — collector)
```python
# occurrences: 1 (verified: grep -c '    def record(self) -> AttemptRecord:' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# BEFORE — insert above `    def record(self) -> AttemptRecord:` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:125)
    def on_attempt_telemetry(self, telemetry: AttemptTelemetry) -> None:
        """Receive the dispatcher's terminal telemetry (FEAT-554, spec §10 R3).

        Called by `LLMCodeDispatcher._emit_attempt_telemetry` through the bound
        session host. Separate from `apply()` because this payload deliberately
        does NOT travel as a `DispatchCompleted` action: that projection copies
        only seven whitelisted `usage` scalars and swallows validation errors,
        so a per-turn series or a budget report would vanish in silence.
        """
        self.telemetry = telemetry
```
**Why**: A plain attribute assignment, not a merge into `self.usage`: the two carry different things (`apply()` gets CLI-shaped scalars, this gets the rich payload) and `record()` decides how each lands on the `AttemptRecord`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — uid + declared files)
```python
# occurrences: 1 (verified: grep -c '        collector = AttemptTelemetryCollector(attempt=attempt, seat=seat)' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# REPLACE the line `        collector = AttemptTelemetryCollector(attempt=attempt, seat=seat)` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:533)
        # A unique id per attempt: `attempt` restarts at 1 on every _run_task
        # invocation (line 592) and both attempts of a task share `job_id`, so
        # neither can key the telemetry join (spec §10 R3).
        attempt_uid = uuid.uuid4().hex
        collector = AttemptTelemetryCollector(
            attempt=attempt, seat=seat, attempt_uid=attempt_uid, job_id=job_id
        )
        # FILL IN: read `task.task_file` and count `parse_task_files(...)` NOW,
        # while the worktree still exists — set declared_files /
        # declared_files_known on the collector. An unreadable file means
        # known=False, never 0. Bounded by AC-8.
```
**Why**: Minting the uid before `manager.create()` means even a worktree-creation failure produces an identifiable attempt row. `uuid` must be imported at the top of the module if it is not already — check first.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — attempt row)
```python
# occurrences: 1 (verified: grep -c '        return collector.record(), output, error, manager, branch, path' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# REPLACE the line `        return collector.record(), output, error, manager, branch, path` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:586)
        record = collector.record()
        # Write the measurement BEFORE consolidation: if the server dies between
        # here and the outcome, the attempt row still survives and the analysis
        # reports an incomplete pair rather than losing the sample (spec §2).
        await self._sink.write_attempt(
            build_attempt_row(
                record, feature_id=ctx.feature_id, job_id=job_id,
                declared_files=record.declared_files,
            )
        )
        return record, output, error, manager, branch, path
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — outcome events)
```python
# occurrences: 1 (verified: grep -c '        result = await self._consolidate(ctx, manager, task, branch=branch, path=path)' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# AFTER — insert below `        result = await self._consolidate(ctx, manager, task, branch=branch, path=path)` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:611)
        # FILL IN: emit ONE outcome row for the attempt that produced `result`
        # — i.e. `attempts[-1].attempt_uid`, not both attempts. Bounded by AC-19
        # ("failed-then-merged attributed per attempt, never to both").
```
**Why**: Attaching the outcome to `attempts[-1]` is what distinguishes a failed first attempt from the successful second one. Emitting inside `_consolidate` is impossible — it never receives an attempt (`engine.py:337`) and the both-failed path never reaches it at all (`engine.py:602-611`), which is precisely the hole this fixes.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._engine = SddCoderEngine(roster=cfg, redis_url=redis_url, worktree_base_path=worktree_base_path)' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py)
# REPLACE the line `        self._engine = SddCoderEngine(roster=cfg, redis_url=redis_url, worktree_base_path=worktree_base_path)` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:56)
        self._engine = SddCoderEngine(
            roster=cfg,
            redis_url=redis_url,
            worktree_base_path=worktree_base_path,
            telemetry_dir=telemetry_dir,
        )
```
**Why**: The toolkit is the only place that knows operator configuration, and the engine must never guess a durable root from a worktree path. Add `telemetry_dir: Optional[str] = None` to the toolkit's `__init__` signature (line 46) alongside `worktree_base_path`.

### FILL IN checklist
- [ ] `engine.py::AttemptTelemetryCollector.__init__/record` — accept `attempt_uid`/`job_id`/declared-file state and fold `self.telemetry` into the `AttemptRecord`; bounded by TASK-3192's field names
- [ ] `engine.py::_run_attempt` — declared-file capture; bounded by AC-8 (known=False when unreadable)
- [ ] `engine.py::SddCoderEngine.__init__` — `telemetry_dir` kwarg, `resolve_durable_root(...)`, build `self._sink`; bounded by AC-9 (raise on a root under `_base_path`)
- [ ] `engine.py::_run_task` — outcome row on the both-failed return AND after consolidation, per attempt, with `event_seq`; bounded by AC-19
- [ ] `engine.py::merge` — a later outcome row with a higher `event_seq` for the same `attempt_uid`; bounded by AC-19
- [ ] `test_engine_dispatch.py` — the five test bodies below

---

## Acceptance Criteria

- [ ] Two `_run_task` invocations for the same task in different jobs both produce `attempt=1` and DIFFERENT `attempt_uid`s.
- [ ] Every `attempt` row and every `outcome` row for one attempt share the same `attempt_uid`.
- [ ] A task failing on both seats writes two `attempt` rows and two `failed` `outcome` rows — the path that never reaches `_consolidate`.
- [ ] Attempt 1 `failed` + attempt 2 `merged`: each outcome attaches to its own `attempt_uid`, never both.
- [ ] A `merge_conflict` followed by a repaired `merge()` yields two outcome rows for one `attempt_uid` with increasing `event_seq`.
- [ ] `declared_files` is populated during the attempt; deleting the worktree afterwards does not change the written row.
- [ ] A `telemetry_dir` under `worktree_base_path` raises at engine construction.
- [ ] A sink failure does not change any `TaskResult`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py  (append)
import pytest


class TestAttemptIdentity:
    async def test_uid_unique_across_jobs(self, ...):
        # FILL IN: run the same task through _run_task twice with different
        # job_ids; assert attempt == 1 both times and the uids differ
        # — bounded by AC-12 (spec §10 R3)
        raise NotImplementedError


class TestOutcomeEvents:
    async def test_both_attempts_failed(self, ...):
        # FILL IN: force both seats to error; assert two attempt rows and two
        # failed outcome rows — the path that skips _consolidate (§10 R4)
        raise NotImplementedError

    async def test_failed_then_merged_per_attempt(self, ...):
        # FILL IN: attempt 1 errors, attempt 2 merges; assert each outcome row
        # carries its own attempt_uid
        raise NotImplementedError

    async def test_conflict_then_remerge_increments_seq(self, ...):
        # FILL IN: merge_conflict then a repaired merge(); assert two rows,
        # event_seq 1 then 2, same attempt_uid
        raise NotImplementedError


class TestDurableRootGuard:
    def test_root_under_worktree_base_raises(self, tmp_path):
        # FILL IN: construct SddCoderEngine with telemetry_dir inside
        # worktree_base_path; assert it raises — bounded by AC-9
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 4 and §10 R3/R4/R7.
2. **Check dependencies** — TASK-3188, TASK-3191 and TASK-3192 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `_run_attempt` (520-586) and `_run_task` (588-612) in full; if line numbers moved, update the anchors first.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; never emit an outcome row from `_consolidate`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3193-engine-telemetry-wiring.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (codex-spark attempt 1 failed on CLI arg incompatibility; qwen seat attempt 2 succeeded) via parrot-sdd-coder orchestrator, merged by sdd-worker
**Date**: 2026-09-12
**Notes**: Wired attempt identity, telemetry capture and outcome events
into `SddCoderEngine`: `AttemptTelemetryCollector` now accepts
`attempt_uid`/`job_id` and receives `on_attempt_telemetry`;
`_run_attempt` mints a unique `attempt_uid` per attempt and captures
`declared_files` while the worktree still exists; `_run_task` and
`merge()` both emit `outcome` rows (including the failed-both-attempts
path that never reaches `_consolidate`, and repeated `merge()` calls with
increasing `event_seq`); `SddCoderToolkit` passes `telemetry_dir` through;
a `telemetry_dir` under `worktree_base_path` raises at construction. Full
`sdd_coder/` suite (171 tests) plus `test_llm_code_dispatcher.py` (66
tests) pass together; `ruff check` clean. Attempt 1 on codex-spark failed
before any model call (`codex exec` rejected `--ask-for-approval` — a
CLI/dispatcher argument mismatch, not a code issue); attempt 2 on qwen
succeeded.

**Deviations from spec**: none

Seat: codex-spark→qwen (retry) · Backend: codex (failed)→nova · Model: gpt-5.3-codex-spark (failed)→qwen.qwen3-coder-480b-a35b-instruct · Attempts: 2 · Duration: 262.9s · Tokens: 2048316/12151
