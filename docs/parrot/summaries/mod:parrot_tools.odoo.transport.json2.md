---
type: Wiki Summary
title: parrot_tools.odoo.transport.json2
id: mod:parrot_tools.odoo.transport.json2
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: External JSON-2 transport for Odoo 19+.
relates_to:
- concept: class:parrot_tools.odoo.transport.json2.Json2Transport
  rel: defines
- concept: mod:parrot.interfaces.odoointerface
  rel: references
- concept: mod:parrot_tools.odoo.transport.base
  rel: references
---

# `parrot_tools.odoo.transport.json2`

External JSON-2 transport for Odoo 19+.

Odoo 19 introduced the External JSON-2 API as the replacement for the legacy
XML-RPC and JSON-RPC object services. The endpoint shape is:

    POST /json/2/<model>/<method>

Unlike ``execute_kw``, JSON-2 accepts only named arguments. This transport keeps
the toolkit-facing ``execute_kw`` contract but translates the ORM calls used by
``OdooToolkit`` into JSON-2 request bodies.

## Classes

- **`Json2Transport(AbstractOdooTransport)`** — Async transport for Odoo's External JSON-2 API.
