---
type: Wiki Entity
title: GigSmartClient
id: class:parrot_tools.interfaces.gigsmart.client.GigSmartClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: aiohttp-based GraphQL client for the GigSmart API.
---

# GigSmartClient

Defined in [`parrot_tools.interfaces.gigsmart.client`](../summaries/mod:parrot_tools.interfaces.gigsmart.client.md).

```python
class GigSmartClient
```

aiohttp-based GraphQL client for the GigSmart API.

Usage::

    config = GigSmartConfig(client_id="...", client_secret="...")
    async with GigSmartClient(config) as client:
        data = await client.execute("query { viewer { id } }")

Args:
    config: GigSmartConfig carrying endpoint URLs and credentials.

## Methods

- `async def start(self) -> None` — Open the underlying aiohttp.ClientSession.
- `async def close(self) -> None` — Close the underlying aiohttp.ClientSession.
- `async def execute(self, document: str, variables: dict | None=None, *, operation_name: str | None=None, is_mutation: bool=False) -> dict` — Execute a GraphQL operation against the GigSmart API.
- `async def paginate(self, document: str, variables: dict, extract_path: str, page_size: int=25) -> list[dict]` — Fetch all pages of a Relay connection and return all nodes.
