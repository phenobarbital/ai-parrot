---
type: Wiki Entity
title: OdooInterface
id: class:parrot.interfaces.odoointerface.OdooInterface
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async interface for Odoo ERP via JSON-RPC 2.0.
---

# OdooInterface

Defined in [`parrot.interfaces.odoointerface`](../summaries/mod:parrot.interfaces.odoointerface.md).

```python
class OdooInterface
```

Async interface for Odoo ERP via JSON-RPC 2.0.

Supports Odoo v16+ (Community and Enterprise).

Attributes:
    config: Validated connection configuration.
    uid: Cached user ID after successful authentication.
    logger: Logger instance.

Example:
    async with OdooInterface(
        url="https://myodoo.com",
        database="mydb",
        username="admin",
        password="secret",
    ) as odoo:
        await odoo.authenticate()
        partners = await odoo.search_read(
            "res.partner",
            domain=[("is_company", "=", True)],
            fields=["name", "email", "phone"],
            limit=10,
        )

## Methods

- `async def close(self) -> None` — Close the underlying aiohttp session explicitly.
- `async def version(self) -> dict[str, Any]` — Return Odoo server version info via the unauthenticated common service.
- `async def authenticate(self) -> int` — Authenticate with Odoo and cache the user ID.
- `async def execute_kw(self, model: str, method: str, args: list[Any] | None=None, kwargs: dict[str, Any] | None=None) -> Any` — Execute any Odoo model method via ``execute_kw``.
- `async def search(self, model: str, domain: list | None=None, offset: int=0, limit: int | None=None, order: str | None=None) -> list[int]` — Search for record IDs matching the domain.
- `async def search_read(self, model: str, domain: list | None=None, fields: list[str] | None=None, offset: int=0, limit: int | None=None, order: str | None=None) -> list[dict[str, Any]]` — Search and read records in a single call.
- `async def read(self, model: str, ids: list[int], fields: list[str] | None=None) -> list[dict[str, Any]]` — Read specific records by ID.
- `async def create(self, model: str, values: dict[str, Any] | list[dict[str, Any]]) -> int | list[int]` — Create one or more records.
- `async def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool` — Update existing records.
- `async def unlink(self, model: str, ids: list[int]) -> bool` — Delete records by ID.
- `async def search_count(self, model: str, domain: list | None=None) -> int` — Return the count of records matching the domain.
- `async def fields_get(self, model: str, attributes: list[str] | None=None) -> dict[str, Any]` — Get field definitions for a model.
