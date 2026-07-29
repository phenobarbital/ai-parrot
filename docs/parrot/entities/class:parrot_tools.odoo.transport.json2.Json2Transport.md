---
type: Wiki Entity
title: Json2Transport
id: class:parrot_tools.odoo.transport.json2.Json2Transport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async transport for Odoo's External JSON-2 API.
relates_to:
- concept: class:parrot_tools.odoo.transport.base.AbstractOdooTransport
  rel: extends
---

# Json2Transport

Defined in [`parrot_tools.odoo.transport.json2`](../summaries/mod:parrot_tools.odoo.transport.json2.md).

```python
class Json2Transport(AbstractOdooTransport)
```

Async transport for Odoo's External JSON-2 API.

## Methods

- `def from_config(cls, config: OdooConfig) -> 'Json2Transport'` — Build a JSON-2 transport from an :class:`OdooConfig`.
- `async def authenticate(self) -> int` — Validate the bearer API key and cache the current user id when available.
- `async def execute_kw(self, model: str, method: str, args: list[Any] | None=None, kwargs: dict[str, Any] | None=None) -> Any`
- `async def version(self) -> dict[str, Any]`
- `async def close(self) -> None`
