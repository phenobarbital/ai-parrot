---
type: Concept
title: iter_controls()
id: func:parrot_formdesigner.controls.registry.iter_controls
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Yield registered controls in registration order.
---

# iter_controls

```python
def iter_controls() -> Iterator[FieldControlMetadata]
```

Yield registered controls in registration order.

Yields:
    Each ``FieldControlMetadata`` instance in registration order.
