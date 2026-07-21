---
type: Wiki Summary
title: parrot_tools.odoo.transport.detect
id: mod:parrot_tools.odoo.transport.detect
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Auto-detect the best Odoo external API transport for a given server.
relates_to:
- concept: func:parrot_tools.odoo.transport.detect.auto_detect_transport
  rel: defines
- concept: func:parrot_tools.odoo.transport.detect.build_transport
  rel: defines
- concept: mod:parrot.interfaces.odoointerface
  rel: references
- concept: mod:parrot_tools.odoo.transport.base
  rel: references
- concept: mod:parrot_tools.odoo.transport.json2
  rel: references
- concept: mod:parrot_tools.odoo.transport.jsonrpc
  rel: references
- concept: mod:parrot_tools.odoo.transport.xmlrpc
  rel: references
---

# `parrot_tools.odoo.transport.detect`

Auto-detect the best Odoo external API transport for a given server.

Strategy: use the unauthenticated ``/web/version`` endpoint first because it is
the Odoo 19+ replacement for the legacy ``common.version`` service. If it
reports Odoo 19 or newer, prefer JSON-2. Older versions use XML-RPC. When
``/web/version`` is unavailable, fall back to the legacy JSON-RPC version probe
only for compatibility detection.

* ``19.0`` and newer → JSON-2
* anything older or any error → XML-RPC

## Functions

- `async def auto_detect_transport(config: OdooConfig) -> AbstractOdooTransport` — Return the best transport for the given server.
- `def build_transport(protocol: Protocol, config: OdooConfig) -> AbstractOdooTransport | None` — Build a transport for an explicit protocol choice.
