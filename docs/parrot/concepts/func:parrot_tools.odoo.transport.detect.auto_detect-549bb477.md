---
type: Concept
title: auto_detect_transport()
id: func:parrot_tools.odoo.transport.detect.auto_detect_transport
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the best transport for the given server.
---

# auto_detect_transport

```python
async def auto_detect_transport(config: OdooConfig) -> AbstractOdooTransport
```

Return the best transport for the given server.

Probe order:

1. ``/web/version`` — succeeds → inspect ``server_serie``.
   Use JSON-2 when serie ≥ 19.0.
2. Legacy JSON-RPC ``common.version`` — compatibility-only probe.
3. Default to XML-RPC.
