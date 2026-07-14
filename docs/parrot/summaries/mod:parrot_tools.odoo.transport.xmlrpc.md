---
type: Wiki Summary
title: parrot_tools.odoo.transport.xmlrpc
id: mod:parrot_tools.odoo.transport.xmlrpc
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: XML-RPC transport for Odoo (v14-18 and any version with /xmlrpc/2/ enabled).
relates_to:
- concept: class:parrot_tools.odoo.transport.xmlrpc.TimeoutSafeTransport
  rel: defines
- concept: class:parrot_tools.odoo.transport.xmlrpc.TimeoutTransport
  rel: defines
- concept: class:parrot_tools.odoo.transport.xmlrpc.XmlRpcTransport
  rel: defines
- concept: mod:parrot.interfaces.odoointerface
  rel: references
- concept: mod:parrot_tools.odoo.transport.base
  rel: references
---

# `parrot_tools.odoo.transport.xmlrpc`

XML-RPC transport for Odoo (v14-18 and any version with /xmlrpc/2/ enabled).

Uses ``xmlrpc.client`` (synchronous) and offloads RPC calls to a worker thread
via ``asyncio.to_thread`` so the event loop stays unblocked. This mirrors the
classic Odoo XML-RPC pattern used by Flowtask's OdooInjector and odoo-mcp-pro
for older Odoo releases.

## Classes

- **`TimeoutTransport(xmlrpc.client.Transport)`** — HTTP XML-RPC transport with explicit socket timeout.
- **`TimeoutSafeTransport(xmlrpc.client.SafeTransport)`** — HTTPS XML-RPC transport with explicit socket timeout.
- **`XmlRpcTransport(AbstractOdooTransport)`** — Synchronous XML-RPC client wrapped in an async surface.
