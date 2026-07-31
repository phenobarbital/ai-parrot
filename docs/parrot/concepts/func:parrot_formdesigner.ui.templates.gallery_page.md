---
type: Concept
title: gallery_page()
id: func:parrot_formdesigner.ui.templates.gallery_page
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the HTML body for the gallery page.
---

# gallery_page

```python
def gallery_page(form_items_html: str) -> str
```

Return the HTML body for the gallery page.

Args:
    form_items_html: Pre-rendered HTML for the form list items. The
        caller (``FormPageHandler.gallery``) is responsible for
        prefixing hrefs inside this fragment — ``gallery_page`` never
        touches URLs.

Returns:
    HTML body string for the gallery page.

Warning:
    ``form_items_html`` is inserted raw — the caller MUST escape
    all user-controlled content before passing it here.
