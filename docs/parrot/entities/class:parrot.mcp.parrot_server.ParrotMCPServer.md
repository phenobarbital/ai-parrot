---
type: Wiki Entity
title: ParrotMCPServer
id: class:parrot.mcp.parrot_server.ParrotMCPServer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manage lifecycle of multiple MCP servers (multi-transport) attached to an
  aiohttp app.
---

# ParrotMCPServer

Defined in [`parrot.mcp.parrot_server`](../summaries/mod:parrot.mcp.parrot_server.md).

```python
class ParrotMCPServer
```

Manage lifecycle of multiple MCP servers (multi-transport) attached to an aiohttp app.

## Methods

- `def setup(self, app: web.Application) -> None` — Register lifecycle hooks inside the aiohttp application.
- `async def on_startup(self, app: web.Application) -> None` — Start the MCP server once aiohttp finishes bootstrapping.
- `async def on_shutdown(self, app: web.Application) -> None` — Stop the MCP server when aiohttp starts shutting down.
