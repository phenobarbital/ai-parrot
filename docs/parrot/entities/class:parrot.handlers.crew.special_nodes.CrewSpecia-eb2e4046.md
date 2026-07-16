---
type: Wiki Entity
title: CrewSpecialNodeCatalogHandler
id: class:parrot.handlers.crew.special_nodes.CrewSpecialNodeCatalogHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Returns the curated special-node catalog for the crew builder UI.
---

# CrewSpecialNodeCatalogHandler

Defined in [`parrot.handlers.crew.special_nodes`](../summaries/mod:parrot.handlers.crew.special_nodes.md).

```python
class CrewSpecialNodeCatalogHandler(BaseView)
```

Returns the curated special-node catalog for the crew builder UI.

## Methods

- `def post_init(self, *args, **kwargs) -> None`
- `async def get(self) -> Any` — Return the curated special-node catalog as a JSON array.
