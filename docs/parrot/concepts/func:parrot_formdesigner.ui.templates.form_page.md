---
type: Concept
title: form_page()
id: func:parrot_formdesigner.ui.templates.form_page
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the HTML body wrapping a rendered form fragment.
---

# form_page

```python
def form_page(form_fragment: str) -> str
```

Return the HTML body wrapping a rendered form fragment.

Args:
    form_fragment: Rendered HTML5 form fragment.

Returns:
    HTML body string with the form wrapped in a card.

Warning:
    ``form_fragment`` is inserted raw — the caller MUST ensure the
    fragment was produced by a trusted renderer (e.g. HTML5Renderer)
    and contains no unescaped user-controlled content.
