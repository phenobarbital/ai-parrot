---
type: Wiki Entity
title: WhatsAppConfigHandler
id: class:parrot.services.whatsapp.WhatsAppConfigHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Authenticated endpoints for WhatsApp bridge management.
---

# WhatsAppConfigHandler

Defined in [`parrot.services.whatsapp`](../summaries/mod:parrot.services.whatsapp.md).

```python
class WhatsAppConfigHandler(_WhatsAppMixin, BaseView)
```

Authenticated endpoints for WhatsApp bridge management.

Routes registered by ``setup_whatsapp_bridge``:
    GET    /api/whatsapp/status           — connection status
    POST   /api/whatsapp/disconnect       — stop hooks
    GET    /api/whatsapp/hooks            — list hooks
    POST   /api/whatsapp/hooks            — create hook
    PUT    /api/whatsapp/hooks/{hook_id}  — update hook
    DELETE /api/whatsapp/hooks/{hook_id}  — delete hook
    POST   /api/whatsapp/send             — send test message
    GET    /api/whatsapp/stats            — message statistics

## Methods

- `async def get(self)` — Dispatch GET based on path suffix.
- `async def post(self)` — Dispatch POST based on path suffix.
- `async def put(self)` — Update an existing WhatsApp hook.
- `async def delete(self)` — Delete an existing WhatsApp hook.
