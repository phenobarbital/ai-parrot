---
type: Wiki Summary
title: parrot.eval
id: mod:parrot.eval
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generic Agent Evaluation Harness — public surface.
relates_to:
- concept: mod:parrot.eval.datasets
  rel: references
- concept: mod:parrot.eval.evaluators.base
  rel: references
- concept: mod:parrot.eval.evaluators.state_based
  rel: references
- concept: mod:parrot.eval.events
  rel: references
- concept: mod:parrot.eval.models
  rel: references
- concept: mod:parrot.eval.registry
  rel: references
- concept: mod:parrot.eval.rollout
  rel: references
- concept: mod:parrot.eval.runner
  rel: references
- concept: mod:parrot.eval.sandbox.base
  rel: references
- concept: mod:parrot.eval.sandbox.state
  rel: references
- concept: mod:parrot.eval.sink
  rel: references
---

# `parrot.eval`

Generic Agent Evaluation Harness — public surface.

FEAT-217. All public names for the ``parrot.eval`` package are re-exported
from here so callers can do:

    from parrot.eval import EvalRunner, EvalTask, Trajectory, StateBasedEvaluator

``EvalTask.model_rebuild()`` is called here once ``SandboxSpec`` is available
to resolve the forward reference in the ``sandbox_spec`` field.
