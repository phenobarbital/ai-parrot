---
type: Wiki Entity
title: RuleEvaluator
id: class:parrot_formdesigner.services.rule_evaluator.RuleEvaluator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Authoritative server-side rule evaluator for FormSchema conditional sections.
---

# RuleEvaluator

Defined in [`parrot_formdesigner.services.rule_evaluator`](../summaries/mod:parrot_formdesigner.services.rule_evaluator.md).

```python
class RuleEvaluator
```

Authoritative server-side rule evaluator for FormSchema conditional sections.

Given a :class:`~parrot_formdesigner.core.schema.FormSchema` and current
answers, resolves visibility, required state, computed values, and
cascade-clears for all fields.

Pre-dependencies (``FormField.depends_on``) are evaluated first, then
post-dependencies (``FormField.post_depends``) in topological order.

Example::

    evaluator = RuleEvaluator()
    resolution = await evaluator.resolve(form_schema, {"age": 30})
    if not resolution.visible.get("guardian_name", True):
        # field is hidden — skip it
        ...

## Methods

- `async def resolve(self, form: FormSchema, answers: dict[str, Any], *, locale: str='en', location_vars: dict[str, Any] | None=None, visit_context: dict[str, Any] | None=None) -> RuleResolution` — Resolve all conditional-section rules for ``form`` against ``answers``.
