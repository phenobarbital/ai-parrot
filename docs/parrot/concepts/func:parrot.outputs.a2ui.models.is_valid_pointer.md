---
type: Concept
title: is_valid_pointer()
id: func:parrot.outputs.a2ui.models.is_valid_pointer
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return whether ``pointer`` is a syntactically well-formed JSON Pointer.
---

# is_valid_pointer

```python
def is_valid_pointer(pointer: str) -> bool
```

Return whether ``pointer`` is a syntactically well-formed JSON Pointer.

This is a *shape* check only (RFC 6901 grammar). It does NOT verify that the
pointer resolves against any document — resolution is the bake pass's job.

Args:
    pointer: The candidate JSON Pointer string.

Returns:
    ``True`` if ``pointer`` matches the JSON Pointer grammar, else ``False``.
