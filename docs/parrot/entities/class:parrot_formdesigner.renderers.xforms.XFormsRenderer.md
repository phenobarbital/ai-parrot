---
type: Wiki Entity
title: XFormsRenderer
id: class:parrot_formdesigner.renderers.xforms.XFormsRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Render a ``FormSchema`` as an XForms 1.1 (W3C) document.
---

# XFormsRenderer

Defined in [`parrot_formdesigner.renderers.xforms`](../summaries/mod:parrot_formdesigner.renderers.xforms.md).

```python
class XFormsRenderer(AbstractFormRenderer)
```

Render a ``FormSchema`` as an XForms 1.1 (W3C) document.

Output: ``RenderedForm(content=<xml-bytes>, content_type="application/xml")``.

The renderer ignores ``style`` / ``prefilled`` / ``errors`` parameters
(HTML-only concerns) but preserves them for base-class compatibility.

## Methods

- `async def render(self, form: FormSchema, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None) -> RenderedForm` — Render ``form`` as an XForms 1.1 XML document.
