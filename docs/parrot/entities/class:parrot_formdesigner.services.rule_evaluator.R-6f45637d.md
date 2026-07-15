---
type: Wiki Entity
title: RuleResolution
id: class:parrot_formdesigner.services.rule_evaluator.RuleResolution
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of evaluating all conditional-section rules for a form submission.
---

# RuleResolution

Defined in [`parrot_formdesigner.services.rule_evaluator`](../summaries/mod:parrot_formdesigner.services.rule_evaluator.md).

```python
class RuleResolution(BaseModel)
```

Result of evaluating all conditional-section rules for a form submission.

Attributes:
    visible: Maps ``field_id`` → ``True`` (visible) / ``False`` (hidden).
        Fields with no applicable rule default to ``True``.
    required: Maps ``field_id`` → ``True`` (required) / ``False`` (not
        required).  Inherits the ``FormField.required`` baseline; rules may
        flip this.
    computed: Maps ``field_id`` → computed value produced by a
        ``DependencyOperation`` or ``post_depends`` set/calc effect.
        ``"__reload__"`` is a sentinel for ``reload_options`` targets
        (TODO(FEAT-234 open question)).
    cleared: List of ``field_id`` values whose answers should be cleared
        (``cascade_clear`` effect).
