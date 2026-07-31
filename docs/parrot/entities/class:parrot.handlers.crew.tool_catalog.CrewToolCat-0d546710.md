---
type: Wiki Entity
title: CrewToolCatalogHandler
id: class:parrot.handlers.crew.tool_catalog.CrewToolCatalogHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Returns the curated tool catalog for the crew builder UI.
---

# CrewToolCatalogHandler

Defined in [`parrot.handlers.crew.tool_catalog`](../summaries/mod:parrot.handlers.crew.tool_catalog.md).

```python
class CrewToolCatalogHandler(BaseView)
```

Returns the curated tool catalog for the crew builder UI.

## Methods

- `def post_init(self, *args, **kwargs) -> None`
- `async def get(self) -> Any` — Return the curated crew tool catalog as a JSON array.
