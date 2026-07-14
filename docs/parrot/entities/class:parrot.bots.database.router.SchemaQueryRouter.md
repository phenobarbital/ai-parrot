---
type: Wiki Entity
title: SchemaQueryRouter
id: class:parrot.bots.database.router.SchemaQueryRouter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Routes queries with multi-schema awareness and "show me" pattern recognition.
---

# SchemaQueryRouter

Defined in [`parrot.bots.database.router`](../summaries/mod:parrot.bots.database.router.md).

```python
class SchemaQueryRouter
```

Routes queries with multi-schema awareness and "show me" pattern recognition.

## Methods

- `def register_database(self, identifier: str, toolkit_name: str) -> None` — Register a database identifier for query routing.
- `async def route(self, query: str, user_role: Optional[UserRole]=None, output_components: Optional[OutputComponent]=None, intent_override: Optional[QueryIntent]=None, database: Optional[str]=None) -> RouteDecision` — Enhanced routing with database selection and role inference.
