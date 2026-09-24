---
id: F022
query_id: (recursive from Q005)
type: grep+read
intent: A second TableMetadata/SchemaMetadata + SchemaMetadataCache live in ai-parrot-tools; `dq_get_table_metadata` is another live introspection surface
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 1
---

# F022 — A second TableMetadata/SchemaMetadata + SchemaMetadataCache live in ai-parrot-tools; `dq_get_table_metadata` is another live introspection surface

## Summary

packages/ai-parrot-tools/src/parrot_tools/database/models.py defines SchemaMetadata L12 and TableMetadata L31 (same field names as bots/database's but WITHOUT completeness/source), cache.py SchemaMetadataCache L26, abstract.py AbstractSchemaManagerTool L41 — the legacy `parrot.tools.database` family. Imported by tools/databasequery/__init__.py, tools/databasequery/sources/{documentdb,oracle}.py, flows/dev_loop/test_scope/policy.py and the mcp toolkit template database-query.yaml. tools/databasequery/toolkit.py get_table_metadata(driver, table, credentials) L298 backs the `dq_get_table_metadata` MCP tool and returns a MetadataResult — a live introspection path the brainstorm did not list. Two records named TableMetadata means the plane must name its canonical input explicitly.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/database/models.py`
  lines: 12,31-45
  symbol: `SchemaMetadata / TableMetadata`
  excerpt: |
    class TableMetadata: """Enhanced table metadata for large-scale operations.""" schema, tablename, table_type, full_name, comment, columns, primary_keys, foreign_keys, indexes, row_count, sample_data
- path: `packages/ai-parrot-tools/src/parrot_tools/database/cache.py`
  lines: 26
  symbol: `SchemaMetadataCache`
- path: `packages/ai-parrot-tools/src/parrot_tools/database/abstract.py`
  lines: 41
  symbol: `AbstractSchemaManagerTool`
- path: `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py`
  lines: 127,298-312
  symbol: `DatabaseQueryToolkit.get_table_metadata`
  excerpt: |
    async def get_table_metadata(self, driver: str, table: str, credentials: Optional[dict[str, Any]] = None) -> MetadataResult:
- path: `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py`
  lines: -
  excerpt: |
    imports parrot_tools.database
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py`
  lines: -
  excerpt: |
    references parrot.tools.database
