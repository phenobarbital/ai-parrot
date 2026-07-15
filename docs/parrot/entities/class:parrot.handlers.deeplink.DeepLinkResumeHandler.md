---
type: Wiki Entity
title: DeepLinkResumeHandler
id: class:parrot.handlers.deeplink.DeepLinkResumeHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Web resume handler for A2UI deep links.
---

# DeepLinkResumeHandler

Defined in [`parrot.handlers.deeplink`](../summaries/mod:parrot.handlers.deeplink.md).

```python
class DeepLinkResumeHandler
```

Web resume handler for A2UI deep links.

## Methods

- `async def handle(self, token: str) -> tuple[dict[str, Any], int]` — Consume ``token`` and inject the action; return (body, http_status).
- `def render_landing(self, token: str) -> str` — Return the confirm-before-consume landing HTML (does NOT touch state).
- `async def landing(self, request: web.Request) -> web.Response` — GET entry point: render the confirm page WITHOUT consuming the token.
- `async def resume(self, request: web.Request) -> web.Response` — POST entry point: consume the token and inject the action.
