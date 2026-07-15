---
type: Wiki Entity
title: DependencyRule
id: class:parrot.forms.constraints.DependencyRule
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Rule controlling conditional visibility/behavior of a field or section.
---

# DependencyRule

Defined in [`parrot.forms.constraints`](../summaries/mod:parrot.forms.constraints.md).

```python
class DependencyRule(BaseModel)
```

Rule controlling conditional visibility/behavior of a field or section.

Attributes:
    conditions: List of field conditions that must be evaluated.
    logic: Whether conditions are combined with AND or OR logic.
    effect: The effect applied when conditions are met.
