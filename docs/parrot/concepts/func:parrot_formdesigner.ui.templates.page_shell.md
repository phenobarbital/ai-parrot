---
type: Concept
title: page_shell()
id: func:parrot_formdesigner.ui.templates.page_shell
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wrap body HTML in a full page shell.
---

# page_shell

```python
def page_shell(title: str, body: str, locale: str='en', nav: bool=True, prefix: str='') -> str
```

Wrap body HTML in a full page shell.

Injects an authentication script that reads the JWT from localStorage
and attaches it as an ``Authorization: Bearer`` header on every
``fetch()`` call targeting the form-designer API. If no token is
present the user is redirected to ``/admin``.

Args:
    title: Page title shown in the browser tab.
    body: Inner HTML content.
    locale: HTML lang attribute value.
    nav: Whether to include the top navigation links.
    prefix: URL prefix where the form-designer is mounted. Empty
        string = legacy behaviour (routes at root).

Returns:
    Complete HTML page string.
