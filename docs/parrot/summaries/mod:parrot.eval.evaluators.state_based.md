---
type: Wiki Summary
title: parrot.eval.evaluators.state_based
id: mod:parrot.eval.evaluators.state_based
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: State-based evaluator and metric for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.evaluators.state_based.StateBasedEvaluator
  rel: defines
- concept: class:parrot.eval.evaluators.state_based.StateMatch
  rel: defines
- concept: mod:parrot.eval.evaluators.base
  rel: references
- concept: mod:parrot.eval.models
  rel: references
- concept: mod:parrot.eval.registry
  rel: references
- concept: mod:parrot.eval.sandbox.base
  rel: references
---

# `parrot.eval.evaluators.state_based`

State-based evaluator and metric for the Generic Agent Evaluation Harness.

FEAT-217 — Module 7.

``StateMatch``
    Metric that does a subset diff of the final world state against the
    annotated ``goal_state``.  Only keys present in ``goal_state`` are
    asserted; extra state the agent touched is ignored.  Score =
    ``matched_assertions / total_assertions``.

``StateBasedEvaluator``
    Evaluator that runs ``StateMatch`` and optionally checks ``forbidden``
    entities.  ``passed`` iff all goal assertions hold AND no forbidden
    entity is present.

## Classes

- **`StateMatch(Metric)`** — Subset-match metric comparing final state to ``goal_state``.
- **`StateBasedEvaluator(AbstractEvaluator)`** — Evaluator for state-based (τ-bench style) agent tasks.
