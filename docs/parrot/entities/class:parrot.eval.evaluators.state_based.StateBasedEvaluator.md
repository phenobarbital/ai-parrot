---
type: Wiki Entity
title: StateBasedEvaluator
id: class:parrot.eval.evaluators.state_based.StateBasedEvaluator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Evaluator for state-based (τ-bench style) agent tasks.
relates_to:
- concept: class:parrot.eval.evaluators.base.AbstractEvaluator
  rel: extends
---

# StateBasedEvaluator

Defined in [`parrot.eval.evaluators.state_based`](../summaries/mod:parrot.eval.evaluators.state_based.md).

```python
class StateBasedEvaluator(AbstractEvaluator)
```

Evaluator for state-based (τ-bench style) agent tasks.

Uses a single ``StateMatch`` metric: diff the post-rollout world
against the annotated ``goal_state`` + ``forbidden`` in
``task.expected``.

Scoring is path-independent — only the final world state matters, not
the sequence of tool calls that produced it.  Re-scoring is fully
offline when ``trajectory.final_state`` is populated.

## Methods

- `async def evaluate(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None=None) -> EvalResult` — Evaluate the trajectory using state-match scoring.
