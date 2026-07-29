---
type: Wiki Entity
title: TimeoutTransport
id: class:parrot_tools.odoo.transport.xmlrpc.TimeoutTransport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP XML-RPC transport with explicit socket timeout.
---

# TimeoutTransport

Defined in [`parrot_tools.odoo.transport.xmlrpc`](../summaries/mod:parrot_tools.odoo.transport.xmlrpc.md).

```python
class TimeoutTransport(xmlrpc.client.Transport)
```

HTTP XML-RPC transport with explicit socket timeout.

## Methods

- `def make_connection(self, host: str) -> http.client.HTTPConnection`
