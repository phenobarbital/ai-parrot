---
type: Concept
title: setup_form_ui()
id: func:parrot_formdesigner.ui.routes.setup_form_ui
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mount the HTML page + Telegram WebApp surface on ``app``.
---

# setup_form_ui

```python
def setup_form_ui(app: web.Application, registry: FormRegistry, *, base_path: str='', protect_pages: bool=True) -> None
```

Mount the HTML page + Telegram WebApp surface on ``app``.

Telegram routes are public (no auth). HTML page routes honour
``protect_pages``.

Args:
    app: aiohttp application to register routes on.
    registry: Pre-built ``FormRegistry`` shared across requests.
    base_path: URL prefix for all routes (default ``""`` — root mount).
    protect_pages: When ``True`` (default), HTML page routes go through
        navigator-auth. When ``False``, they run without auth (useful
        when authentication is handled client-side).
