---
type: Concept
title: register_evaluator()
id: func:parrot.eval.registry.register_evaluator
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Class decorator that registers an evaluator under *name*.
---

# register_evaluator

```python
def register_evaluator(name: str)
```

Class decorator that registers an evaluator under *name*.

Args:
    name: Registry key.  Must be unique; a duplicate raises
        ``ValueError``.

Returns:
    The class unchanged (decorator pattern).

Raises:
    ValueError: If *name* is already registered.

Example::

    @register_evaluator("state_based")
    class StateBasedEvaluator(AbstractEvaluator):
        ...
