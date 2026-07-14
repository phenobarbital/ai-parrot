---
type: Concept
title: get_evaluator()
id: func:parrot.eval.registry.get_evaluator
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the evaluator class registered under *name*.
---

# get_evaluator

```python
def get_evaluator(name: str) -> type
```

Return the evaluator class registered under *name*.

Args:
    name: Registry key used with ``@register_evaluator``.

Returns:
    The registered class.

Raises:
    KeyError: If *name* has not been registered.
