---
type: Wiki Entity
title: DatabaseToolkit
id: class:parrot.bots.database.toolkits.base.DatabaseToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for all database toolkits.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# DatabaseToolkit

Defined in [`parrot.bots.database.toolkits.base`](../summaries/mod:parrot.bots.database.toolkits.base.md).

```python
class DatabaseToolkit(AbstractToolkit, ABC)
```

Abstract base class for all database toolkits.

Subclasses implement the two abstract methods (``search_schema`` and
``execute_query``).  All public ``async`` methods are automatically
converted to LLM-callable tools by ``AbstractToolkit._generate_tools()``.

Internal lifecycle methods (``start``, ``stop``, ``cleanup``,
``get_table_metadata``, ``health_check``) are hidden from the LLM via
``exclude_tools``.

## Methods

- `async def start(self) -> None` — Connect to the database using asyncdb.
- `async def stop(self) -> None` — Close the database connection and release resources.
- `async def cleanup(self) -> None` — Alias for ``stop()``.
- `async def health_check(self) -> bool` — Check if the database connection is alive.
- `async def get_table_metadata(self, schema_name: str, table_name: str) -> Optional[TableMetadata]` — Retrieve cached table metadata for the given table.
- `async def search_schema(self, search_term: str, schema_name: Optional[str]=None, limit: int=10) -> List[TableMetadata]` — Search for tables/columns matching *search_term*.
- `async def execute_query(self, query: str, limit: int=1000, timeout: int=30) -> QueryExecutionResponse` — Execute a query and return results.
