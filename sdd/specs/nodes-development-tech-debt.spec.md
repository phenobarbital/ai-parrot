---
type: feature
base_branch: dev
feature_id: FEAT-693
projects: [ai-parrot]
tags: [dev-loop, task-scheduler, tech-debt, sdd-fix]
---

# Feature Specification: FEAT-560 follow-ups in `DevelopmentNode` / `task_scheduler`

**Feature ID**: FEAT-693
**Date**: 2026-10-16
**Author**: Jesus Lara (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger fix group `fixgroup:80693c1eee43` (all discovered from
`spec:FEAT-560`, `sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`):

| Issue | Severity | Summary |
|---|---|---|
| issue:27a665e3773c | minor | FEAT-560 AC-5 says "identical" legacy dispatch, but §7 mandates an id-sorted wave |
| issue:7f7d8adce7e2 | minor | Comment above the isolated-mode merge/refresh says "for exclusive rounds" |
| issue:8f46e2c1eed1 | minor | `_execute_pool` re-derives exclusivity inline (`not batch[0].parallel`); AC-3 grep is stale |
| issue:a02a4ef38c4e | low | Function-local imports of `parallel_width` / `partition_wave` |
| issue:ee92b81d1adf | low | Drive-by edit in `_resolver_label_model` — process-tracking only, **no code change** |

---

## 1. Motivation & Business Requirements

### Problem Statement
FEAT-560's code review left four small, verified inconsistencies between the
`DevelopmentNode` pool loop, `task_scheduler.py` and FEAT-560's own spec text.
None is a behaviour bug; each one misleads the next maintainer (a wrong
comment, a second exclusivity check, a stale verification grep, an AC that
reads as if the deterministic sort were a regression).

### Goals
- G1: `task_scheduler.py` exports `is_exclusive_batch(batch)`; `_execute_pool`
  uses it instead of `len(batch) == 1 and not batch[0].parallel`.
- G2: `development.py` imports `partition_wave`, `parallel_width` and
  `is_exclusive_batch` at module level (extending the existing line-62 import);
  the two function-local imports are removed.
- G3: The comment above the isolated-mode `merge_sequential` / `refresh_all`
  block states it runs after **every** round in isolated mode.
- G4: FEAT-560's spec text is reconciled: AC-5 scopes "identical" to the set
  of dispatched tasks and pool sizing (id-sorted worker assignment is an
  intentional change, per its §7), and AC-3's grep matches the real code.

### Non-Goals
- issue:ee92b81d1adf — the `_resolver_label_model` edit is functionally
  equivalent; reverting it is churn. Released back to the ledger for human
  acknowledgement, not closed by this feature.
- `sdd_coder/roster.py` `ChunkAssigner.assign` keeps its own exclusive/shared
  split (it chunks shared tasks by seat count, so `partition_wave` does not fit
  as-is). Contradicts FEAT-560 AC-3; tracked as a separate ledger issue, not
  fixed here.
- No behaviour change of any kind: dispatch order, batches, logs and progress
  messages stay byte-identical.

---

## 2. Architectural Design

```python
# task_scheduler.py, next to partition_wave / parallel_width
def is_exclusive_batch(batch: Sequence[TaskRef]) -> bool:
    """True when ``batch`` is a single exclusive task (one partition_wave round)."""
    return len(batch) == 1 and not batch[0].parallel
```

`development.py` line 62 becomes
`from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler, is_exclusive_batch, parallel_width, partition_wave`
(no circular-import risk: the module already imports `TaskRef`/`TaskScheduler`
from it at top level).

---

## 3. Module Breakdown

### Module 1: Scheduler helper + DevelopmentNode cleanup
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` — add `is_exclusive_batch`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` — module-level import, use the helper, fix the comment.
- `packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py` — unit tests for `is_exclusive_batch`.

### Module 2: FEAT-560 spec reconciliation
- `sdd/specs/dev-loop-pool-exclusive-tasks.spec.md` — amend AC-3 and AC-5, add a revision-history row.

---

## 4. Test Specification
- `is_exclusive_batch([exclusive])` → `True`; `([parallel])` → `False`;
  `([exclusive, exclusive])` → `False`; `([])` → `False`.
- Existing `test_task_scheduler.py` and `test_development_node.py` suites pass unchanged.

---

## 5. Acceptance Criteria
- [ ] AC-1: `grep -n "\.parallel" packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` finds nothing.
- [ ] AC-2: `development.py` has no function-local `from parrot.flows.dev_loop.task_scheduler import`.
- [ ] AC-3: The merge/refresh comment no longer says "exclusive rounds".
- [ ] AC-4: FEAT-560 AC-3 and AC-5 are amended as in G4.
- [ ] AC-5: `pytest packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py packages/ai-parrot/tests/flows/dev_loop/test_development_node.py` passes.
- [ ] AC-6: `ruff check` clean on the changed Python files.

---

## 6. Codebase Contract

### Verified Imports
- `from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler` — development.py:62
- `from parrot.flows.dev_loop.task_scheduler import parallel_width` — development.py:97 (inside `should_fan_out`)
- `from parrot.flows.dev_loop.task_scheduler import partition_wave` — development.py:1388 (inside `_execute_pool`)

### Existing Signatures
- `partition_wave(wave: Sequence[TaskRef]) -> List[List[TaskRef]]` — task_scheduler.py:65
- `parallel_width(wave: Sequence[TaskRef]) -> int` — task_scheduler.py:103
- `TaskRef.parallel: bool` — task_scheduler.py:54
- `is_exclusive = len(batch) == 1 and not batch[0].parallel` — development.py:1495
- `# For exclusive rounds, merge and refresh before the next batch` — development.py:1572, guarding `if manager is not None:`

### Does NOT Exist
- No `is_exclusive_batch` in `task_scheduler.py` before this feature.
- `task_scheduler.py` has no `__all__`.

---

## 7. Implementation Notes & Constraints
- Keep log/progress strings byte-identical; only the source of `is_exclusive` changes.
- Do not touch `_resolver_label_model` or `sdd_coder/roster.py`.

## 8. Open Questions
None.

## Revision History
- 2026-10-16: initial (sdd-fix lane for fixgroup:80693c1eee43).
