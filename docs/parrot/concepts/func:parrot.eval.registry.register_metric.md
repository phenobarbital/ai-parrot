---
type: Concept
title: register_metric()
id: func:parrot.eval.registry.register_metric
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Class decorator that registers a metric under *name*.
---

# register_metric

```python
def register_metric(name: str)
```

Class decorator that registers a metric under *name*.

Args:
    name: Registry key.  Must be unique; a duplicate raises
        ``ValueError``.

Returns:
    The class unchanged (decorator pattern).

Raises:
    ValueError: If *name* is already registered.

Example::

    @register_metric("state_match")
    class StateMatch(Metric):
        ...
