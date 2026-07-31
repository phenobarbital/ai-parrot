---
type: Concept
title: get_controls()
id: func:parrot_formdesigner.controls.registry.get_controls
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return all registered controls in registration order.
---

# get_controls

```python
def get_controls() -> list[FieldControlMetadata]
```

Return all registered controls in registration order.

Returns:
    A list of ``FieldControlMetadata`` instances in the order they were
    registered. The list is a fresh copy of the registry's values.
