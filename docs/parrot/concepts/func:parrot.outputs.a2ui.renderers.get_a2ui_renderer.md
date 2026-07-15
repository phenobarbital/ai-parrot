---
type: Concept
title: get_a2ui_renderer()
id: func:parrot.outputs.a2ui.renderers.get_a2ui_renderer
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve a renderer class by name, importing its satellite module if needed.
---

# get_a2ui_renderer

```python
def get_a2ui_renderer(name: str) -> type[AbstractA2UIRenderer]
```

Resolve a renderer class by name, importing its satellite module if needed.

Args:
    name: The renderer name (e.g. ``"ssr_html"``, ``"pdf"``).

Returns:
    The registered renderer class.

Raises:
    ImportError: If the satellite module cannot be imported (message names the
        required pip extra), or if the module imported but did not register.
