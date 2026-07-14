---
type: Wiki Entity
title: WhatsAppQRHandler
id: class:parrot.services.whatsapp.WhatsAppQRHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Authenticated endpoints for QR code authentication.
---

# WhatsAppQRHandler

Defined in [`parrot.services.whatsapp`](../summaries/mod:parrot.services.whatsapp.md).

```python
class WhatsAppQRHandler(_WhatsAppMixin, BaseView)
```

Authenticated endpoints for QR code authentication.

Routes registered by ``setup_whatsapp_bridge``:
    GET /api/whatsapp/qr         — QR code availability / metadata
    GET /api/whatsapp/qr/image   — raw QR PNG proxied from bridge

## Methods

- `async def get(self)` — Dispatch GET based on path suffix.
