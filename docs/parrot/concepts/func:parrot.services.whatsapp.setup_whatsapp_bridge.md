---
type: Concept
title: setup_whatsapp_bridge()
id: func:parrot.services.whatsapp.setup_whatsapp_bridge
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register WhatsApp configuration API endpoints.
---

# setup_whatsapp_bridge

```python
def setup_whatsapp_bridge(app: web.Application, orchestrator: Optional[object]=None, bridge_url: Optional[str]=None) -> None
```

Register WhatsApp configuration API endpoints.

Args:
    app: aiohttp Application instance.
    orchestrator: AutonomousOrchestrator (or compatible) instance.
    bridge_url: WhatsApp Bridge URL (default ``http://localhost:8765``).

Usage::

    from parrot.services.whatsapp import setup_whatsapp_bridge

    setup_whatsapp_bridge(app, orchestrator)
