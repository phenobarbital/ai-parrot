---
type: Wiki Entity
title: HTML5Renderer
id: class:parrot.forms.renderers.html5.HTML5Renderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renders FormSchema as an HTML5 <form> fragment.
---

# HTML5Renderer

Defined in [`parrot.forms.renderers.html5`](../summaries/mod:parrot.forms.renderers.html5.md).

```python
class HTML5Renderer(AbstractFormRenderer)
```

Renders FormSchema as an HTML5 <form> fragment.

Uses Jinja2 templates (with autoescape=True) to produce HTML that can
be served via API and embedded in any web page.

Output:
- A <form> fragment (no <html>, <head>, <body>)
- HTML5 validation attributes (required, minlength, maxlength, min, max, pattern, step)
- data-depends-on attributes for conditional visibility rules
- CSS classes for layout (form-layout--single_column, form-layout--two_column, etc.)
- content_type="text/html"

Example:
    renderer = HTML5Renderer()
    result = await renderer.render(form_schema)
    html_fragment = result.content

## Methods

- `async def render(self, form: FormSchema, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None) -> RenderedForm` — Render a FormSchema as an HTML5 form fragment.
