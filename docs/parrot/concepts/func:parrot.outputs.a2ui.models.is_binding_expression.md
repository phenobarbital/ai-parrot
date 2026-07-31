---
type: Concept
title: is_binding_expression()
id: func:parrot.outputs.a2ui.models.is_binding_expression
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return whether ``value`` is a data-model binding expression.
---

# is_binding_expression

```python
def is_binding_expression(value: Any) -> bool
```

Return whether ``value`` is a data-model binding expression.

A binding is a mapping of the form ``{"$bind": "<json-pointer>"}``.

Args:
    value: Any property value.

Returns:
    ``True`` if ``value`` is a binding expression mapping, else ``False``.
