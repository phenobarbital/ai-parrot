# TASK-4404: `is_exclusive_batch` helper, module-level imports and FEAT-560 spec reconciliation

**Feature**: FEAT-693 — FEAT-560 follow-ups in `DevelopmentNode` / `task_scheduler`
**Spec**: `sdd/specs/nodes-development-tech-debt.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

discovered_from: issue:27a665e3773c, issue:7f7d8adce7e2, issue:8f46e2c1eed1, issue:a02a4ef38c4e
(issue:ee92b81d1adf is in the same fix group but needs no code change — see spec Non-Goals.)

---

## Context
FEAT-560 code review left four verified, behaviour-neutral inconsistencies (spec §1):
`_execute_pool` re-derives exclusivity inline, `development.py` imports scheduler
helpers function-locally, a comment describes the wrong guard, and FEAT-560's own
AC-3/AC-5 text no longer matches the code.

---

## Scope
- Add `is_exclusive_batch(batch)` to `task_scheduler.py` and unit-test it.
- `development.py`: extend the line-62 import, drop the two function-local imports,
  use `is_exclusive_batch(batch)`, reword the merge/refresh comment.
- `dev-loop-pool-exclusive-tasks.spec.md`: amend AC-3 (grep) and AC-5 (scope of
  "identical"), add a revision-history row.

**NOT in scope**: `_resolver_label_model`; `sdd_coder/roster.py`; any change to log
or progress strings, dispatch order or batches.

---

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` | MODIFY | add `is_exclusive_batch` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | module-level import, use helper, fix comment |
| `packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py` | MODIFY | `TestIsExclusiveBatch` |
| `sdd/specs/dev-loop-pool-exclusive-tasks.spec.md` | MODIFY | amend AC-3 / AC-5 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler  # development.py:62
from parrot.flows.dev_loop.task_scheduler import parallel_width          # development.py:97 (in should_fan_out)
from parrot.flows.dev_loop.task_scheduler import partition_wave          # development.py:1388 (in _execute_pool)
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler, partition_wave, parallel_width  # test_task_scheduler.py:9
```

### Existing Signatures to Use
```python
# task_scheduler.py
class TaskRef(BaseModel): parallel: bool                         # :54
def partition_wave(wave: Sequence[TaskRef]) -> List[List[TaskRef]]: ...  # :65
def parallel_width(wave: Sequence[TaskRef]) -> int: ...          # :103 (last def in the helpers block)
# development.py
is_exclusive = len(batch) == 1 and not batch[0].parallel         # :1495
# For exclusive rounds, merge and refresh before the next batch  # :1572, guards `if manager is not None:`
# test_task_scheduler.py
def _ref(task_id: str, *, parallel: bool = True, depends_on=None) -> TaskRef  # :12
class TestParallelWidth: ...                                     # :221 (last class)
```

### Does NOT Exist
- ~~`is_exclusive_batch`~~ before this task; ~~`__all__`~~ in `task_scheduler.py`.

---

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py", "action": "MODIFY"},
    {"path": "sdd/specs/dev-loop-pool-exclusive-tasks.spec.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#partition_wave",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#parallel_width",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py#should_fan_out",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py#DevelopmentNode._execute_pool"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `is_exclusive_batch` after `parallel_width` in `task_scheduler.py` — because it belongs with the other wave helpers (single source of truth, FEAT-560 AC-3).
2. In `development.py`, replace the line-62 import with the extended one, then delete the two function-local imports — because the module already imports from `task_scheduler` at top level, so there is no cycle.
3. Replace the inline `is_exclusive` expression with `is_exclusive_batch(batch)` — logs stay byte-identical.
4. Reword the comment above `if manager is not None:` — the block runs after every round in isolated mode (FEAT-560 AC-6).
5. Add `TestIsExclusiveBatch` and amend the FEAT-560 spec.

### `task_scheduler.py` — MODIFY
```python
# AFTER — append below the body of `def parallel_width` (verified: task_scheduler.py:103)
# occurrences: 1 (verified: grep -c '^def parallel_width' task_scheduler.py)
def is_exclusive_batch(batch: Sequence[TaskRef]) -> bool:
    """Whether ``batch`` is a single exclusive task, i.e. an exclusive round of :func:`partition_wave`.

    Args:
        batch: One batch returned by :func:`partition_wave`.

    Returns:
        ``True`` only for a one-task batch whose task has ``parallel=False``.
    """
    return len(batch) == 1 and not batch[0].parallel
```
**Why**: keeps every reading of `TaskRef.parallel` inside `task_scheduler.py`.

### `development.py` — MODIFY
```python
# REPLACE (occurrences: 1) line 62
from parrot.flows.dev_loop.task_scheduler import (
    TaskRef,
    TaskScheduler,
    is_exclusive_batch,
    parallel_width,
    partition_wave,
)
# DELETE (occurrences: 1 each) the local imports at :97 and :1388
# REPLACE (occurrences: 1) :1495
                is_exclusive = is_exclusive_batch(batch)
# REPLACE (occurrences: 1) :1572
                # In isolated mode, merge and refresh after every round (exclusive or not)
```

### `test_task_scheduler.py` — MODIFY
```python
# extend line 9 import with is_exclusive_batch; append after class TestParallelWidth
class TestIsExclusiveBatch:
    # FILL IN: single exclusive → True; single parallel → False; two exclusive → False; empty → False
```

### FEAT-560 spec — MODIFY
- AC-3: replace `grep -n "not t.parallel" packages/ai-parrot/src` with a grep that matches the real code.
- AC-5: scope "identical" to the set of dispatched tasks and pool sizing; note id-sorted worker assignment is an intentional §7 change.
- FILL IN: revision-history row dated 2026-10-16 referencing FEAT-693.

### FILL IN checklist
- [ ] `TestIsExclusiveBatch` bodies
- [ ] AC-3 / AC-5 wording + revision row

---

## Acceptance Criteria
- [ ] `grep -n "\.parallel" packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` finds nothing.
- [ ] No function-local `task_scheduler` import in `development.py`.
- [ ] Merge/refresh comment no longer says "exclusive rounds".
- [ ] FEAT-560 AC-3 and AC-5 amended.
- [ ] Tests below pass; `ruff check` clean on the changed Python files.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_development_node.py -q`

## Completion Note
Completed 2026-10-16 (sdd-fix lane, fixgroup:80693c1eee43). Implementing commit 7857c7b6d.

- `task_scheduler.is_exclusive_batch(batch)` added next to `partition_wave` /
  `parallel_width`; `_execute_pool` now uses it, so `development.py` no longer
  reads `TaskRef.parallel` (issue:8f46e2c1eed1).
- `development.py` imports `is_exclusive_batch`, `parallel_width`,
  `partition_wave` at module level; both function-local imports removed
  (issue:a02a4ef38c4e).
- Merge/refresh comment reworded: runs after every round in isolated mode
  (issue:7f7d8adce7e2).
- FEAT-560 spec: AC-3 grep fixed to match the real code, and the
  `sdd_coder/roster.py` `ChunkAssigner` split is noted as still separate. AC-5
  is scoped to the task set and pool sizing; the id-sorted order is intentional
  per its §7 (issue:27a665e3773c, issue:8f46e2c1eed1's stale-grep note).
- Log and progress strings unchanged. 5 new `TestIsExclusiveBatch` tests;
  `test_task_scheduler.py` + `test_development_node.py` = 81 passed against
  the worktree code (Cython `.so` symlinked from the main checkout); ruff clean.
- Not changed: issue:ee92b81d1adf (`_resolver_label_model`). It asks for no code
  change, so it was released to the ledger for a human to acknowledge.
