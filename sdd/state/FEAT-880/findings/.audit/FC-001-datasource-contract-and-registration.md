---
id: FC-001
query_id: Q009, Q010, Q011, Q012
type: read
intent: "DataSource abstract contract, the add_* registration methods, and the SQL / query-slug sources a semantic source would sit beside."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-001 — DataSource contract and how add_query / add_sql_source / add_table_source register

## Summary

A source is a `DataSource` subclass with three mandatory members (`fetch(**params) -> pd.DataFrame`,
`describe()`, `cache_key`) and two optional ones (`prefetch_schema()`, `has_builtin_cache`). Every
`add_*` method on `DatasetManager` follows one shape: lazily import the source class, build it, wrap it
with `self._make_source(...)`, put it in a `DatasetEntry`, and store it in `self._datasets[name]`.
There are 13 `add_*` methods and a generic `add_source(source)` that registers any pre-built
`DataSource`, so a new source kind needs no change to the registration machinery. `SQLQuerySource`
executes through `AsyncDB(driver, dsn=|params=)` with `output_format('pandas')`.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py`
  lines: 23-132
  symbol: `DataSource`
  excerpt: |
    class DataSource(ABC):
        async def prefetch_schema(self) -> Dict[str, str]: return {}
        @abstractmethod
        async def fetch(self, **params) -> pd.DataFrame: ...
        @abstractmethod
        def describe(self) -> str: ...
        @property
        def has_builtin_cache(self) -> bool: return False
        @property
        @abstractmethod
        def cache_key(self) -> str: ...

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 1433-1481
  symbol: `DatasetManager.add_source`
  excerpt: |
    def add_source(self, source, capability_registry=None) -> str:
        if not hasattr(source, "cache_key"):
            raise ValueError(...)
        name = getattr(source, "name", None) or source.cache_key
        entry = DatasetEntry(name=name, description=description,
            source=self._make_source(source), ..., protected=True)
        self._datasets[name] = entry

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 1483-1534
  symbol: `DatasetManager.add_query`
  excerpt: |
    from .sources.query_slug import QuerySlugSource
    resolved_filter = permanent_filter if permanent_filter is not None else query_filter
    source = QuerySlugSource(slug=query_slug, permanent_filter=resolved_filter)
    entry = DatasetEntry(name=name, description=description,
        source=self._make_source(source), ..., protected=True)
    self._datasets[name] = entry

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 1633-1680
  symbol: `DatasetManager.add_sql_source`
  excerpt: |
    def add_sql_source(self, name, sql, driver, *, description=None, dsn=None,
                       metadata=None, cache_ttl=3600, computed_columns=None, usage_guidance=None) -> str:
        from .sources.sql import SQLQuerySource
        source = SQLQuerySource(sql=sql, driver=driver, dsn=dsn)
        entry = DatasetEntry(..., source=self._make_source(source), cache_ttl=cache_ttl, ...)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 1536-1631
  symbol: `DatasetManager.add_table_source`
  excerpt: |
    source = TableSource(table=table, driver=driver, dsn=dsn, credentials=credentials, ...)
    await source.prefetch_schema()  # raises on failure if strict_schema=True
    await source.prefetch_row_count()
    entry = DatasetEntry(..., source=self._make_source(source), cache_ttl=cache_ttl, no_cache=no_cache, ...)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/sql.py`
  lines: 181-231
  symbol: `SQLQuerySource.fetch`
  excerpt: |
    escaped_params = {k: self._escape_value(v) for k, v in params.items() if k in required}
    final_sql = self.sql.format(**escaped_params)
    credentials, dsn = self._get_connection_args()
    db = AsyncDB(self.driver, dsn=dsn) if dsn else AsyncDB(self.driver, params=credentials)
    async with await db.connection() as conn:
        conn.output_format('pandas')
        result, errors = await conn.query(final_sql)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/sql.py`
  lines: 86-94
  symbol: `SQLQuerySource.cache_key`
  excerpt: |
    md5 = hashlib.md5(self.sql.encode(), usedforsecurity=False).hexdigest()[:8]
    return f"sql:{self.driver}:{md5}"

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  lines: 56-130
  symbol: `QuerySlugSource`
  excerpt: |
    def __init__(self, slug, prefetch_schema_enabled=True, permanent_filter=None, *,
                 tenant=None, is_multiquery=False, multi_output=None, principal=None, definition=None)
    @property
    def has_builtin_cache(self) -> bool: return True
    # cache_key: "qs:{slug}[:f={hash}][:t={tenant}]" — "The principal is NEVER part of the key."

## Notes

- All `add_*` methods found (tool.py): `add_dataset` 1038, `add_dataframe` 1174,
  `add_dataframe_from_file` 1252, `add_source` 1433, `add_query` 1483, `add_table_source` 1536,
  `add_sql_source` 1633, `add_airtable_source` 1682, `add_smartsheet_source` 1726,
  `add_iceberg_source` 1770, `add_mongo_source` 1854, `add_deltatable_source` 1934,
  `add_composite_dataset` 2018. No `add_semantic*` exists.
- `SQLQuerySource` interpolates `{param}` placeholders with `str.format` after escaping — it is not a
  bind-parameter path (`sql.py:146-150` warns about this). A compiled semantic SELECT containing literal
  braces would be misread as a placeholder.
- `QuerySlugSource` already carries a per-request `principal` kept out of the cache key — precedent for
  identity-bearing sources.
