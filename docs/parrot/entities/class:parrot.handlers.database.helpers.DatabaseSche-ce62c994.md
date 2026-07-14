---
type: Wiki Entity
title: DatabaseSchemasHandler
id: class:parrot.handlers.database.helpers.DatabaseSchemasHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return cached schema metadata from a running ``DatabaseAgent``.
---

# DatabaseSchemasHandler

Defined in [`parrot.handlers.database.helpers`](../summaries/mod:parrot.handlers.database.helpers.md).

```python
class DatabaseSchemasHandler(BaseView)
```

Return cached schema metadata from a running ``DatabaseAgent``.

## Methods

- `async def get(self, **kwargs: Any) -> web.Response` — List cached schemas or detail a single schema.
