---
id: F006
query_id: Q005/Q025
type: read
intent: bots/database TableMetadata is the dialect-neutral record; MetadataSource has no 'ddl'; FK list is untyped dicts
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — bots/database TableMetadata is the dialect-neutral record; MetadataSource has no 'ddl'; FK list is untyped dicts

## Summary

models.py: Completeness(IntEnum) L97; MetadataSource = Literal['frontend','information_schema','pg_catalog','unknown'] L108; SchemaMetadata dataclass L112; TableMetadata dataclass L131 with foreign_keys: List[Dict[str,Any]] L140, row_count L142, sample_data L143, completeness (default FULL) L153, source (default 'unknown') L155. No origin/dialect field.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/database/models.py`
  lines: 97
  symbol: `Completeness`
  excerpt: |
    class Completeness(IntEnum):
- path: `packages/ai-parrot/src/parrot/bots/database/models.py`
  lines: 108
  symbol: `MetadataSource`
  excerpt: |
    MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "unknown"]
- path: `packages/ai-parrot/src/parrot/bots/database/models.py`
  lines: 112
  symbol: `SchemaMetadata`
  excerpt: |
    class SchemaMetadata:
- path: `packages/ai-parrot/src/parrot/bots/database/models.py`
  lines: 131-155
  symbol: `TableMetadata`
  excerpt: |
    foreign_keys: List[Dict[str, Any]] … row_count: Optional[int] … sample_data … completeness: Completeness = field(default=Completeness.FULL) … source: MetadataSource = field(default="unknown")
