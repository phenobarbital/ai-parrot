---
type: Wiki Summary
title: parrot.services.whatsapp
id: mod:parrot.services.whatsapp
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WhatsApp Configuration API Handler.
relates_to:
- concept: class:parrot.services.whatsapp.WhatsAppConfigHandler
  rel: defines
- concept: class:parrot.services.whatsapp.WhatsAppQRHandler
  rel: defines
- concept: func:parrot.services.whatsapp.setup_whatsapp_bridge
  rel: defines
- concept: func:parrot.services.whatsapp.whatsapp_dashboard_page
  rel: defines
- concept: mod:parrot.autonomous
  rel: references
---

# `parrot.services.whatsapp`

WhatsApp Configuration API Handler.

Provides REST endpoints to manage the WhatsApp Bridge:
- QR code authentication (superuser-only)
- Connection status and hook management
- Test messaging and statistics

## Classes

- **`WhatsAppQRHandler(_WhatsAppMixin, BaseView)`** — Authenticated endpoints for QR code authentication.
- **`WhatsAppConfigHandler(_WhatsAppMixin, BaseView)`** — Authenticated endpoints for WhatsApp bridge management.

## Functions

- `async def whatsapp_dashboard_page(request: web.Request) -> web.Response` — Serve the WhatsApp dashboard HTML (no auth required).
- `def setup_whatsapp_bridge(app: web.Application, orchestrator: Optional[object]=None, bridge_url: Optional[str]=None) -> None` — Register WhatsApp configuration API endpoints.
