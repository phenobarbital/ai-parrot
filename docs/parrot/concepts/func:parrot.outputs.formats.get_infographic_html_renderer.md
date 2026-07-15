---
type: Concept
title: get_infographic_html_renderer()
id: func:parrot.outputs.formats.get_infographic_html_renderer
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return ``InfographicHTMLRenderer`` with its concrete type preserved.
---

# get_infographic_html_renderer

```python
def get_infographic_html_renderer()
```

Return ``InfographicHTMLRenderer`` with its concrete type preserved.

Use this instead of ``get_renderer(OutputMode.INFOGRAPHIC)`` when you
need to call ``render_to_html()``, which is not part of the base
``Renderer`` Protocol.

Returns:
    Type[InfographicHTMLRenderer]: The concrete renderer class.
