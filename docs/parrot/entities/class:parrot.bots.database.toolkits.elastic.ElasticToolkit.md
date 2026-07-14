---
type: Wiki Entity
title: ElasticToolkit
id: class:parrot.bots.database.toolkits.elastic.ElasticToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Elasticsearch toolkit with DSL query support.
relates_to:
- concept: class:parrot.bots.database.toolkits.base.DatabaseToolkit
  rel: extends
---

# ElasticToolkit

Defined in [`parrot.bots.database.toolkits.elastic`](../summaries/mod:parrot.bots.database.toolkits.elastic.md).

```python
class ElasticToolkit(DatabaseToolkit)
```

Elasticsearch toolkit with DSL query support.

Exposes index search, DSL query generation/execution, and
aggregation as LLM-callable tools.

## Methods

- `async def search_schema(self, search_term: str, schema_name: Optional[str]=None, limit: int=10) -> List[TableMetadata]` — Search for Elasticsearch indices matching the search term.
- `async def execute_query(self, query: str, limit: int=1000, timeout: int=30) -> QueryExecutionResponse` — Execute an Elasticsearch DSL query (as JSON string).
- `async def search_indices(self, search_term: str, limit: int=10) -> List[TableMetadata]` — Search for Elasticsearch indices matching *search_term*.
- `async def generate_dsl_query(self, natural_language: str, index: Optional[str]=None) -> str` — Generate context for Elasticsearch DSL query generation.
- `async def run_aggregation(self, index: str, agg_body: str) -> QueryExecutionResponse` — Run an Elasticsearch aggregation.
