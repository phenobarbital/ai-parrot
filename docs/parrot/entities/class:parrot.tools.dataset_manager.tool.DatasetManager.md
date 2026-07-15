---
type: Wiki Entity
title: DatasetManager
id: class:parrot.tools.dataset_manager.tool.DatasetManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Dataset Catalog and toolkit for managing DataFrames and Queries.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# DatasetManager

Defined in [`parrot.tools.dataset_manager.tool`](../summaries/mod:parrot.tools.dataset_manager.tool.md).

```python
class DatasetManager(AbstractToolkit)
```

Dataset Catalog and toolkit for managing DataFrames and Queries.

As a Toolkit:
- Exposes tools to the LLM: list_available(), get_metadata(), get_active(), etc.

As a Catalog:
- Stores datasets (DataFrames or query slugs)
- Manages active/inactive state (defaults to active)
- Provides dataframes to PythonPandasTool on demand
- Replaces MetadataTool with get_metadata() functionality

As a Metadata Engine:
- Column type categorization (integer, float, datetime, categorical_text, text, etc.)
- Per-column metrics guide generation
- Comprehensive DataFrame info (shape, dtypes, memory, nulls, column types)
- Data quality checks (NaN detection, completeness, duplicates)

## Methods

- `def set_on_change(self, callback: Callable[[], None]) -> None` — Register a callback invoked after dataset mutations (fetch, activate, deactivate).
- `def set_repl_locals_getter(self, getter: Callable[[], Dict[str, Any]]) -> None` — Register a callable that returns the REPL local variables.
- `def drain_artifacts(self) -> List[Dict[str, Any]]` — Return accumulated artifacts and clear the internal list.
- `async def setup(self) -> None` — Async init placeholder — can be extended for deferred prefetch.
- `def categorize_columns(df: pd.DataFrame) -> Dict[str, str]` — Categorize DataFrame columns into semantic data types.
- `def get_dataframe_info(self, df: pd.DataFrame) -> Dict[str, Any]` — Get comprehensive information about a DataFrame.
- `def generate_metrics_guide(self, df: pd.DataFrame, columns: Optional[List[str]]=None) -> str` — Generate per-column information guide with type, range, unique values, and nulls.
- `def check_dataframes_for_nans(self, names: Optional[List[str]]=None) -> List[str]` — Check DataFrames for NaN/Null values.
- `async def add_dataset(self, name: str, *, description: Optional[str]=None, query_slug: Optional[str]=None, query: Optional[str]=None, table: Optional[str]=None, dataframe: Optional[pd.DataFrame]=None, driver: Optional[str]=None, dsn: Optional[str]=None, credentials: Optional[Dict[str, Any]]=None, conditions: Optional[Dict[str, Any]]=None, sql: Optional[str]=None, filter: Optional[Dict[str, Any]]=None, metadata: Optional[Dict[str, Any]]=None, is_active: bool=True, permanent_filter: Optional[Dict[str, Any]]=None, computed_columns: Optional[List[Any]]=None, usage_guidance: Optional[Dict[str, List[str]]]=None) -> str` — Fetch data from any source and register the result as an in-memory DataFrame.
- `def add_dataframe(self, name: str, df: pd.DataFrame, description: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None, is_active: bool=True, computed_columns: Optional[List[Any]]=None, usage_guidance: Optional[Dict[str, List[str]]]=None) -> str` — Add a DataFrame to the catalog.
- `def add_dataframe_from_file(self, name: str, path: Union[str, PathLike[str]], metadata: Optional[Dict[str, Any]]=None, is_active: bool=True, **kwargs: Any) -> str` — Create and add a DataFrame from a CSV or Excel file.
- `async def load_file(self, name: str, path: Union[str, Path], metadata: Optional[Dict[str, Any]]=None, max_rows_per_table: int=200, output_format: str='markdown') -> str` — Load a CSV or Excel file for LLM context.
- `async def get_file_context(self, name: str) -> str` — Get the full markdown context for a loaded file.
- `async def get_file_table(self, name: str, table_id: str) -> str` — Get markdown for a specific table from a loaded file.
- `def add_source(self, source, capability_registry=None) -> str` — Register a pre-built DataSource instance with optional CapabilityRegistry hook.
- `def add_query(self, name: str, query_slug: str, description: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None, is_active: bool=True, permanent_filter: Optional[Dict[str, Any]]=None, query_filter: Optional[Dict[str, Any]]=None, computed_columns: Optional[List[Any]]=None, usage_guidance: Optional[Dict[str, List[str]]]=None) -> str` — Register a query slug for lazy loading.
- `async def add_table_source(self, name: str, table: str, driver: str, *, description: Optional[str]=None, dsn: Optional[str]=None, credentials: Optional[Dict[str, Any]]=None, metadata: Optional[Dict[str, Any]]=None, cache_ttl: int=3600, strict_schema: bool=True, permanent_filter: Optional[Dict[str, Any]]=None, query_filter: Optional[Dict[str, Any]]=None, allowed_columns: Optional[List[str]]=None, no_cache: bool=False, computed_columns: Optional[List[Any]]=None, usage_guidance: Optional[Dict[str, List[str]]]=None) -> str` — Register a database table with schema prefetch.
- `def add_sql_source(self, name: str, sql: str, driver: str, *, description: Optional[str]=None, dsn: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None, cache_ttl: int=3600, computed_columns: Optional[List[Any]]=None, usage_guidance: Optional[Dict[str, List[str]]]=None) -> str` — Register a parameterized SQL source. Sync — no prefetch needed.
- `async def add_airtable_source(self, name: str, base_id: str, table: str, api_key: Optional[str]=None, view: Optional[str]=None, description: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None, cache_ttl: int=3600, fetch_on_create: bool=True, computed_columns: Optional[List[Any]]=None) -> str` — Register an Airtable table source and optionally fetch immediately.
- `async def add_smartsheet_source(self, name: str, sheet_id: str, access_token: Optional[str]=None, description: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None, cache_ttl: int=3600, fetch_on_create: bool=True, computed_columns: Optional[List[Any]]=None) -> str` — Register a Smartsheet source and optionally fetch immediately.
- `async def add_iceberg_source(self, name: str, table_id: str, catalog_params: Dict[str, Any], *, description: Optional[str]=None, factory: str='pandas', credentials: Optional[Dict[str, Any]]=None, dsn: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None, cache_ttl: int=3600, no_cache: bool=False, is_active: bool=True, computed_columns: Optional[List[Any]]=None) -> str` — Register an Apache Iceberg table with schema and row-count prefetch.
- `async def add_mongo_source(self, name: str, collection: str, database: str, *, description: Optional[str]=None, credentials: Optional[Dict[str, Any]]=None, dsn: Optional[str]=None, required_filter: bool=True, metadata: Optional[Dict[str, Any]]=None, cache_ttl: int=3600, no_cache: bool=False, is_active: bool=True, computed_columns: Optional[List[Any]]=None) -> str` — Register a MongoDB/DocumentDB collection with schema prefetch.
- `async def add_deltatable_source(self, name: str, path: str, *, description: Optional[str]=None, table_name: Optional[str]=None, mode: str='error', credentials: Optional[Dict[str, Any]]=None, metadata: Optional[Dict[str, Any]]=None, cache_ttl: int=3600, no_cache: bool=False, is_active: bool=True, computed_columns: Optional[List[Any]]=None) -> str` — Register a Delta Lake table with schema and row-count prefetch.
- `def add_composite_dataset(self, name: str, joins: List[Dict[str, Any]], *, description: str='', computed_columns: Optional[List[Any]]=None, is_active: bool=True, metadata: Optional[Dict[str, Any]]=None) -> str` — Register a virtual composite dataset that JOINs existing datasets.
- `async def create_iceberg_from_dataframe(self, name: str, df: 'pd.DataFrame', table_id: str, *, namespace: str='default', catalog_params: Optional[Dict[str, Any]]=None, description: Optional[str]=None, mode: str='overwrite') -> str` — Write a DataFrame to a new Iceberg table and register it as a dataset.
- `async def create_deltatable_from_parquet(self, name: str, parquet_path: str, delta_path: str, *, table_name: Optional[str]=None, mode: str='overwrite', description: Optional[str]=None) -> str` — Create a Delta table from a Parquet file and register it as a dataset.
- `def remove(self, name: str) -> str` — Remove a dataset from the catalog.
- `def set_query_loader(self, loader: Any) -> None` — Set the query loader callable (from PandasAgent).
- `def activate(self, names: Union[str, List[str]]) -> List[str]` — Mark datasets as active for use in the session.
- `def deactivate(self, names: Union[str, List[str]]) -> List[str]` — Mark datasets as inactive (exclude from session).
- `def get_active_dataframes(self) -> Dict[str, pd.DataFrame]` — Get all active DataFrames (loaded only).
- `async def get_active_dataframes_lazy(self) -> Dict[str, pd.DataFrame]` — Get active dataframes, loading from queries if needed.
- `def get_dataset_entry(self, name: str) -> Optional[DatasetEntry]` — Get a dataset entry by name or alias.
- `def list_dataframes(self) -> Dict[str, Dict[str, Any]]` — List all loaded DataFrames with detailed info.
- `def get_dataframe_summary(self, name: str) -> Dict[str, Any]` — Get detailed summary for a specific DataFrame.
- `async def add_computed_column(self, dataset_name: str, column_name: str, func: str, columns: List[str], description: str='', **kwargs: Any) -> str` — Add a computed column to an existing dataset at runtime.
- `async def list_available_functions(self) -> List[str]` — List all available computed-column functions.
- `async def get_tools_filtered(self, permission_context: 'PermissionContext', resolver: 'AbstractPermissionResolver') -> List` — Filter toolkit tools by resolver and then by dataset policy.
- `async def list_datasets(self) -> List[Dict[str, Any]]` — List all datasets in the catalog with their status.
- `async def list_available(self) -> List[Dict[str, Any]]` — Alias for list_datasets (backward compatibility).
- `async def get_active(self) -> List[str]` — Get the names of all currently active datasets.
- `async def get_datasets_summary(self) -> str` — Generate a bullet-list summary of all active datasets with descriptions.
- `async def get_metadata(self, name: str, include_eda: bool=False, include_samples: bool=True, include_column_stats: bool=False, include_metrics_guide: bool=False, column: Optional[str]=None) -> Dict[str, Any]` — Get comprehensive metadata about a dataset.
- `async def activate_datasets(self, names: List[str]) -> str` — Activate datasets for use in analysis.
- `async def deactivate_datasets(self, names: List[str]) -> str` — Deactivate datasets to exclude them from the current session.
- `async def remove_dataset(self, name: str) -> str` — Remove a dataset from the catalog entirely.
- `async def get_dataframe(self, name: str) -> Dict[str, Any]` — Get a DataFrame by name or alias.
- `async def store_dataframe(self, name: str, description: str='') -> str` — Store a computed DataFrame from python_repl_pandas into the catalog.
- `async def fetch_dataset(self, name: str, sql: Optional[str]=None, conditions: Optional[Dict[str, Any]]=None, force_refresh: bool=False) -> Dict[str, Any]` — Materialize a dataset by fetching data from its source.
- `async def evict_dataset(self, name: str) -> str` — Release a materialized dataset from memory.
- `async def get_source_schema(self, name: str) -> str` — Return the schema (column → type) for a registered source.
- `async def check_data_quality(self, names: Optional[List[str]]=None) -> Dict[str, Any]` — Run data quality checks on datasets.
- `def get_guide(self) -> str` — Return the current DataFrame guide.
- `def get_usage_rules(self) -> str` — Return the decision rules an agent should inject into its system prompt.
- `async def materialize(self, name: str, force_refresh: bool=False, **params) -> pd.DataFrame` — On-demand materialization with Redis Parquet caching.
- `def evict(self, name: str) -> str` — Release a materialized DataFrame from memory.
- `def evict_all(self) -> str` — Release all materialized DataFrames from memory.
- `def evict_table_sources(self) -> int` — Evict all loaded TableSource DataFrames from memory.
- `def evict_unactive(self) -> str` — Release inactive (is_active=False) materialized DataFrames from memory.
- `async def load_data(self, query: Union[List[str], Dict, str], agent_name: str, refresh: bool=False, cache_expiration: int=48, no_cache: bool=False, **kwargs) -> Dict[str, pd.DataFrame]` — Deprecated: bulk query-loading helper kept for PandasAgent backward compat.
- `def define_filters(self, definitions: List[FilterDefinition]) -> None` — Validate and store common-field filter definitions on this instance.
- `async def get_filter_values(self, name: str, *, cardinality_cap: int=1000) -> List[Any]` — Return distinct values for a named filter.
- `def clear_filter_values_cache(self, name: Optional[str]=None) -> None` — Invalidate the filter-values cache.
- `def get_filter_schema(self) -> List[Dict[str, Any]]` — Serialize the filter catalog for the frontend.
- `def suggest_filters(self, min_datasets: int=1) -> List[FilterDefinition]` — Propose FilterDefinitions from column introspection (opt-in, no side effects).
- `async def list_filters(self) -> List[Dict[str, Any]]` — List all defined common-field filters and their applicable datasets.
- `async def set_filters(self, filter_definitions: List[Dict[str, Any]]) -> str` — Define (or replace) common-field filters on this DatasetManager.
- `async def apply_filters(self, request: Dict[str, Any], *, persist: bool=False) -> 'FilterResult'` — Apply a filter request recursively across all matching datasets.
- `def get_manifest(self) -> List[Dict[str, Any]]` — Return a manifest of all datasets that have a spatial profile.
- `async def spatial_filter(self, spec: 'SpatialFilterSpec', cap_per_dataset: int=1000) -> 'SpatialResult'` — Execute a spatial radius filter across one or more datasets.
