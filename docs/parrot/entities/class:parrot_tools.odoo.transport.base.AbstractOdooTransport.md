---
type: Wiki Entity
title: AbstractOdooTransport
id: class:parrot_tools.odoo.transport.base.AbstractOdooTransport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Common surface for JSON-2, legacy JSON-RPC, and XML-RPC backends.
---

# AbstractOdooTransport

Defined in [`parrot_tools.odoo.transport.base`](../summaries/mod:parrot_tools.odoo.transport.base.md).

```python
class AbstractOdooTransport(ABC)
```

Common surface for JSON-2, legacy JSON-RPC, and XML-RPC backends.

Concrete transports are responsible for authentication, dispatching
toolkit calls, and reporting server version. The toolkit composes one of
these — it never constructs an Odoo client directly.

## Methods

- `async def authenticate(self) -> int` — Authenticate against Odoo and cache the user id.
- `async def execute_kw(self, model: str, method: str, args: list[Any] | None=None, kwargs: dict[str, Any] | None=None) -> Any` — Dispatch a model method via the underlying Odoo external API.
- `async def version(self) -> dict[str, Any]` — Return server version info (no auth required).
- `async def close(self) -> None` — Release any held resources (sessions, sockets).
- `def name(self) -> str` — Human-readable transport identifier ('json2' | 'jsonrpc' | 'xmlrpc').
