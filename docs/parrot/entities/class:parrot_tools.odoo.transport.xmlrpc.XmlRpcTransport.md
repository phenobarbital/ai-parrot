---
type: Wiki Entity
title: XmlRpcTransport
id: class:parrot_tools.odoo.transport.xmlrpc.XmlRpcTransport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Synchronous XML-RPC client wrapped in an async surface.
relates_to:
- concept: class:parrot_tools.odoo.transport.base.AbstractOdooTransport
  rel: extends
---

# XmlRpcTransport

Defined in [`parrot_tools.odoo.transport.xmlrpc`](../summaries/mod:parrot_tools.odoo.transport.xmlrpc.md).

```python
class XmlRpcTransport(AbstractOdooTransport)
```

Synchronous XML-RPC client wrapped in an async surface.

## Methods

- `def from_config(cls, config: OdooConfig) -> 'XmlRpcTransport'` — Build an XML-RPC transport from an :class:`OdooConfig`.
- `async def authenticate(self) -> int`
- `async def execute_kw(self, model: str, method: str, args: list[Any] | None=None, kwargs: dict[str, Any] | None=None) -> Any`
- `async def version(self) -> dict[str, Any]`
- `async def close(self) -> None`
