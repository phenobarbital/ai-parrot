---
type: Wiki Summary
title: parrot_formdesigner.api.controls
id: mod:parrot_formdesigner.api.controls
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler for ``GET /api/v1/form-controls``.
relates_to:
- concept: func:parrot_formdesigner.api.controls.handle_form_controls
  rel: defines
- concept: mod:parrot_formdesigner.controls
  rel: references
---

# `parrot_formdesigner.api.controls`

HTTP handler for ``GET /api/v1/form-controls``.

Returns the registered form-control metadata as ``{"controls": [...]}``.
The registry is seeded by ``parrot_formdesigner.controls.builtin`` on
``import parrot_formdesigner.api``.

## Functions

- `async def handle_form_controls(request: web.Request) -> web.Response` — GET /api/v1/form-controls — return the registered control metadata.
