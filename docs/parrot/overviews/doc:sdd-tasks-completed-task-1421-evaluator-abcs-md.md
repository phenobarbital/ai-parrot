---
type: Wiki Overview
title: 'TASK-1421: Evaluator ABCs (`Metric`, `AbstractEvaluator`)'
id: doc:sdd-tasks-completed-task-1421-evaluator-abcs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The scoring contract — the polymorphic point of the whole harness. Implements
  spec §3 Module 6:'
relates_to:
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.evaluators
  rel: mentions
- concept: mod:parrot.eval.models
  rel: mentions
- concept: mod:parrot.eval.sandbox.base
  rel: mentions
---

# TASK-1421: Evaluator ABCs (`Metric`, `AbstractEvaluator`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 6
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1415, TASK-1417
**Assigned-to**: unassigned

---

## Context

The scoring contract — the polymorphic point of the whole harness. Implements spec §3 Module 6:
`Metric` and `AbstractEvaluator` ABCs. Concrete evaluators (state-based) are built in TASK-1422.

---

## Scope

- Create `parrot/eval/evaluators/__init__.py` and `parrot/eval/evaluators/base.py`.
- Implement `Metric(ABC)` with `name: str` and `async score(task, trajectory, sandbox=None) -> MetricScore`.
- Implement `AbstractEvaluator(ABC)` with `async evaluate(task, trajectory, sandbox=None) -> EvalResult`.
- Export from `parrot/eval/__init__.py`.

**NOT in scope**: any concrete evaluator/metric, the registry (TASK-1416 — imported only by concretes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/evaluators/__init__.py` | CREATE | Subpackage init |
| `packages/ai-parrot/src/parrot/eval/evaluators/base.py` | CREATE | `Metric`, `AbstractEvaluator` |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export ABCs |
| `packages/ai-parrot/tests/eval/test_evaluator_base.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from abc import ABC, abstractmethod
from parrot.eval.models import EvalTask, Trajectory, EvalResult, MetricScore   # TASK-1415
from parrot.eval.sandbox.base import Sandbox                                    # TASK-1417
```

### Does NOT Exist
- ~~`parrot.eval.evaluators.*` concretes~~ — created in later tasks.

---

## Implementation Notes

### Key Constraints
- Async abstract methods; `sandbox` parameter optional (`Sandbox | None = None`).
- No logic in the ABCs beyond the signatures + docstrings.

---

## Acceptance Criteria

- [ ] `from parrot.eval import AbstractEvaluator, Metric` resolves.
- [ ] A trivial concrete subclass can be instantiated and `await`ed in a test.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_evaluator_base.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/evaluators/base.py`

---

## Test Specification

```python
from parrot.eval import AbstractEvaluator, Metric, EvalResult, MetricScore
from parrot.eval.models import Trajectory, EvalTask

async def test_concrete_evaluator_roundtrip():
    class Trivial(AbstractEvaluator):
        async def evaluate(self, task, trajectory, sandbox=None):
            return EvalResult(task_id=task.task_id, attempt=trajectory.attempt,
                              scores=[], passed=True, trajectory=trajectory)
    t = EvalTask(task_id="t1", inputs={})
    tr = Trajectory(task_id="t1", attempt=1)
    assert (await Trivial().evaluate(t, tr)).passed
```

---

## Agent Instructions

Standard SDD flow: verify the contract, set index `in-progress`, implement, run tests + ruff, move to
`completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
