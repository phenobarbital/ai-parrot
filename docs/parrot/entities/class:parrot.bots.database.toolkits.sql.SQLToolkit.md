---
type: Wiki Entity
title: SQLToolkit
id: class:parrot.bots.database.toolkits.sql.SQLToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Common SQL operations with overridable dialect hooks.
relates_to:
- concept: class:parrot.bots.database.toolkits.base.DatabaseToolkit
  rel: extends
---

# SQLToolkit

Defined in [`parrot.bots.database.toolkits.sql`](../summaries/mod:parrot.bots.database.toolkits.sql.md).

```python
class SQLToolkit(DatabaseToolkit)
```

Common SQL operations with overridable dialect hooks.

Subclass and override the ``_get_*`` methods to customize behaviour for
specific SQL dialects (PostgreSQL, BigQuery, etc.).

## Methods

- `async def search_schema(self, search_term: str, schema_name: Optional[str]=None, limit: int=10) -> List[TableMetadata]` — Search schema identifiers (table/column/comment names) matching *search_term*.
- `async def describe_table(self, schema: str, table: str) -> Optional[TableMetadata]` — Return full-completeness metadata for *schema.table*.
- `async def generate_query(self, natural_language: str, target_tables: Optional[List[str]]=None, query_type: str='SELECT') -> str` — Prepare a SQL skeleton and schema context for SQL generation.
- `async def execute_query(self, query: str, limit: int=1000, timeout: int=30) -> Union[QueryExecutionResponse, RetryContext]` — Execute a SQL query and return results or a retry context.
- `async def explain_query(self, query: str) -> str` — Run EXPLAIN ANALYZE on the given query and return the execution plan.
- `async def validate_query(self, sql: str) -> Dict[str, Any]` — Validate SQL syntax and referenced objects.
