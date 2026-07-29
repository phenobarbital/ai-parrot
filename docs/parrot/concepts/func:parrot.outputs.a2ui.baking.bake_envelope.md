---
type: Concept
title: bake_envelope()
id: func:parrot.outputs.a2ui.baking.bake_envelope
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Bake an envelope: resolve all bindings against its data model.'
---

# bake_envelope

```python
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]
```

Bake an envelope: resolve all bindings against its data model.

Args:
    envelope: The ``createSurface`` envelope to bake.

Returns:
    A list of resolved component dicts (``id``/``component``/``properties``/
    ``children``) with zero live bindings.

Raises:
    BakeError: If any binding is unresolvable, or if a live binding survives
        (post-condition guard).
    ImportError: If ``jsonpointer`` is unavailable (names the extra).
