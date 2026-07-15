---
type: Wiki Summary
title: parrot_formdesigner.api.render
id: mod:parrot_formdesigner.api.render
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Render dispatcher for parrot-formdesigner.
relates_to:
- concept: func:parrot_formdesigner.api.render.get_renderer
  rel: defines
- concept: func:parrot_formdesigner.api.render.handle_render
  rel: defines
- concept: func:parrot_formdesigner.api.render.register_renderer
  rel: defines
- concept: func:parrot_formdesigner.api.render.supported_formats
  rel: defines
- concept: mod:parrot_formdesigner.api._utils
  rel: references
- concept: mod:parrot_formdesigner.renderers.adaptive_card
  rel: references
- concept: mod:parrot_formdesigner.renderers.audio
  rel: references
- concept: mod:parrot_formdesigner.renderers.base
  rel: references
- concept: mod:parrot_formdesigner.renderers.html5
  rel: references
- concept: mod:parrot_formdesigner.renderers.pdf
  rel: references
- concept: mod:parrot_formdesigner.renderers.xforms
  rel: references
---

# `parrot_formdesigner.api.render`

Render dispatcher for parrot-formdesigner.

Provides a name-keyed registry of renderers (``dict[str, AbstractFormRenderer]``)
and the ``handle_render`` aiohttp handler that delegates
``GET /api/v1/forms/{form_id}/render/{format}`` to the renderer registered
under ``{format}``.

V1 seeds two renderers:

- ``"html"`` → :class:`HTML5Renderer`
- ``"adaptive"`` → :class:`AdaptiveCardRenderer`

Wave 2 plugs in additional renderers (``"xml"``, ``"pdf"``) by calling
:func:`register_renderer` at module-import time. ``GET /api/v1/forms/{id}/render/{unknown}``
returns ``415 Unsupported Media Type`` with ``{"supported": [...]}``.

## Functions

- `def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None` — Register (or overwrite) a renderer under ``format_key``.
- `def get_renderer(format_key: str) -> AbstractFormRenderer | None` — Return the renderer registered under ``format_key`` or ``None``.
- `def supported_formats() -> list[str]` — Return the sorted list of currently registered format keys.
- `async def handle_render(request: web.Request) -> web.Response` — GET /api/v1/forms/{form_id}/render/{format} — render dispatcher.
