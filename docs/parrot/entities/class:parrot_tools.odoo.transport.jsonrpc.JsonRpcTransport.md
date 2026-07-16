---
type: Wiki Entity
title: JsonRpcTransport
id: class:parrot_tools.odoo.transport.jsonrpc.JsonRpcTransport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wrap :class:`parrot.interfaces.OdooInterface` as a transport.
relates_to:
- concept: class:parrot_tools.odoo.transport.base.AbstractOdooTransport
  rel: extends
---

# JsonRpcTransport

Defined in [`parrot_tools.odoo.transport.jsonrpc`](../summaries/mod:parrot_tools.odoo.transport.jsonrpc.md).

```python
class JsonRpcTransport(AbstractOdooTransport)
```

Wrap :class:`parrot.interfaces.OdooInterface` as a transport.

Delegates all calls to the underlying interface. This remains available for
compatibility with deployments that still require Odoo's legacy ``/jsonrpc``
endpoint; auto-detection prefers JSON-2 for Odoo 19+.

## Methods

- `def uid(self) -> int | None`
- `def uid(self, value: int | None) -> None`
- `def from_config(cls, config: OdooConfig) -> 'JsonRpcTransport'` — Build a transport from an :class:`OdooConfig` payload.
- `async def authenticate(self) -> int`
- `async def execute_kw(self, model: str, method: str, args: list[Any] | None=None, kwargs: dict[str, Any] | None=None) -> Any`
- `async def version(self) -> dict[str, Any]`
- `async def close(self) -> None`
