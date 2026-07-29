---
type: Wiki Summary
title: parrot_formdesigner.ui.routes
id: mod:parrot_formdesigner.ui.routes
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Route registration for the HTML / Telegram UI surface of parrot-formdesigner.
relates_to:
- concept: func:parrot_formdesigner.ui.routes.setup_form_ui
  rel: defines
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.ui.handlers
  rel: references
- concept: mod:parrot_formdesigner.ui.telegram
  rel: references
---

# `parrot_formdesigner.ui.routes`

Route registration for the HTML / Telegram UI surface of parrot-formdesigner.

Hard-imports navigator-auth (matching the api package). HTML page routes
honour the ``protect_pages`` flag via the ``_page_wrap`` helper; Telegram
WebApp routes are registered WITHOUT auth (public by design — Telegram
clients must be able to hit them).

Public API:

    setup_form_ui(app, registry, *, base_path="", protect_pages=True) -> None

## Functions

- `def setup_form_ui(app: web.Application, registry: FormRegistry, *, base_path: str='', protect_pages: bool=True) -> None` — Mount the HTML page + Telegram WebApp surface on ``app``.
