---
type: Concept
title: handle_form_controls()
id: func:parrot_formdesigner.api.controls.handle_form_controls
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: GET /api/v1/form-controls — return the registered control metadata.
---

# handle_form_controls

```python
async def handle_form_controls(request: web.Request) -> web.Response
```

GET /api/v1/form-controls — return the registered control metadata.

Args:
    request: Incoming aiohttp request.

Returns:
    JSON response ``{"controls": [<FieldControlMetadata.model_dump()>, ...]}``.
