---
type: Wiki Overview
title: 'TASK-1422: `StateBasedEvaluator` + `StateMatch` metric'
id: doc:sdd-tasks-completed-task-1422-state-based-evaluator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The τ-bench-style scorer: diff the post-rollout world against an annotated
  goal state. Implements'
relates_to:
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.evaluators.base
  rel: mentions
- concept: mod:parrot.eval.models
  rel: mentions
- concept: mod:parrot.eval.registry
  rel: mentions
- concept: mod:parrot.eval.sandbox.base
  rel: mentions
---

# TASK-1422: `StateBasedEvaluator` + `StateMatch` metric

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 7 (brainstorm §13.5)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1416, TASK-1418, TASK-1421
**Assigned-to**: unassigned

---

## Context

The τ-bench-style scorer: diff the post-rollout world against an annotated goal state. Implements
spec §3 Module 7. **Subset semantics** — only fields named in `goal_state` are asserted; the score is
path-independent (scores the world, not the exact tool calls).

---

## Scope

- Create `parrot/eval/evaluators/state_based.py` with:
  - `@register_metric("state_match")` `StateMatch(Metric)`:
    `value = matched_assertions / total_assertions`; `passed = all goal assertions hold AND no
    forbidden entity present`; `detail = {"mismatches": [...], "forbidden_present": [...]}`.
  - `@register_evaluator("state_based")` `StateBasedEvaluator(AbstractEvaluator)`: reads
    `task.expected["goal_state"]` (subset diff) and optional `task.expected["forbidden"]`; scores
    against `trajectory.final_state` (falling back to `await sandbox.snapshot()` if absent).
- Goal format per spec: `goal_state = {collection: {entity_id: {field: value}}}`,
  `forbidden = {collection: [entity_id, ...]} | None`.
- Export from `parrot/eval/__init__.py`.

**NOT in scope**: runner population of `final_state` (TASK-1425), benchmark data (TASK-1428).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/evaluators/state_based.py` | CREATE | Evaluator + metric |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export `StateBasedEvaluator`, `StateMatch` |
| `packages/ai-parrot/tests/eval/test_state_based.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.evaluators.base import AbstractEvaluator, Metric        # TASK-1421
from parrot.eval.registry import register_evaluator, register_metric     # TASK-1416
from parrot.eval.models import EvalTask, Trajectory, EvalResult, MetricScore  # TASK-1415
from parrot.eval.sandbox.base import Sandbox                              # TASK-1417
```

### Does NOT Exist
- ~~A generic deep-diff util in `parrot`~~ — implement the subset diff inline (small, explicit).

---

## Implementation Notes

### Key Constraints
- **Subset match**: iterate only the keys present in `goal_state`; ignore unrelated state the agent
  touched. Each `{collection, entity_id, field}` assertion is one unit toward `value`.
- A missing entity/collection or a wrong value is a mismatch (recorded with its path in `detail`).
- `forbidden` entities present → `passed = False` regardless of goal matches.
- Prefer `trajectory.final_state`; only call `sandbox.snapshot()` if `final_state is None` — keeps
  re-scoring fully offline (spec §7).

### Pattern to Follow
```python
@register_metric("state_match")
class StateMatch(Metric):
    name = "state_match"
    async def score(self, task, trajectory, sandbox=None):
        final = trajectory.final_state if trajectory.final_state is not None else await sandbox.snapshot()
        goal = (task.expected or {}).get("goal_state", {})
        # count matched/total; collect mismatches + forbidden_present ...
```

---

## Acceptance Criteria

- [ ] `from parrot.eval import StateBasedEvaluator, StateMatch` resolves.
- [ ] `get_evaluator("state_based")` and `get_metric("state_match")` resolve (registered).
- [ ] Subset pass: state with extra fields beyond `goal_state` still passes.
- [ ] Mismatch + `forbidden_present` recorded in `MetricScore.detail`.
- [ ] Evaluator scores `trajectory.final_state` without a live sandbox.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_state_based.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/evaluators/state_based.py`

---

## Test Specification

```python
import pytest
from parrot.eval import StateBasedEvaluator
from parrot.eval.models import EvalTask, Trajectory

async def test_subset_pass_ignores_extra():
    task = EvalTask(task_id="t", inputs={},
                    expected={"goal_state": {"issues": {"P-1": {"assignee": "oncall"}}}})
    tr = Trajectory(task_id="t", attempt=1,
                    final_state={"issues": {"P-1": {"assignee": "oncall", "title": "x"}}})
    assert (await StateBasedEvaluator().evaluate(task, tr)).passed

async def test_forbidden_fails():
    task = EvalTask(task_id="t", inputs={},
                    expected={"goal_state": {}, "forbidden": {"issues": ["P-9"]}})
    tr = Trajectory(task_id="t", attempt=1, final_state={"issues": {"P-9": {"a": 1}}})
    assert (await StateBasedEvaluator().evaluate(task, tr)).passed is False
```

---

## Agent Instructions

Standard SDD flow: verify the contract, set index `in-progress`, implement, run tests + ruff, move to
`completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
