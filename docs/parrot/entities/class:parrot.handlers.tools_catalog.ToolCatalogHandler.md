---
type: Wiki Entity
title: ToolCatalogHandler
id: class:parrot.handlers.tools_catalog.ToolCatalogHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Read-only handler that returns the global tool registry as JSON.
---

# ToolCatalogHandler

Defined in [`parrot.handlers.tools_catalog`](../summaries/mod:parrot.handlers.tools_catalog.md).

```python
class ToolCatalogHandler(BaseView)
```

Read-only handler that returns the global tool registry as JSON.

Only ``GET`` is supported.  The catalog is built on the first request
and cached for the lifetime of the process.

## Methods

- `def post_init(self, *args, **kwargs) -> None` — Initialise the instance logger.
- `async def get(self) -> Any` — Return the tool catalog as a JSON array.
