---
type: Wiki Entity
title: AbstractSchemaManagerTool
id: class:parrot_tools.database.abstract.AbstractSchemaManagerTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base for database-specific schema management tools.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# AbstractSchemaManagerTool

Defined in [`parrot_tools.database.abstract`](../summaries/mod:parrot_tools.database.abstract.md).

```python
class AbstractSchemaManagerTool(AbstractTool, ABC)
```

Abstract base for database-specific schema management tools.

Handles all schema-related operations:
- Schema analysis and metadata extraction
- Schema search and discovery
- Metadata caching and retrieval

## Methods

- `async def analyze_all_schemas(self) -> Dict[str, int]` — Analyze all allowed schemas and populate metadata cache.
- `async def analyze_schema(self, schema_name: str) -> int` — Analyze individual schema and return table count.
- `async def analyze_table(self, session: AsyncSession, schema_name: str, table_name: str, table_type: str, comment: Optional[str]) -> TableMetadata` — Analyze individual table metadata.
- `async def search_schema(self, search_term: str, search_type: str='all', limit: int=10) -> List[TableMetadata]` — Search database schema - returns raw TableMetadata for agent use.
- `async def get_table_details(self, schema: str, tablename: str) -> Optional[TableMetadata]` — Get detailed metadata for a specific table.
- `async def get_schema_overview(self, schema_name: str) -> Optional[Dict[str, Any]]` — Get overview of a specific schema.
- `def get_allowed_schemas(self) -> List[str]` — Get the list of schemas this tool can search.
