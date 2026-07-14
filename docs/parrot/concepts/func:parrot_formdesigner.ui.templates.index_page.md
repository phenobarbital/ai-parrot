---
type: Concept
title: index_page()
id: func:parrot_formdesigner.ui.templates.index_page
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the HTML body for the index page (prompt builder + DB loader).
---

# index_page

```python
def index_page(prefix: str='') -> str
```

Return the HTML body for the index page (prompt builder + DB loader).

The embedded JavaScript declares a ``FORM_PREFIX`` constant so all
``fetch()`` calls and ``window.location.href`` redirects respect the
mount point configured via ``setup_form_routes(..., prefix=...)``.

Args:
    prefix: URL prefix where the form-designer is mounted.

Returns:
    HTML body string for the landing page.
