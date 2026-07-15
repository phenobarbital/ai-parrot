---
type: Wiki Entity
title: StateMatch
id: class:parrot.eval.evaluators.state_based.StateMatch
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Subset-match metric comparing final state to ``goal_state``.
relates_to:
- concept: class:parrot.eval.evaluators.base.Metric
  rel: extends
---

# StateMatch

Defined in [`parrot.eval.evaluators.state_based`](../summaries/mod:parrot.eval.evaluators.state_based.md).

```python
class StateMatch(Metric)
```

Subset-match metric comparing final state to ``goal_state``.

Scoring:
    ``value = matched_assertions / total_assertions``
    Each ``{collection, entity_id, field}`` triple in ``goal_state``
    is one assertion unit.  A missing collection/entity or a wrong
    field value counts as a mismatch.

``passed``:
    ``True`` iff all goal assertions match AND no ``forbidden``
    entity is present in the final state.

``detail``:
    ``{"mismatches": [...], "forbidden_present": [...]}``

The evaluator prefers ``trajectory.final_state`` over a live
``sandbox.snapshot()`` so re-scoring works fully offline (spec D5).

## Methods

- `async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None=None) -> MetricScore` — Compute the state-match score.
