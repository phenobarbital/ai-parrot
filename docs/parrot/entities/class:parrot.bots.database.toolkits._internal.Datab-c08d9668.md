---
type: Wiki Entity
title: DatabaseAgentToolkit
id: class:parrot.bots.database.toolkits._internal.DatabaseAgentToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Internal helper toolkit for DatabaseAgent.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# DatabaseAgentToolkit

Defined in [`parrot.bots.database.toolkits._internal`](../summaries/mod:parrot.bots.database.toolkits._internal.md).

```python
class DatabaseAgentToolkit(AbstractToolkit)
```

Internal helper toolkit for DatabaseAgent.

Provides 16 stateless utilities for formatting, extracting, and generating
database-related content. All methods are decorated with ``@tool`` so the
LLM can call them directly. Async methods (#7, #10, #16) require ``await``.

Args:
    session_maker: Optional async session factory used by
        ``get_schema_counts_direct``. When ``None``, that method returns
        ``(0, 0)`` immediately.

## Methods

- `def format_explain_plan(self, plan_json: str) -> str` — Format a PostgreSQL EXPLAIN ANALYZE JSON string into readable text.
- `def simplify_column_type(self, raw_type: str) -> str` — Simplify a verbose SQL column type to its base name.
- `def extract_sql_from_response(self, response_text: str) -> str` — Extract a SQL query from an LLM response that may contain markdown.
- `def extract_table_name_from_query(self, query: str) -> Optional[str]` — Extract the primary table name from a natural-language query or SQL.
- `def extract_table_names_from_metadata(self, metadata_context: str) -> List[str]` — Extract table names referenced in a YAML/text metadata context block.
- `def generate_create_table_statement(self, table_yaml: str) -> str` — Generate a CREATE TABLE DDL statement from a YAML table descriptor.
- `async def generate_optimization_tips(self, sql_query: str, query_plan: str) -> List[str]` — Generate query optimization tips from SQL and execution plan text.
- `def generate_basic_optimization_tips(self, sql_query: str, query_plan: str) -> List[str]` — Generate pattern-based optimization tips without an LLM call.
- `def generate_table_specific_tips(self, table_yaml: str) -> List[str]` — Generate query-development tips based on a YAML table descriptor.
- `async def generate_examples(self, schema_context: str, intent: str) -> List[str]` — Generate SQL usage examples from a schema context and query intent.
- `def extract_performance_metrics(self, explain_analyze: str) -> Dict[str, Any]` — Extract key performance metrics from EXPLAIN ANALYZE text or JSON.
- `def format_as_text(self, data: Any, components: int=0) -> str` — Format arbitrary data into a human-readable string based on active components.
- `def format_query_history(self, history: List[Dict[str, Any]]) -> str` — Format a list of previous query attempts into an LLM-readable string.
- `def parse_tips(self, response_text: str) -> List[str]` — Parse structured optimization tips from an LLM response.
- `def is_explanatory_response(self, response_text: str) -> bool` — Detect whether an LLM response is an explanation rather than SQL.
- `async def get_schema_counts_direct(self, schema_name: str) -> Tuple[int, int]` — Return the number of tables and views in a schema via information_schema.
