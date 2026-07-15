---
type: Concept
title: error_page()
id: func:parrot_formdesigner.ui.templates.error_page
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return an error page body.
---

# error_page

```python
def error_page(message: str, prefix: str='') -> str
```

Return an error page body.

Args:
    message: Human-readable error message.
    prefix: URL prefix where the form-designer is mounted.

Returns:
    HTML body string with the error banner.
