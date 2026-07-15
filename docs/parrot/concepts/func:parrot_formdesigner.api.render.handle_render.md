---
type: Concept
title: handle_render()
id: func:parrot_formdesigner.api.render.handle_render
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: GET /api/v1/forms/{form_id}/render/{format} — render dispatcher.
---

# handle_render

```python
async def handle_render(request: web.Request) -> web.Response
```

GET /api/v1/forms/{form_id}/render/{format} — render dispatcher.

Looks up the renderer by ``format`` path-param. On miss returns 415 with
``{"supported": [...]}``. On hit, loads the form from
``request.app["form_registry"]`` and delegates to ``renderer.render(form)``.

Args:
    request: Incoming aiohttp request.

Returns:
    The rendered output with ``Content-Type`` set from the renderer.
