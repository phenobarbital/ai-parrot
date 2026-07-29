---
type: Concept
title: schema_page()
id: func:parrot_formdesigner.ui.templates.schema_page
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the HTML body for the JSON Schema view page.
---

# schema_page

```python
def schema_page(form_id: str, title: str, schema_json: str, style_json: str, prefix: str='') -> str
```

Return the HTML body for the JSON Schema view page.

Args:
    form_id: The form identifier.
    title: Human-readable form title.
    schema_json: Pretty-printed JSON Schema string.
    style_json: Pretty-printed Style Schema string.
    prefix: URL prefix where the form-designer is mounted.

Returns:
    HTML body string with the JSON schema display.
