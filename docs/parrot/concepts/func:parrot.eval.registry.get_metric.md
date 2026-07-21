---
type: Concept
title: get_metric()
id: func:parrot.eval.registry.get_metric
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the metric class registered under *name*.
---

# get_metric

```python
def get_metric(name: str) -> type
```

Return the metric class registered under *name*.

Args:
    name: Registry key used with ``@register_metric``.

Returns:
    The registered class.

Raises:
    KeyError: If *name* has not been registered.
