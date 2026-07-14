---
type: Wiki Summary
title: parrot.eval.registry
id: mod:parrot.eval.registry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Lightweight decorator registries for evaluators and metrics.
relates_to:
- concept: func:parrot.eval.registry.get_evaluator
  rel: defines
- concept: func:parrot.eval.registry.get_metric
  rel: defines
- concept: func:parrot.eval.registry.list_evaluators
  rel: defines
- concept: func:parrot.eval.registry.list_metrics
  rel: defines
- concept: func:parrot.eval.registry.register_evaluator
  rel: defines
- concept: func:parrot.eval.registry.register_metric
  rel: defines
---

# `parrot.eval.registry`

Lightweight decorator registries for evaluators and metrics.

FEAT-217 — Module 2. These registries are intentionally minimal: plain
``dict`` backed, import-cycle free (no dependency on the ABCs), and
independent from the bot-specific ``AgentRegistry``.

Usage::

    from parrot.eval.registry import register_evaluator, get_evaluator

    @register_evaluator("state_based")
    class StateBasedEvaluator(AbstractEvaluator):
        ...

    klass = get_evaluator("state_based")

## Functions

- `def register_evaluator(name: str)` — Class decorator that registers an evaluator under *name*.
- `def get_evaluator(name: str) -> type` — Return the evaluator class registered under *name*.
- `def list_evaluators() -> list[str]` — Return a sorted list of all registered evaluator names.
- `def register_metric(name: str)` — Class decorator that registers a metric under *name*.
- `def get_metric(name: str) -> type` — Return the metric class registered under *name*.
- `def list_metrics() -> list[str]` — Return a sorted list of all registered metric names.
