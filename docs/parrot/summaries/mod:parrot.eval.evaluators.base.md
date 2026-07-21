---
type: Wiki Summary
title: parrot.eval.evaluators.base
id: mod:parrot.eval.evaluators.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base classes for evaluation metrics and evaluators.
relates_to:
- concept: class:parrot.eval.evaluators.base.AbstractEvaluator
  rel: defines
- concept: class:parrot.eval.evaluators.base.Metric
  rel: defines
- concept: mod:parrot.eval.models
  rel: references
- concept: mod:parrot.eval.sandbox.base
  rel: references
---

# `parrot.eval.evaluators.base`

Abstract base classes for evaluation metrics and evaluators.

FEAT-217 — Module 6.  These ABCs define the scoring contract — the
polymorphic point of the harness.  Concrete implementations register
themselves via ``@register_metric`` / ``@register_evaluator``.

## Classes

- **`Metric(ABC)`** — Abstract base for a single evaluation metric.
- **`AbstractEvaluator(ABC)`** — Abstract base for evaluators that combine one or more metrics.
