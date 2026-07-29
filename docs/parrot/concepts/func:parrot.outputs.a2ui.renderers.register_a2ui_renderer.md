---
type: Concept
title: register_a2ui_renderer()
id: func:parrot.outputs.a2ui.renderers.register_a2ui_renderer
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register an A2UI renderer class under ``name``.
---

# register_a2ui_renderer

```python
def register_a2ui_renderer(name: str, capabilities: RendererCapabilities) -> Callable[[type[AbstractA2UIRenderer]], type[AbstractA2UIRenderer]]
```

Register an A2UI renderer class under ``name``.

Args:
    name: The renderer name used with :func:`get_a2ui_renderer`.
    capabilities: The renderer's declared capabilities; also assigned to the
        class as its ``capabilities`` attribute.

Returns:
    The class decorator.

Raises:
    TypeError: If ``capabilities`` is not a :class:`RendererCapabilities`.
