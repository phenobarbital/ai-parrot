---
type: Wiki Entity
title: DocumentDBToolkit
id: class:parrot.bots.database.toolkits.documentdb.DocumentDBToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DocumentDB/MongoDB toolkit with MQL support.
relates_to:
- concept: class:parrot.bots.database.toolkits.base.DatabaseToolkit
  rel: extends
---

# DocumentDBToolkit

Defined in [`parrot.bots.database.toolkits.documentdb`](../summaries/mod:parrot.bots.database.toolkits.documentdb.md).

```python
class DocumentDBToolkit(DatabaseToolkit)
```

DocumentDB/MongoDB toolkit with MQL support.

Exposes collection search, MQL query generation/execution, and
collection exploration as LLM-callable tools.

## Methods

- `async def search_schema(self, search_term: str, schema_name: Optional[str]=None, limit: int=10) -> List[TableMetadata]` — Search for collections matching the search term.
- `async def execute_query(self, query: str, limit: int=1000, timeout: int=30) -> QueryExecutionResponse` — Execute a MongoDB query (JSON string).
- `async def search_collections(self, search_term: str, database: Optional[str]=None, limit: int=10) -> List[TableMetadata]` — Search for MongoDB/DocumentDB collections matching *search_term*.
- `async def generate_mql_query(self, natural_language: str, collection: Optional[str]=None) -> str` — Generate context for MongoDB query generation.
- `async def explore_collection(self, collection: str, sample_size: int=5) -> str` — Explore a collection's structure by sampling documents.
