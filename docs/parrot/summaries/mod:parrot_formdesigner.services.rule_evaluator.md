---
type: Wiki Summary
title: parrot_formdesigner.services.rule_evaluator
id: mod:parrot_formdesigner.services.rule_evaluator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Authoritative server-side rule evaluator for FormSchema conditional sections.
relates_to:
- concept: class:parrot_formdesigner.services.rule_evaluator.RuleEvaluator
  rel: defines
- concept: class:parrot_formdesigner.services.rule_evaluator.RuleResolution
  rel: defines
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
---

# `parrot_formdesigner.services.rule_evaluator`

Authoritative server-side rule evaluator for FormSchema conditional sections.

Given a :class:`~parrot_formdesigner.core.schema.FormSchema` and a dict of
current field answers, :class:`RuleEvaluator` resolves visibility, required
state, computed values (from ``DependencyOperation``), and cascade-clears —
processing pre-dependencies, post-dependencies, and operations in topological
order.

Design notes (spec §8):
- The JSON schema representation is *declarative* and intended for client-side
  interpretation.  This Python evaluator is the **authoritative** server-side
  implementation.
- Evaluation order: topological sort of the dependency graph; cycles were
  already rejected by :class:`~parrot_formdesigner.services.validators.FormValidator`
  — any residual cycle is skipped with a warning.
- ``NOT`` logic negates the AND-combination of conditions (spec §8 explicit
  default).
- ``reload_options`` and ARRAY-operand aggregation scope are open questions in
  the spec (§8).  The evaluator records ``reload_options`` targets in
  ``computed`` as a sentinel (``"__reload__"``) and uses a flat list for
  AGGREGATE operands.  TODO(FEAT-234 open question): revisit once spec §8 is
  finalised.

## Classes

- **`RuleResolution(BaseModel)`** — Result of evaluating all conditional-section rules for a form submission.
- **`RuleEvaluator`** — Authoritative server-side rule evaluator for FormSchema conditional sections.
