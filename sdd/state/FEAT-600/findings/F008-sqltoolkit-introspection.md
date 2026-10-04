---
id: F008
query_id: Q007
type: read
intent: SQLToolkit hooks for live introspection; validate_query says 'not found in cache'; _internal DDL helper takes YAML, not TableMetadata
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — SQLToolkit hooks for live introspection; validate_query says 'not found in cache'; _internal DDL helper takes YAML, not TableMetadata

## Summary

sql.py: _SQLGLOT_DIALECT_MAP L45; _metadata_source='information_schema' L80; search_schema L113; describe_table L183; generate_query L214; validate_query L509 emits "Table '{schema}.{table}' not found in cache." L534; dialect lookup L564; _warm_table_cache L576; _get_information_schema_query L636; _get_columns_query L672; _get_primary_keys_query L691; _get_unique_constraints_query L714; meta.source assigned at L953/L1052. PostgresToolkit L28 sets _metadata_source='pg_catalog' L41 AND overrides _get_information_schema_query L123 (brainstorm implied only BigQuery overrides it); BigQueryToolkit L19 overrides at L60. _internal.py: simplify_column_type L131 and generate_create_table_statement(self, table_yaml) L278 are *methods on a helper class that take YAML text* — not a TableMetadata→DDL renderer, so a sqlglot renderer is new, not a replacement.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
  lines: 45
  symbol: `_SQLGLOT_DIALECT_MAP`
- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
  lines: 80,113,183,214
  symbol: `SQLToolkit._metadata_source / search_schema / describe_table / generate_query`
- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
  lines: 509-534
  symbol: `SQLToolkit.validate_query`
  excerpt: |
    errors.append(f"Table '{schema}.{table_part}' not found in cache.")
- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
  lines: 564,576,636,672,691,714
  symbol: `dialect lookup / _warm_table_cache / _get_information_schema_query / _get_columns_query / _get_primary_keys_query / _get_unique_constraints_query`
- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py`
  lines: 28,41,123
  symbol: `PostgresToolkit`
  excerpt: |
    _metadata_source: str = "pg_catalog" … def _get_information_schema_query(
- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/bigquery.py`
  lines: 19,60
  symbol: `BigQueryToolkit`
  excerpt: |
    def _get_information_schema_query(
- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py`
  lines: 131,278
  symbol: `simplify_column_type / generate_create_table_statement`
  excerpt: |
    def generate_create_table_statement(self, table_yaml: str) -> str:
