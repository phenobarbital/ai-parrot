---
type: Wiki Entity
title: DependencyRule
id: class:parrot_formdesigner.core.constraints.DependencyRule
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rule controlling conditional visibility/behavior of a field or section.
---

# DependencyRule

Defined in [`parrot_formdesigner.core.constraints`](../summaries/mod:parrot_formdesigner.core.constraints.md).

```python
class DependencyRule(BaseModel)
```

Rule controlling conditional visibility/behavior of a field or section.

Attributes:
    conditions: List of field conditions that must be evaluated.
    logic: How conditions are combined. One of:
        - ``"and"``: all conditions must be true (default; backward-compatible).
        - ``"or"``: at least one condition must be true.
        - ``"xor"``: exactly one condition must be true.
        - ``"not"``: negates the AND-combination of conditions (i.e. NOT(all true)).
    effect: The effect applied when conditions are met.
    operations: Optional list of :class:`DependencyOperation` instances
        that compute or assign values when the rule is triggered.
