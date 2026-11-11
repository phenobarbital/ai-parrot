---
id: F007
query_id: Q029, Q031
type: read
intent: "Composite source as precedent for a source built from other definitions, and the existing test files for DatasetManager sources."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
lane_id: FC-008
---

# F007 — CompositeDataSource is the precedent for a definition-driven source; source tests are split across three packages

## Summary

`CompositeDataSource` is a `DataSource` defined by Pydantic specs (`JoinSpec`) rather than by a query
string, holds a back-reference to its `DatasetManager` under `TYPE_CHECKING`, and sets
`has_builtin_cache = True` so the manager skips its Redis layer. It is registered through a dedicated
`add_composite_dataset` method (tool.py:2018). That is the closest structural precedent for a source
defined by a `SemanticQuery`. Tests for sources are spread over `packages/ai-parrot/tests/tools/`,
`packages/ai-parrot/tests/auth/` and `packages/ai-parrot-tools/tests/dataset_manager/`; a semantic source
has no test today.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/composite.py`
  lines: 1-30
  symbol: `CompositeDataSource`
  excerpt: |
    CompositeDataSource — virtual dataset that JOINs two or more existing datasets.
    - ``has_builtin_cache = True``: DatasetManager skips its Redis layer for the
      composite result.  Components are cached individually by their own sources.
    - Circular import avoided via ``TYPE_CHECKING`` for DatasetManager reference.
    if TYPE_CHECKING:  # pragma: no cover
        from ..tool import DatasetManager

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/composite.py`
  lines: 38-57
  symbol: `JoinSpec`
  excerpt: |
    class JoinSpec(BaseModel):
        left: str = Field(description="Left dataset name")
        right: str = Field(description="Right dataset name")
        on: Union[str, List[str]] = Field(description="Join column(s)")
        how: Literal["inner", "left", "right", "outer"] = Field(default="inner", ...)

- path: `packages/ai-parrot/tests/auth/test_authorizing_data_source.py`
  lines: 1-1
  symbol: `test_authorizing_data_source`
  excerpt: |
    (file located by glob; not read)

- path: `packages/ai-parrot/tests/auth/test_physical_resource_resolver.py`
  lines: 1-1
  symbol: `test_physical_resource_resolver`
  excerpt: |
    (file located by glob; not read)

- path: `packages/ai-parrot-tools/tests/dataset_manager/test_composite_source.py`
  lines: 1-1
  symbol: `test_composite_source`
  excerpt: |
    (file located by glob; not read)

- path: `packages/ai-parrot/tests/tools/test_dataset_new_sources_integration.py`
  lines: 1-1
  symbol: `test_dataset_new_sources_integration`
  excerpt: |
    (file located by glob; not read)

## Notes

- Glob `packages/*/tests/**/test_*source*.py` returned 23 files; the DatasetManager-source ones are:
  `packages/ai-parrot/tests/auth/{test_authorizing_data_source,test_opaque_source_resolvers,test_physical_resource_resolver}.py`,
  `packages/ai-parrot/tests/tools/{test_dataset_new_sources_integration,test_deltatable_source,test_iceberg_source,test_mongo_source,test_tablesource_allowed_columns,test_tablesource_dialect_hint}.py`,
  `packages/ai-parrot-tools/tests/dataset_manager/test_composite_source.py`,
  `packages/ai-parrot-tools/tests/test_datasources.py`.
- `packages/ai-parrot/tests/test_semantic_duckdb_source.py` is about `parrot.tools.databasequery.sources.duckdb.DuckDBSource`
  (the semantic executor's DuckDB backend), not a DatasetManager source.
- Where tests for a new semantic source would live depends on where the class lives (FC-007): in
  `packages/ai-parrot-semantic/tests/` if the source ships from the semantic distribution.
- `composite.py` was read for lines 1-60 only.
