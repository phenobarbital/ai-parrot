---
type: Wiki Entity
title: TelegramWebAppHandler
id: class:parrot_formdesigner.ui.telegram.TelegramWebAppHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Serves forms as Telegram WebApps and handles REST fallback submissions.
---

# TelegramWebAppHandler

Defined in [`parrot_formdesigner.ui.telegram`](../summaries/mod:parrot_formdesigner.ui.telegram.md).

```python
class TelegramWebAppHandler
```

Serves forms as Telegram WebApps and handles REST fallback submissions.

Args:
    registry: FormRegistry for looking up forms by ID.
    renderer: Optional HTML5Renderer. Created if not provided.
    validator: Optional FormValidator. Created if not provided.

## Methods

- `async def serve_webapp(self, request: web.Request) -> web.Response` — GET /forms/{form_id}/telegram — Serve the form as a Telegram WebApp.
- `async def rest_fallback(self, request: web.Request) -> web.Response` — POST /api/v1/forms/{form_id}/telegram-submit — REST fallback.
