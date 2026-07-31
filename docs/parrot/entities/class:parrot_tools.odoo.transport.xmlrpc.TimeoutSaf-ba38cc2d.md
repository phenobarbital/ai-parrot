---
type: Wiki Entity
title: TimeoutSafeTransport
id: class:parrot_tools.odoo.transport.xmlrpc.TimeoutSafeTransport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTPS XML-RPC transport with explicit socket timeout.
---

# TimeoutSafeTransport

Defined in [`parrot_tools.odoo.transport.xmlrpc`](../summaries/mod:parrot_tools.odoo.transport.xmlrpc.md).

```python
class TimeoutSafeTransport(xmlrpc.client.SafeTransport)
```

HTTPS XML-RPC transport with explicit socket timeout.

## Methods

- `def make_connection(self, host: str) -> http.client.HTTPSConnection`
