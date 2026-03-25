"""
DatasetManager: A Toolkit and Data Catalog for PandasAgent.

Provides:
- Dataset catalog with add/remove/activate/deactivate
- Full metadata/EDA capabilities (replaces MetadataTool)
- Column type categorization and metrics guide generation
- Data quality checks (NaN detection, completeness)
- LLM-exposed tools for discovery, metadata retrieval, and management
"""
from __future__ import annotations
import io
import re
import warnings
from typing import Callable, Dict, List, Literal, Optional, Any, Tuple, Union, TYPE_CHECKING
from parrot._imports import lazy_import
import redis.asyncio as aioredis
from os import PathLike
from pydantic import BaseModel, Field
import numpy as np
import pandas as pd
from navconfig.logging import logging
from ..toolkit import AbstractToolkit
from ...conf import REDIS_DATASET_URL
from .sources.base import DataSource


try:
    logger = logging.getLogger(__name__)
except Exception:
    logger = logging


class DatasetInfo(BaseModel):
    """Schema for dataset information exposed to LLM.

    Schema fields (columns, column_types) are available even when the dataset
    is not yet loaded — for TableSource entries whose schema was prefetched.
    """

    name: str = Field(description="Dataset name/identifier")
    alias: Optional[str] = Field(default=None, description="Standardized alias (df1, df2, etc.)")
    description: str = Field(default="", description="Dataset description")
    source_type: Literal[
        "dataframe", "query_slug", "sql", "table", "airtable", "smartsheet",
        "iceberg", "mongo", "deltatable", "composite",
    ] = Field(
        default="dataframe",
        description="Type of data source backing this dataset"
    )
    source_description: str = Field(
        default="",
        description="Human-readable description from the DataSource (from source.describe())"
    )

    # Schema — available even when loaded=False (e.g. TableSource after prefetch)
    columns: List[str] = Field(default_factory=list, description="List of column names")
    column_types: Optional[Dict[str, str]] = Field(
        default=None,
        description="Detected column type (integer, float, datetime, categorical_text, text, etc.)"
    )

    # Shape/memory only meaningful when loaded=True
    shape: Optional[Tuple[int, int]] = Field(default=None, description="(rows, columns)")
    loaded: bool = Field(default=False, description="Whether data is loaded in memory")
    memory_usage_mb: float = Field(default=0.0, description="Memory usage in MB")
    null_count: int = Field(default=0, description="Total number of null values across all columns")

    # Row count estimate (TableSource only — prefetched on registration)
    row_count_estimate: Optional[int] = Field(
        default=None,
        description=(
            "Estimated row count from the database (TableSource only). "
            "Large tables (>10k rows) should use GROUP BY / aggregations "
            "instead of SELECT *."
        ),
    )
    table_size_warning: str = Field(
        default="",
        description="Size warning for the LLM when the table is large",
    )

    is_active: bool = Field(default=True, description="Whether dataset is currently active")
    cache_ttl: int = Field(default=3600, description="Per-entry TTL in seconds for Redis cache")
    cache_key: str = Field(default="", description="Stable Redis cache key (from source.cache_key)")


class DatasetEntry:
    """Lifecycle wrapper around a DataSource.

    Knows WHETHER data is in memory and manages its lifecycle:
    - materialize(**params): fetch from source, cache result in _df
    - evict(): release _df from memory (source reference and schema are retained)

    Provides backward-compatible properties (df, query_slug, _column_metadata)
    so existing DatasetManager methods continue to work without changes.

    Computed columns (``computed_columns``) are applied post-materialization
    and before type categorization, so they appear as regular columns
    throughout the DatasetManager API.
    """

    def __init__(
        self,
        name: str,
        description: Optional[str] = None,
        source: Optional[DataSource] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        auto_detect_types: bool = True,
        cache_ttl: int = 3600,
        no_cache: bool = False,
        # Backward-compat kwargs — wrap in appropriate source if no source given
        df: Optional[pd.DataFrame] = None,
        query_slug: Optional[str] = None,
        # Computed columns
        computed_columns: Optional[List[Any]] = None,
    ) -> None:
        self.name = name
        self.metadata = metadata or {}
        # Priority: explicit description > metadata["description"] > ""
        raw_desc = description or self.metadata.get("description", "")
        self.description: str = raw_desc[:300] if raw_desc else ""
        self.is_active = is_active
        self.auto_detect_types = auto_detect_types
        self.cache_ttl = cache_ttl
        self.no_cache = no_cache

        # Resolve source: prefer explicit source, then legacy df/query_slug kwargs
        if source is not None:
            self.source = source
        elif df is not None:
            from .sources.memory import InMemorySource
            self.source = InMemorySource(df=df, name=name)
        elif query_slug is not None:
            from .sources.query_slug import QuerySlugSource
            self.source = QuerySlugSource(slug=query_slug)
        else:
            raise ValueError("DatasetEntry requires 'source', 'df', or 'query_slug'")

        # Computed columns — stored as a list; type annotation uses Any to avoid
        # circular import at class-definition time.
        self._computed_columns: List[Any] = list(computed_columns) if computed_columns else []

        # Internal state
        self._df: Optional[pd.DataFrame] = df  # pre-load when df provided directly
        self._column_types: Optional[Dict[str, str]] = None
        if df is not None:
            # Apply computed columns before type detection
            if self._computed_columns:
                self._apply_computed_columns()
            if auto_detect_types:
                self._column_types = DatasetManager.categorize_columns(self._df)

    # ─────────────────────────────────────────────────────────────
    # Computed columns
    # ─────────────────────────────────────────────────────────────

    def _apply_computed_columns(self) -> None:
        """Apply all registered computed columns to ``self._df`` in list order.

        Each column definition is looked up in the ``COMPUTED_FUNCTIONS``
        registry.  If a function is not found or raises an exception, the
        column is skipped and a warning is logged — other columns continue
        to be applied (resilience by design).

        Ordering matters: if column B depends on computed column A, A must
        appear first in ``self._computed_columns``.
        """
        if self._df is None or not self._computed_columns:
            return

        from .computed import get_computed_function

        for col_def in self._computed_columns:
            fn = get_computed_function(col_def.func)
            if fn is None:
                logger.warning(
                    "DatasetEntry '%s': unknown computed function '%s' for column '%s' — skipping",
                    self.name,
                    col_def.func,
                    col_def.name,
                )
                continue
            try:
                self._df = fn(
                    self._df,
                    col_def.name,
                    col_def.columns,
                    **col_def.kwargs,
                )
            except Exception as exc:
                logger.error(
                    "DatasetEntry '%s': error applying computed column '%s' (func='%s'): %s",
                    self.name,
                    col_def.name,
                    col_def.func,
                    exc,
                )

    # ─────────────────────────────────────────────────────────────
    # Source-based lifecycle
    # ─────────────────────────────────────────────────────────────

    async def materialize(self, force: bool = False, **params) -> pd.DataFrame:
        """Fetch data from source if not already loaded (or if force=True).

        Computed columns are applied post-fetch and before type categorization
        so they appear as regular columns in all metadata surfaces.

        Args:
            force: If True, re-fetch even if _df is already populated.
            **params: Passed through to source.fetch() (e.g. sql=, conditions=).

        Returns:
            The loaded DataFrame.
        """
        if self._df is None or force:
            self._df = await self.source.fetch(**params)
            if self._df is not None and self._computed_columns:
                self._apply_computed_columns()
            if self.auto_detect_types and self._df is not None:
                self._column_types = DatasetManager.categorize_columns(self._df)
        return self._df

    def evict(self) -> None:
        """Release DataFrame from memory.

        Source reference and schema (_schema on source, _column_types) are cleared.
        The source itself is retained so the dataset can be re-materialized later.
        """
        self._df = None
        self._column_types = None

    # ─────────────────────────────────────────────────────────────
    # Properties — new interface
    # ─────────────────────────────────────────────────────────────

    @property
    def loaded(self) -> bool:
        """True if data has been materialized into memory."""
        return self._df is not None

    @property
    def shape(self) -> Tuple[int, int]:
        """Shape of the loaded DataFrame, or (0, 0) if not loaded."""
        return self._df.shape if self._df is not None else (0, 0)

    @property
    def columns(self) -> List[str]:
        """Column names. Falls back to source schema (TableSource) when not loaded.

        In prefetch state (not yet loaded), computed column names are appended
        after the schema columns so the LLM can see them before materialization.
        """
        if self._df is not None:
            return self._df.columns.tolist()
        # Schema from prefetch (available for TableSource before materialization)
        schema = getattr(self.source, '_schema', {})
        base_cols = list(schema.keys())
        # Append computed column names that are not already in the schema
        computed_names = [c.name for c in self._computed_columns if c.name not in base_cols]
        return base_cols + computed_names

    @property
    def memory_usage_mb(self) -> float:
        """Memory usage of the loaded DataFrame in MB."""
        if self._df is not None:
            return self._df.memory_usage(deep=True).sum() / 1024 / 1024
        return 0.0

    @property
    def null_count(self) -> int:
        """Total null count across all columns."""
        return int(self._df.isnull().sum().sum()) if self._df is not None else 0

    @property
    def column_types(self) -> Optional[Dict[str, str]]:
        """Semantic column types (populated after materialization)."""
        return self._column_types

    # ─────────────────────────────────────────────────────────────
    # Backward-compatibility properties (for existing DatasetManager code)
    # ─────────────────────────────────────────────────────────────

    @property
    def df(self) -> Optional[pd.DataFrame]:
        """Backward-compat: return the loaded DataFrame (same as _df)."""
        return self._df

    @df.setter
    def df(self, value: Optional[pd.DataFrame]) -> None:
        """Backward-compat setter used by _load_query and legacy code paths."""
        self._df = value
        if value is not None and self.auto_detect_types:
            self._column_types = DatasetManager.categorize_columns(value)

    @property
    def query_slug(self) -> Optional[str]:
        """Backward-compat: return slug if source is a QuerySlugSource."""
        from .sources.query_slug import QuerySlugSource
        if isinstance(self.source, QuerySlugSource):
            return self.source.slug
        return None

    @property
    def _column_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Backward-compat: generate column metadata dict for get_metadata().

        When loaded, derives metadata from the DataFrame and user metadata.
        Computed column descriptions (from ``ComputedColumnDef.description``)
        are injected for computed columns.
        When not loaded, derives from source schema (TableSource prefetch).
        """
        # Build a mapping from computed column name → description for fast lookup
        computed_desc: Dict[str, str] = {
            c.name: c.description
            for c in self._computed_columns
            if c.description
        }

        if self._df is not None:
            # Extract user-provided column hints from metadata dict
            column_meta: Dict[str, Any] = {}
            if isinstance(self.metadata.get('columns'), dict):
                column_meta = self.metadata['columns']
            else:
                # Column keys may be top-level in metadata
                column_meta = {
                    k: v for k, v in self.metadata.items()
                    if k in self._df.columns
                }

            result: Dict[str, Dict[str, Any]] = {}
            for col in self._df.columns:
                user_meta = column_meta.get(col)
                if isinstance(user_meta, str):
                    col_info: Dict[str, Any] = {'description': user_meta}
                elif isinstance(user_meta, dict):
                    col_info = user_meta.copy()
                else:
                    col_info = {}
                # Inject computed description (overrides default title-case fallback)
                if col in computed_desc:
                    col_info.setdefault('description', computed_desc[col])
                col_info.setdefault('description', col.replace('_', ' ').title())
                col_info.setdefault('dtype', str(self._df[col].dtype))
                result[col] = col_info
            return result

        # Not loaded — derive from source schema (TableSource prefetch)
        schema = getattr(self.source, '_schema', {})
        return {
            col: {'description': col.replace('_', ' ').title(), 'dtype': dtype}
            for col, dtype in schema.items()
        }

    # ─────────────────────────────────────────────────────────────
    # DatasetInfo serialization
    # ─────────────────────────────────────────────────────────────

    def to_info(self, alias: Optional[str] = None) -> DatasetInfo:
        """Serialize this entry to a DatasetInfo Pydantic model.

        Schema (columns + column_types) is populated even when loaded=False,
        provided the source has prefetched schema (e.g. TableSource).

        Args:
            alias: Standardized alias string (e.g. 'df1', 'df2').

        Returns:
            DatasetInfo instance ready for LLM consumption.
        """
        from .sources.memory import InMemorySource
        from .sources.query_slug import QuerySlugSource, MultiQuerySlugSource
        from .sources.sql import SQLQuerySource
        from .sources.table import TableSource
        from .sources.airtable import AirtableSource
        from .sources.smartsheet import SmartsheetSource
        from .sources.iceberg import IcebergSource
        from .sources.mongo import MongoSource
        from .sources.deltatable import DeltaTableSource
        from .sources.composite import CompositeDataSource

        _source_type_map: Dict[type, str] = {
            InMemorySource: "dataframe",
            QuerySlugSource: "query_slug",
            MultiQuerySlugSource: "query_slug",
            SQLQuerySource: "sql",
            TableSource: "table",
            AirtableSource: "airtable",
            SmartsheetSource: "smartsheet",
            IcebergSource: "iceberg",
            MongoSource: "mongo",
            DeltaTableSource: "deltatable",
            CompositeDataSource: "composite",
        }
        source_type = _source_type_map.get(type(self.source), "dataframe")

        # column_types: use post-fetch types if loaded, else source _schema for TableSource
        col_types = self._column_types
        if col_types is None:
            raw_schema = getattr(self.source, '_schema', {})
            col_types = raw_schema if raw_schema else None

        # Row count estimate and size warning (TableSource, IcebergSource, DeltaTableSource)
        row_count = getattr(self.source, '_row_count_estimate', None)
        size_warning = ""
        if isinstance(self.source, TableSource) and row_count is not None:
            size_warning = TableSource._size_warning(row_count)
        elif isinstance(self.source, (IcebergSource, DeltaTableSource)) and row_count is not None:
            if row_count > 100_000:
                size_warning = (
                    f"Large dataset (~{row_count:,} rows). "
                    "Use SQL queries with filters/aggregations — avoid SELECT *."
                )

        return DatasetInfo(
            name=self.name,
            alias=alias,
            description=self.description,
            source_type=source_type,
            source_description=self.source.describe(),
            columns=self.columns,
            column_types=col_types,
            shape=self.shape if self.loaded else None,
            loaded=self.loaded,
            memory_usage_mb=round(self.memory_usage_mb, 2),
            null_count=self.null_count,
            row_count_estimate=row_count,
            table_size_warning=size_warning,
            is_active=self.is_active,
            cache_ttl=self.cache_ttl,
            cache_key=self.source.cache_key,
        )


class DatasetManager(AbstractToolkit):
    """
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
    """

    exclude_tools = ("setup", "add_dataset", "list_available")

    def __init__(
        self,
        df_prefix: str = "df",
        generate_guide: bool = True,
        include_summary_stats: bool = False,
        auto_detect_types: bool = True,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._datasets: Dict[str, DatasetEntry] = {}
        self._query_loader: Optional[Any] = None
        self._on_change_callback: Optional[Callable[[], None]] = None
        self._repl_locals_getter: Optional[Callable[[], Dict[str, Any]]] = None
        self.df_prefix = df_prefix
        self.generate_guide = generate_guide
        self.include_summary_stats = include_summary_stats
        self.auto_detect_types = auto_detect_types
        self.df_guide: str = ""
        self.logger = logger
        self._redis: Optional[aioredis.Redis] = None

    def set_on_change(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked after dataset mutations (fetch, activate, deactivate)."""
        self._on_change_callback = callback

    def set_repl_locals_getter(self, getter: Callable[[], Dict[str, Any]]) -> None:
        """Register a callable that returns the REPL local variables.

        Used by ``store_dataframe`` to look up a computed DataFrame by name
        from the python_repl_pandas execution environment.
        """
        self._repl_locals_getter = getter

    def _notify_change(self) -> None:
        """Invoke the on-change callback if registered."""
        if self._on_change_callback is not None:
            try:
                self._on_change_callback()
            except Exception as exc:
                self.logger.error(
                    "on_change callback failed (DataFrames may not sync to REPL): %s",
                    exc, exc_info=True,
                )

    async def setup(self) -> None:
        """Async init placeholder — can be extended for deferred prefetch."""

    # ─────────────────────────────────────────────────────────────
    # Alias Mapping
    # ─────────────────────────────────────────────────────────────
    def _get_alias_map(self) -> Dict[str, str]:
        """Return mapping of dataset names to standardized aliases."""
        return {
            name: f"{self.df_prefix}{i + 1}"
            for i, name in enumerate(self._datasets.keys())
        }

    def _resolve_name(self, identifier: str) -> str:
        """Resolve alias or name to actual dataset name."""
        if identifier in self._datasets:
            return identifier

        # Check if it's an alias
        alias_map = self._get_alias_map()
        for name, alias in alias_map.items():
            if alias == identifier:
                return name
        # Case-insensitive match
        identifier_lower = identifier.lower()
        return next(
            (
                name
                for name, _ in self._datasets.items()
                if name.lower() == identifier_lower
            ),
            identifier,
        )

    # ─────────────────────────────────────────────────────────────
    # Column Type Categorization (moved from PythonPandasTool)
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def categorize_columns(df: pd.DataFrame) -> Dict[str, str]:
        """
        Categorize DataFrame columns into semantic data types.

        Uses heuristics to distinguish between:
        - integer, float (numeric)
        - datetime
        - categorical, boolean
        - categorical_text (low-cardinality text)
        - text (high-cardinality text)

        Args:
            df: DataFrame to categorize

        Returns:
            Dictionary mapping column names to type categories
        """
        column_types = {}

        for col in df.columns:
            # Check boolean first (nullable boolean is also considered numeric)
            if pd.api.types.is_bool_dtype(df[col]):
                column_types[col] = "boolean"
            elif pd.api.types.is_numeric_dtype(df[col]):
                if pd.api.types.is_integer_dtype(df[col]):
                    column_types[col] = "integer"
                else:
                    column_types[col] = "float"
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                column_types[col] = "datetime"
            elif isinstance(df[col].dtype, pd.CategoricalDtype):
                column_types[col] = "categorical"
            else:
                # Check if it looks like categorical data
                # May fail for columns with unhashable types (arrays, lists)
                try:
                    unique_ratio = df[col].nunique() / len(df) if len(df) > 0 else 0
                    if unique_ratio < 0.1 and df[col].nunique() < 50:
                        column_types[col] = "categorical_text"
                    else:
                        column_types[col] = "text"
                except TypeError:
                    # Column contains unhashable types - treat as text
                    column_types[col] = "text"

        return column_types

    # ─────────────────────────────────────────────────────────────
    # DataFrame Info (moved from PythonPandasTool)
    # ─────────────────────────────────────────────────────────────

    def get_dataframe_info(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Get comprehensive information about a DataFrame.

        Args:
            df: DataFrame to inspect

        Returns:
            Dictionary with shape, columns, dtypes, memory usage,
            null counts, row/column counts, and optional column types.
        """
        info = {
            'shape': df.shape,
            'columns': df.columns.tolist(),
            'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()},
            'memory_usage_bytes': df.memory_usage(deep=True).sum(),
            'null_counts': df.isnull().sum().to_dict(),
            'row_count': len(df),
            'column_count': len(df.columns),
        }

        if self.auto_detect_types:
            info['column_types'] = self.categorize_columns(df)

        return info

    # ─────────────────────────────────────────────────────────────
    # Metrics Guide (moved from PythonPandasTool)
    # ─────────────────────────────────────────────────────────────
    def generate_metrics_guide(self, df: pd.DataFrame, columns: Optional[List[str]] = None) -> str:
        """
        Generate per-column information guide with type, range, unique values, and nulls.

        Args:
            df: DataFrame to generate metrics for
            columns: Specific columns to include (defaults to all)

        Returns:
            Formatted string with per-column metrics
        """
        if columns is None:
            columns = df.columns.tolist()

        column_types = self.categorize_columns(df) if self.auto_detect_types else {}
        column_info = []

        for col in columns:
            dtype = str(df[col].dtype)
            category = column_types.get(col, dtype)
            null_count = df[col].isnull().sum()

            # Try to get unique count - may fail for unhashable types (arrays, lists)
            try:
                unique_count = df[col].nunique()
            except TypeError:
                unique_count = None

            # Additional info based on data type
            extra_info = []
            if category in ('integer', 'float'):
                min_val, max_val = df[col].min(), df[col].max()
                extra_info.append(f"Range: {min_val} - {max_val}")
            elif category in ('text', 'categorical_text'):
                if unique_count is not None:
                    extra_info.append(f"Unique values: {unique_count}")
                    if unique_count <= 10:
                        try:
                            unique_vals = df[col].unique()[:5]
                            extra_info.append(f"Sample values: {list(unique_vals)}")
                        except TypeError:
                            # Column contains unhashable types (arrays, lists)
                            extra_info.append("Sample values: [contains complex types]")
                else:
                    extra_info.append("Unique values: [contains unhashable types]")

            extra_str = f" ({', '.join(extra_info)})" if extra_info else ""
            null_str = f" [Nulls: {null_count}]" if null_count > 0 else ""

            column_info.append(f"- **{col}**: {dtype} → {category}{extra_str}{null_str}")

        return "\n".join(column_info)

    # ─────────────────────────────────────────────────────────────
    # Data Quality Checks (moved from PythonPandasTool)
    # ─────────────────────────────────────────────────────────────
    def check_dataframes_for_nans(
        self,
        names: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Check DataFrames for NaN/Null values.

        Args:
            names: Specific dataset names to check (defaults to all active)

        Returns:
            List of warning messages describing where NaNs were found.
        """
        warning_messages = []

        if names:
            datasets_to_check = {
                self._resolve_name(n): self._datasets.get(self._resolve_name(n))
                for n in names
            }
        else:
            datasets_to_check = {
                name: entry
                for name, entry in self._datasets.items()
                if entry.is_active and entry.loaded
            }

        for name, entry in datasets_to_check.items():
            if entry is None or not entry.loaded:
                continue

            try:
                df = entry.df
                if df.empty:
                    continue

                null_counts = df.isnull().sum()
                total_rows = len(df)

                # Filter for columns that actually have nulls
                cols_with_nulls = null_counts[null_counts > 0]

                if not cols_with_nulls.empty:
                    for col_name, count in cols_with_nulls.items():
                        percentage = (count / total_rows) * 100
                        warning_messages.append(
                            f"- DataFrame '{name}' (column '{col_name}'): "
                            f"Contains {count} NaNs ({percentage:.1f}% of {total_rows} rows)"
                        )

            except Exception as e:
                self.logger.warning("Error checking NaNs in dataframe '%s': %s", name, e)

        return warning_messages

    # ─────────────────────────────────────────────────────────────
    # Catalog Management (Internal Methods)
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_filter(
        df: pd.DataFrame,
        filter_dict: Dict[str, Any],
    ) -> pd.DataFrame:
        """Apply dictionary-based equality filters to a DataFrame.

        Each key is a column name. Each value is either:
        - A scalar: rows where ``column == value`` are kept.
        - A list/tuple/set: rows where column value is in the collection are kept.

        All conditions are ANDed together.

        Args:
            df: The DataFrame to filter.
            filter_dict: Mapping of column names to required values.

        Returns:
            Filtered DataFrame with reset index.

        Raises:
            ValueError: If a filter column is not found in the DataFrame.
        """
        mask = pd.Series(True, index=df.index)
        for col, value in filter_dict.items():
            if col not in df.columns:
                raise ValueError(
                    f"Filter column '{col}' not found in DataFrame. "
                    f"Available: {list(df.columns)}"
                )
            if isinstance(value, (list, tuple, set)):
                mask &= df[col].isin(value)
            else:
                mask &= df[col] == value
        return df.loc[mask].reset_index(drop=True)

    async def add_dataset(
        self,
        name: str,
        *,
        description: Optional[str] = None,
        query_slug: Optional[str] = None,
        query: Optional[str] = None,
        table: Optional[str] = None,
        dataframe: Optional[pd.DataFrame] = None,
        driver: Optional[str] = None,
        dsn: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        sql: Optional[str] = None,
        filter: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Fetch data from any source and register the result as an in-memory DataFrame.

        Unlike the lazy ``add_query`` / ``add_table_source`` methods, this
        executes the source immediately and stores the resulting DataFrame so
        the LLM can work with it via ``python_repl_pandas`` without extra
        fetch steps.

        Exactly one of ``query_slug``, ``query``, ``table``, or ``dataframe``
        must be provided.

        Args:
            name: Dataset name/identifier.
            query_slug: QuerySource slug — fetched via QS.
            query: Raw SQL template (may contain ``{param}`` placeholders).
                   Requires ``driver``.
            table: Fully-qualified table name (e.g. ``"schema.table"``).
                   Requires ``driver``.  Pass ``sql`` for a targeted SELECT
                   or omit it to fetch all rows (``SELECT * FROM table``).
            dataframe: An already-loaded pandas DataFrame.
            driver: AsyncDB driver (``"pg"``, ``"bigquery"``, …).
                    Required when using ``query`` or ``table``.
            dsn: Optional DSN override for the database connection.
            credentials: Optional credentials dict for the database connection.
            conditions: Parameter values for SQL-template placeholders
                        (``query`` mode) or QS conditions (``query_slug`` mode).
            sql: SQL statement for ``table`` mode.  When omitted a
                 ``SELECT * FROM <table>`` is executed.
            filter: Optional dictionary-based filter applied to the fetched
                    DataFrame before registration.  Each key is a column name;
                    scalar values use equality matching, list/tuple/set values
                    use ``isin`` matching.  All conditions are ANDed.
            metadata: Optional metadata dict (description, etc.).
            is_active: Whether the dataset is active (default ``True``).
            permanent_filter: Optional dict of equality conditions that are
                always applied when fetching data. For ``query_slug`` mode,
                merged into QS conditions. For ``table`` mode, injected as
                a WHERE clause. Ignored for ``dataframe`` and ``query`` modes.

        Returns:
            Confirmation message with shape.

        Raises:
            ValueError: If the source arguments are ambiguous or incomplete,
                or if a filter column is not found in the DataFrame.
        """
        sources_given = sum(
            x is not None for x in (query_slug, query, table, dataframe)
        )
        if sources_given != 1:
            raise ValueError(
                "Provide exactly one of: query_slug, query, table, or dataframe."
            )

        df: pd.DataFrame

        if dataframe is not None:
            if not isinstance(dataframe, pd.DataFrame):
                raise ValueError("dataframe must be a pandas DataFrame")
            df = dataframe

        elif query_slug is not None:
            from .sources.query_slug import QuerySlugSource
            source = QuerySlugSource(
                slug=query_slug, permanent_filter=permanent_filter,
            )
            params = dict(conditions) if conditions else {}
            df = await source.fetch(**params)

        elif query is not None:
            if not driver:
                raise ValueError("driver is required when using query=")
            from .sources.sql import SQLQuerySource
            source = SQLQuerySource(sql=query, driver=driver, dsn=dsn)
            params = dict(conditions) if conditions else {}
            df = await source.fetch(**params)

        elif table is not None:
            if not driver:
                raise ValueError("driver is required when using table=")
            from .sources.table import TableSource
            source = TableSource(
                table=table,
                driver=driver,
                dsn=dsn,
                credentials=credentials,
                strict_schema=False,
                permanent_filter=permanent_filter,
            )
            fetch_sql = sql or f"SELECT * FROM {table}"
            df = await source.fetch(sql=fetch_sql)

        if filter:
            df = self._apply_filter(df, filter)

        return self.add_dataframe(
            name=name, df=df, description=description, metadata=metadata,
            is_active=is_active, computed_columns=computed_columns,
        )

    def add_dataframe(
        self,
        name: str,
        df: pd.DataFrame,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """
        Add a DataFrame to the catalog.

        Datasets are ACTIVE by default when added, meaning they are
        immediately available for analysis.

        Args:
            name: Name/identifier for the dataset
            df: pandas DataFrame to add
            description: Optional human-readable description of the dataset.
            metadata: Optional metadata dictionary with description, column info
            is_active: Whether dataset is active (default True)
            computed_columns: Optional list of ``ComputedColumnDef`` objects
                applied post-materialization.  Applied immediately when *df*
                is provided directly.

        Returns:
            Confirmation message
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df must be a pandas DataFrame")

        from .sources.memory import InMemorySource

        source = InMemorySource(df=df, name=name)
        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        # Pre-load: InMemorySource has data immediately
        entry._df = df
        # Apply computed columns before type detection
        if entry._computed_columns:
            entry._apply_computed_columns()
        if self.auto_detect_types:
            entry._column_types = self.categorize_columns(entry._df)
        self._datasets[name] = entry

        # Regenerate guide if enabled
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        n_rows, n_cols = entry._df.shape
        self.logger.debug("Dataset '%s' added (%d rows × %d cols)", name, n_rows, n_cols)
        return f"Dataset '{name}' added ({n_rows} rows × {n_cols} cols)"

    def add_dataframe_from_file(
        self,
        name: str,
        path: Union[str, PathLike[str]],
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        **kwargs: Any,
    ) -> str:
        """
        Create and add a DataFrame from a CSV or Excel file.

        File type detection is based on extension. For Excel files, a default
        engine is selected unless explicitly provided via kwargs.

        Args:
            name: Name/identifier for the dataset
            path: Path to the CSV/Excel file
            metadata: Optional metadata dictionary with description, column info
            is_active: Whether dataset is active (default True)
            **kwargs: Passed directly to pandas read_csv/read_excel

        Returns:
            Confirmation message from add_dataframe
        """
        path_str = str(path)
        extension = path_str.rsplit(".", 1)[-1].lower() if "." in path_str else ""

        if extension == "csv":
            df = pd.read_csv(path_str, **kwargs)
        elif extension in {"xls", "xlsx", "xlsm", "xlsb", "ods"}:
            if "engine" not in kwargs:
                engine_map = {
                    "xlsx": "openpyxl",
                    "xlsm": "openpyxl",
                    "xls": "xlrd",
                    "xlsb": "pyxlsb",
                    "ods": "odf",
                }
                kwargs["engine"] = engine_map.get(extension)
            df = pd.read_excel(path_str, **kwargs)
        else:
            raise ValueError(
                f"Unsupported file extension '{extension}'. Expected CSV or Excel file."
            )

        return self.add_dataframe(name=name, df=df, metadata=metadata, is_active=is_active)

    def add_query(
        self,
        name: str,
        query_slug: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Register a query slug for lazy loading.

        Args:
            name: Name/identifier for the dataset.
            query_slug: QuerySource slug to load data from.
            description: Optional human-readable description of the dataset.
            metadata: Optional metadata dictionary.
            is_active: Whether dataset is active (default True).
            permanent_filter: Optional dict of equality conditions that are
                always merged into every fetch() call. Permanent filter keys
                take precedence over runtime params.
            computed_columns: Optional list of ``ComputedColumnDef`` objects
                applied post-materialization.

        Returns:
            Confirmation message.
        """
        from .sources.query_slug import QuerySlugSource

        source = QuerySlugSource(slug=query_slug, permanent_filter=permanent_filter)
        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry
        self.logger.debug("Query '%s' registered (slug: %s)", name, query_slug)
        return f"Query '{name}' registered (slug: {query_slug})"

    async def add_table_source(
        self,
        name: str,
        table: str,
        driver: str,
        *,
        description: Optional[str] = None,
        dsn: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        strict_schema: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
        allowed_columns: Optional[List[str]] = None,
        no_cache: bool = False,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Register a database table with schema prefetch.

        Runs INFORMATION_SCHEMA query on registration to discover column names
        and types. The LLM receives schema information without fetching any rows.

        Args:
            name: Name/identifier for the dataset.
            table: Fully-qualified table name, e.g. "public.orders".
            driver: AsyncDB driver name, e.g. "pg", "bigquery", "mysql".
            dsn: Optional DSN string.
            credentials: Optional credentials dict.
            metadata: Optional metadata dict with description, etc.
            cache_ttl: Redis cache TTL in seconds (default 3600).
            strict_schema: If True (default), raise on prefetch failure.
            permanent_filter: Optional dict of equality conditions that are
                always injected as a WHERE clause into every fetch() SQL.
                Scalar values produce ``col = 'val'``; list/tuple values
                produce ``col IN ('a', 'b')``.
            allowed_columns: Optional list of column names to restrict access.
                When set, only these columns appear in the schema, guide, and
                metadata. SQL queries referencing other columns are rejected.
            no_cache: If True, skip the Redis cache layer entirely for this
                table source.  Every ``fetch_dataset`` call executes the SQL
                directly against the database.  Useful for small/parameter
                tables where fresh data is always needed.

        Returns:
            Confirmation message with column count, driver, and restriction info.
        """
        from .sources.table import TableSource

        source = TableSource(
            table=table,
            driver=driver,
            dsn=dsn,
            credentials=credentials,
            strict_schema=strict_schema,
            permanent_filter=permanent_filter,
            allowed_columns=allowed_columns,
        )
        await source.prefetch_schema()  # raises on failure if strict_schema=True
        await source.prefetch_row_count()  # estimate row count for size warnings
        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            no_cache=no_cache,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        n_cols = len(source._schema)
        row_est = source._row_count_estimate
        row_info = f", ~{row_est:,} rows" if row_est is not None else ""
        col_info = (
            f", restricted to {len(allowed_columns)} allowed columns"
            if allowed_columns else ""
        )
        self.logger.debug(
            "Table source '%s' registered (%d columns, %s%s%s)",
            name, n_cols, driver, row_info, col_info,
        )
        return (
            f"Table source '{name}' registered "
            f"({n_cols} columns, {driver}{row_info}{col_info})."
        )

    def add_sql_source(
        self,
        name: str,
        sql: str,
        driver: str,
        *,
        description: Optional[str] = None,
        dsn: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Register a parameterized SQL source. Sync — no prefetch needed.

        The SQL may use {param} placeholders injected at fetch time.

        Args:
            name: Name/identifier for the dataset.
            sql: SQL template with optional {param} placeholders.
            driver: AsyncDB driver name, e.g. "pg", "bigquery", "mysql".
            description: Optional human-readable description of the dataset.
            dsn: Optional DSN string.
            metadata: Optional metadata dict.
            cache_ttl: Redis cache TTL in seconds (default 3600).
            computed_columns: Optional list of ``ComputedColumnDef`` objects
                applied post-materialization.

        Returns:
            Confirmation message.
        """
        from .sources.sql import SQLQuerySource

        source = SQLQuerySource(sql=sql, driver=driver, dsn=dsn)
        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry
        self.logger.debug("SQL source '%s' registered (%s)", name, driver)
        return f"SQL source '{name}' registered ({driver})."


    async def add_airtable_source(
        self,
        name: str,
        base_id: str,
        table: str,
        api_key: Optional[str] = None,
        view: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        fetch_on_create: bool = True,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Register an Airtable table source and optionally fetch immediately."""
        from .sources.airtable import AirtableSource

        source = AirtableSource(
            base_id=base_id,
            table=table,
            api_key=api_key,
            view=view,
        )
        await source.prefetch_schema()
        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry

        if fetch_on_create:
            await self.materialize(name, force_refresh=True)

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        self.logger.debug("Airtable source '%s' registered (%s/%s)", name, base_id, table)
        return f"Airtable source '{name}' registered ({base_id}/{table})."

    async def add_smartsheet_source(
        self,
        name: str,
        sheet_id: str,
        access_token: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        fetch_on_create: bool = True,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Register a Smartsheet source and optionally fetch immediately."""
        from .sources.smartsheet import SmartsheetSource

        source = SmartsheetSource(
            sheet_id=sheet_id,
            access_token=access_token,
        )
        # Skip prefetch_schema when fetch_on_create=True: fetch() will
        # populate the schema as part of materialization, avoiding a
        # redundant API round-trip.
        if not fetch_on_create:
            await source.prefetch_schema()
        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry

        if fetch_on_create:
            await self.materialize(name, force_refresh=True)

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        self.logger.debug("Smartsheet source '%s' registered (%s)", name, sheet_id)
        return f"Smartsheet source '{name}' registered ({sheet_id})."

    async def add_iceberg_source(
        self,
        name: str,
        table_id: str,
        catalog_params: Dict[str, Any],
        *,
        description: Optional[str] = None,
        factory: str = "pandas",
        credentials: Optional[Dict[str, Any]] = None,
        dsn: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        no_cache: bool = False,
        is_active: bool = True,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Register an Apache Iceberg table with schema and row-count prefetch.

        Calls ``source.prefetch_schema()`` (loads table metadata) and
        ``source.prefetch_row_count()`` (COUNT(*) estimate) on registration.
        The LLM receives column names, types, and size info without fetching
        any rows.

        Args:
            name: Dataset name/identifier.
            table_id: Fully-qualified Iceberg table identifier,
                e.g. ``"demo.cities"``.
            catalog_params: asyncdb iceberg driver connection params
                (uri, warehouse, catalog type, etc.).
            description: Optional human-readable description.
            factory: asyncdb output factory (default ``"pandas"``).
            credentials: Optional credentials dict for the catalog.
            dsn: Optional DSN string (rarely used for Iceberg).
            metadata: Optional metadata dict.
            cache_ttl: Redis cache TTL in seconds (default 3600).
            no_cache: If True, skip the Redis cache layer for this source.
            is_active: Whether the dataset is active (default True).

        Returns:
            Confirmation message with column count and catalog type.
        """
        from .sources.iceberg import IcebergSource

        source = IcebergSource(
            table_id=table_id,
            name=name,
            catalog_params=catalog_params,
            factory=factory,
            credentials=credentials,
            dsn=dsn,
        )
        await source.prefetch_schema()
        await source.prefetch_row_count()

        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            no_cache=no_cache,
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        n_cols = len(source._schema)
        row_est = source._row_count_estimate
        row_info = f", ~{row_est:,} rows" if row_est is not None else ""
        catalog_type = catalog_params.get("type") or catalog_params.get("catalog_type", "unknown")
        self.logger.debug(
            "Iceberg source '%s' registered (%d columns, catalog: %s%s)",
            name, n_cols, catalog_type, row_info,
        )
        return (
            f"Iceberg source '{name}' registered "
            f"({n_cols} columns, catalog: {catalog_type}{row_info})."
        )

    async def add_mongo_source(
        self,
        name: str,
        collection: str,
        database: str,
        *,
        description: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        dsn: Optional[str] = None,
        required_filter: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        no_cache: bool = False,
        is_active: bool = True,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Register a MongoDB/DocumentDB collection with schema prefetch.

        Calls ``source.prefetch_schema()`` via ``find_one()`` to infer field
        names and Python types from a single document. Read-only — every
        ``fetch_dataset()`` call requires a ``filter`` dict and a
        ``projection`` dict.

        Args:
            name: Dataset name/identifier.
            collection: MongoDB collection name, e.g. ``"orders"``.
            database: MongoDB database name, e.g. ``"mydb"``.
            description: Optional human-readable description.
            credentials: Optional credentials dict with host/port/user/password.
                Used when dsn is None.
            dsn: Optional MongoDB connection string (DSN).
            required_filter: If True (default), ``fetch_dataset()`` raises
                ``ValueError`` when no ``filter`` is provided.
            metadata: Optional metadata dict.
            cache_ttl: Redis cache TTL in seconds (default 3600).
            no_cache: If True, skip the Redis cache layer for this source.
            is_active: Whether the dataset is active (default True).

        Returns:
            Confirmation message with field count.
        """
        from .sources.mongo import MongoSource

        source = MongoSource(
            collection=collection,
            name=name,
            database=database,
            credentials=credentials,
            dsn=dsn,
            required_filter=required_filter,
        )
        await source.prefetch_schema()

        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            no_cache=no_cache,
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        n_fields = len(source._schema)
        self.logger.debug(
            "Mongo source '%s' registered (%d fields, %s.%s)",
            name, n_fields, database, collection,
        )
        return (
            f"Mongo source '{name}' registered "
            f"({n_fields} fields, {database}.{collection})."
        )

    async def add_deltatable_source(
        self,
        name: str,
        path: str,
        *,
        description: Optional[str] = None,
        table_name: Optional[str] = None,
        mode: str = "error",
        credentials: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        no_cache: bool = False,
        is_active: bool = True,
        computed_columns: Optional[List[Any]] = None,
    ) -> str:
        """Register a Delta Lake table with schema and row-count prefetch.

        Calls ``source.prefetch_schema()`` (reads Delta metadata) and
        ``source.prefetch_row_count()`` (COUNT(*) estimate) on registration.
        The LLM receives column names, types, and size info without fetching
        any rows.

        For S3 paths (``s3://...``), credentials are resolved automatically
        via ``AWSInterface`` unless explicit credentials are provided.

        Args:
            name: Dataset name/identifier.
            path: Path to the Delta table — local, ``s3://``, or ``gs://``.
            description: Optional human-readable description.
            table_name: DuckDB alias used in SQL queries. Defaults to the
                uppercased ``name``.
            mode: Write mode for creation helpers: ``overwrite``, ``append``,
                ``error``, ``ignore``. Defaults to ``"error"``.
            credentials: Optional credentials/storage-options dict.
                For S3, ``AWSInterface`` is used automatically when None.
            metadata: Optional metadata dict.
            cache_ttl: Redis cache TTL in seconds (default 3600).
            no_cache: If True, skip the Redis cache layer for this source.
            is_active: Whether the dataset is active (default True).

        Returns:
            Confirmation message with column count and path.
        """
        from .sources.deltatable import DeltaTableSource

        source = DeltaTableSource(
            path=path,
            name=name,
            table_name=table_name,
            mode=mode,
            credentials=credentials,
        )
        await source.prefetch_schema()
        await source.prefetch_row_count()

        entry = DatasetEntry(
            name=name,
            description=description,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            no_cache=no_cache,
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        n_cols = len(source._schema)
        row_est = source._row_count_estimate
        row_info = f", ~{row_est:,} rows" if row_est is not None else ""
        self.logger.debug(
            "Delta table source '%s' registered (%d columns, path: %s%s)",
            name, n_cols, path, row_info,
        )
        return (
            f"Delta table source '{name}' registered "
            f"({n_cols} columns, {path}{row_info})."
        )

    def add_composite_dataset(
        self,
        name: str,
        joins: List[Dict[str, Any]],
        *,
        description: str = "",
        computed_columns: Optional[List[Any]] = None,
        is_active: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a virtual composite dataset that JOINs existing datasets.

        Parses *joins* dicts into ``JoinSpec`` models, validates that all
        referenced component datasets are already registered, creates a
        ``CompositeDataSource``, wraps it in a ``DatasetEntry``, and registers
        the composite in ``_datasets``.

        Args:
            name: Dataset name/identifier for the composite.
            joins: List of dicts, each with keys ``left``, ``right``, ``on``
                and optionally ``how`` (default ``"inner"``) and ``suffixes``.
                Every referenced dataset must already be registered.
            description: Optional human-readable description forwarded to the
                composite source and entry.
            computed_columns: Optional list of ``ComputedColumnDef`` objects
                applied post-materialization on the JOIN result.
            is_active: Whether the dataset is active (default True).
            metadata: Optional metadata dictionary.

        Returns:
            Confirmation message including the join topology.

        Raises:
            ValueError: If any referenced component dataset is not registered.
        """
        from .sources.composite import JoinSpec, CompositeDataSource

        # Parse dicts → JoinSpec models
        join_specs = [JoinSpec(**j) for j in joins]

        # Validate all component datasets exist
        required: set = set()
        for j in join_specs:
            required.add(j.left)
            required.add(j.right)
        missing = required - set(self._datasets.keys())
        if missing:
            available = sorted(self._datasets.keys())
            raise ValueError(
                f"Composite '{name}': component dataset(s) {sorted(missing)!r} "
                f"are not registered. Available datasets: {available}"
            )

        # Create the composite source with back-reference to self
        source = CompositeDataSource(
            name=name,
            joins=join_specs,
            dataset_manager=self,
            description=description,
        )

        # Wrap in DatasetEntry (not pre-loaded — composite is lazy)
        entry = DatasetEntry(
            name=name,
            description=description or source.describe(),
            source=source,
            metadata=metadata or {},
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
        )
        self._datasets[name] = entry

        # Regenerate guide if enabled
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        n_joins = len(join_specs)
        join_desc = source.describe()
        self.logger.debug(
            "Composite dataset '%s' registered (%d join(s))", name, n_joins
        )
        return (
            f"Composite dataset '{name}' registered with {n_joins} join(s).\n"
            f"{join_desc}"
        )

    async def create_iceberg_from_dataframe(
        self,
        name: str,
        df: "pd.DataFrame",
        table_id: str,
        *,
        namespace: str = "default",
        catalog_params: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        mode: str = "overwrite",
    ) -> str:
        """Write a DataFrame to a new Iceberg table and register it as a dataset.

        Creates the Iceberg namespace (if needed), infers a PyArrow schema from
        the DataFrame, writes the data, then registers the table with
        ``add_iceberg_source()``.

        Args:
            name: Dataset name/identifier for the new source.
            df: DataFrame whose data is written to the Iceberg table.
            table_id: Fully-qualified target table identifier,
                e.g. ``"demo.cities"``.
            namespace: Iceberg namespace (catalog namespace) to create
                the table in. Defaults to ``"default"``.
            catalog_params: asyncdb iceberg driver connection params.
                Required — raises ``ValueError`` if None.
            description: Optional human-readable description.
            mode: Write mode for the data write step: ``"overwrite"`` or
                ``"append"``. Defaults to ``"overwrite"``.

        Returns:
            Confirmation message from ``add_iceberg_source()``.

        Raises:
            ValueError: If ``catalog_params`` is not provided.
            RuntimeError: If table creation or write fails.
        """
        from .sources.iceberg import IcebergSource

        if not catalog_params:
            raise ValueError(
                "catalog_params is required for create_iceberg_from_dataframe"
            )

        tmp_source = IcebergSource(
            table_id=table_id,
            name=name,
            catalog_params=catalog_params,
        )
        driver = tmp_source._get_driver()
        async with await driver.connection() as conn:
            await IcebergSource.create_table_from_df(
                driver=conn,
                df=df,
                table_id=table_id,
                namespace=namespace,
                mode=mode,
            )

        self.logger.info(
            "Iceberg table '%s' created from DataFrame (%d rows), registering source",
            table_id,
            len(df),
        )
        return await self.add_iceberg_source(
            name=name,
            table_id=table_id,
            catalog_params=catalog_params,
            description=description,
        )

    async def create_deltatable_from_parquet(
        self,
        name: str,
        parquet_path: str,
        delta_path: str,
        *,
        table_name: Optional[str] = None,
        mode: str = "overwrite",
        description: Optional[str] = None,
    ) -> str:
        """Create a Delta table from a Parquet file and register it as a dataset.

        Calls ``DeltaTableSource.create_from_parquet()`` to write the Delta
        table, then registers the result with ``add_deltatable_source()``.

        Args:
            name: Dataset name/identifier for the new source.
            parquet_path: Path to the source Parquet file (local or cloud).
            delta_path: Target path for the new Delta table — local,
                ``s3://``, or ``gs://``.
            table_name: DuckDB alias for SQL queries against this table.
                Defaults to the uppercased ``name``.
            mode: Write mode: ``"overwrite"``, ``"append"``, ``"error"``,
                ``"ignore"``. Defaults to ``"overwrite"``.
            description: Optional human-readable description.

        Returns:
            Confirmation message from ``add_deltatable_source()``.

        Raises:
            RuntimeError: If Delta table creation fails.
        """
        from .sources.deltatable import DeltaTableSource

        await DeltaTableSource.create_from_parquet(
            delta_path=delta_path,
            parquet_path=parquet_path,
            table_name=table_name,
            mode=mode,
        )

        self.logger.info(
            "Delta table created at '%s' from '%s', registering source",
            delta_path,
            parquet_path,
        )
        return await self.add_deltatable_source(
            name=name,
            path=delta_path,
            table_name=table_name,
            description=description,
        )

    def remove(self, name: str) -> str:
        """Remove a dataset from the catalog."""
        name = self._resolve_name(name)
        if name not in self._datasets:
            raise ValueError(f"Dataset '{name}' not found")
        del self._datasets[name]

        # Regenerate guide if enabled
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        self.logger.debug("Dataset '%s' removed", name)
        return f"Dataset '{name}' removed"

    def set_query_loader(self, loader: Any) -> None:
        """Set the query loader callable (from PandasAgent)."""
        self._query_loader = loader

    async def _load_query(self, name: str) -> pd.DataFrame:
        """Load a dataset from its query slug via the legacy query loader."""
        entry = self._datasets.get(name)
        if not entry or not entry.query_slug:
            raise ValueError(f"No query slug for dataset '{name}'")

        if not self._query_loader:
            raise RuntimeError("Query loader not set")

        result = await self._query_loader([entry.query_slug])
        if result and name in result:
            df = result[name]
        elif result:
            df = list(result.values())[0]
        else:
            raise RuntimeError(f"Query returned no data for '{name}'")

        entry._df = df
        # Rebuild column types after loading
        if self.auto_detect_types:
            entry._column_types = self.categorize_columns(df)

        return df

    def activate(self, names: Union[str, List[str]]) -> List[str]:
        """Mark datasets as active for use in the session."""
        if isinstance(names, str):
            names = [names]

        activated = []
        for name in names:
            resolved = self._resolve_name(name)
            if resolved in self._datasets:
                self._datasets[resolved].is_active = True
                activated.append(resolved)

        # Regenerate guide when activation changes
        if activated and self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        return activated

    def deactivate(self, names: Union[str, List[str]]) -> List[str]:
        """Mark datasets as inactive (exclude from session)."""
        if isinstance(names, str):
            names = [names]

        deactivated = []
        for name in names:
            resolved = self._resolve_name(name)
            if resolved in self._datasets:
                self._datasets[resolved].is_active = False
                deactivated.append(resolved)

        # Regenerate guide when activation changes
        if deactivated and self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        return deactivated

    def get_active_dataframes(self) -> Dict[str, pd.DataFrame]:
        """Get all active DataFrames (loaded only)."""
        return {
            name: entry.df
            for name, entry in self._datasets.items()
            if entry.is_active and entry.loaded
        }

    async def get_active_dataframes_lazy(self) -> Dict[str, pd.DataFrame]:
        """Get active dataframes, loading from queries if needed."""
        result = {}
        for name, entry in self._datasets.items():
            if not entry.is_active:
                continue
            if not entry.loaded and entry.query_slug:
                await self._load_query(name)
            if entry.loaded:
                result[name] = entry.df
        return result

    def get_dataset_entry(self, name: str) -> Optional[DatasetEntry]:
        """Get a dataset entry by name or alias."""
        resolved = self._resolve_name(name)
        return self._datasets.get(resolved)

    def list_dataframes(self) -> Dict[str, Dict[str, Any]]:
        """
        List all loaded DataFrames with detailed info.

        Returns original names as keys with alias, shape, columns,
        memory usage, null count, and column types.
        """
        alias_map = self._get_alias_map()
        result = {}
        for name, entry in self._datasets.items():
            if not entry.loaded:
                continue
            df = entry.df
            result[name] = {
                'original_name': name,
                'alias': alias_map.get(name),
                'shape': df.shape,
                'columns': df.columns.tolist(),
                'memory_usage_mb': round(entry.memory_usage_mb, 2),
                'null_count': entry.null_count,
                'column_types': entry.column_types,
            }
        return result

    def get_dataframe_summary(self, name: str) -> Dict[str, Any]:
        """
        Get detailed summary for a specific DataFrame.

        Accepts both original name and alias.

        Args:
            name: Dataset name or alias

        Returns:
            Comprehensive DataFrame info dictionary

        Raises:
            ValueError: If dataset not found
        """
        resolved = self._resolve_name(name)
        entry = self._datasets.get(resolved)

        if not entry or not entry.loaded:
            available = list(self._datasets.keys())
            raise ValueError(f"DataFrame '{name}' not found or not loaded. Available: {available}")

        return self.get_dataframe_info(entry.df)

    def _safe_duplicate_count(self, df: pd.DataFrame) -> int:
        """
        Safely count duplicate rows, handling unhashable types (lists/arrays).

        Returns -1 if duplicate check fails due to unhashable types.
        """
        try:
            return int(df.duplicated().sum())
        except TypeError:
            # Fallback: unhashable types present, duplicates cannot be easily computed
            # We return -1 to indicate error/unknown
            return -1

    @staticmethod
    def _clean_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Convert a DataFrame to a list of JSON-safe dicts.

        Handles numpy scalars, NaN/NaT, and Timestamp objects so the
        result can be safely serialised and returned to the LLM.

        Args:
            df: DataFrame to convert.

        Returns:
            List of row dicts with plain Python types.
        """
        records: List[Dict[str, Any]] = []
        for record in df.to_dict(orient='records'):
            clean: Dict[str, Any] = {}
            for k, v in record.items():
                if hasattr(v, 'item'):  # numpy scalar
                    v = v.item()
                elif hasattr(v, 'isoformat'):  # Timestamp / datetime
                    v = v.isoformat()
                elif v is None or (isinstance(v, float) and v != v):  # NaN
                    v = None
                clean[str(k)] = v
            records.append(clean)
        return records

    # ─────────────────────────────────────────────────────────────
    # Metadata / EDA Methods (Replaces MetadataTool)
    # ─────────────────────────────────────────────────────────────
    def _generate_eda_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Generate EDA summary for a DataFrame."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns
        datetime_cols = df.select_dtypes(include=['datetime64']).columns

        missing = df.isnull().sum()
        total_missing = int(missing.sum())
        missing_percentage = float(missing.sum() / df.size * 100) if df.size > 0 else 0.0
        memory_mb = float(df.memory_usage(deep=True).sum() / 1024 / 1024)

        columns_with_missing = [
            {
                "column": col,
                "missing_count": int(missing[col]),
                "missing_percentage": round(
                    float(missing[col] / len(df) * 100), 2
                ) if len(df) > 0 else 0.0
            }
            for col in df.columns if missing[col] > 0
        ]

        return {
            "basic_info": {
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "numeric_columns": len(numeric_cols),
                "categorical_columns": len(categorical_cols),
                "datetime_columns": len(datetime_cols),
                "memory_usage_mb": round(memory_mb, 2),
            },
            "missing_data": {
                "total_missing": total_missing,
                "missing_percentage": round(missing_percentage, 2),
                "columns_with_missing": columns_with_missing
            },
            "data_quality": {
                "duplicate_rows": self._safe_duplicate_count(df),
                "completeness_percentage": round((1 - missing_percentage / 100) * 100, 2)
            }
        }

    def _generate_column_statistics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Generate detailed statistics for all columns."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns

        stats: Dict[str, Any] = {"numeric_columns": {}, "categorical_columns": {}}

        for col in numeric_cols:
            series = df[col]
            stats["numeric_columns"][col] = {
                "dtype": str(series.dtype),
                "null_count": int(series.isnull().sum()),
                "mean": None if series.empty else round(float(series.mean()), 4),
                "median": None if series.empty else round(float(series.median()), 4),
                "std": None if series.empty else round(float(series.std()), 4),
                "min": None if series.empty else float(series.min()),
                "max": None if series.empty else float(series.max()),
            }

        for col in categorical_cols:
            value_counts = df[col].value_counts()
            stats["categorical_columns"][col] = {
                "unique_values": int(df[col].nunique()),
                "most_common": value_counts.head(5).to_dict(),
                "null_count": int(df[col].isnull().sum())
            }

        return stats

    def _compute_single_column_stats(self, series: pd.Series) -> Dict[str, Any]:
        """Compute statistics for a single column."""
        stats: Dict[str, Any] = {
            "dtype": str(series.dtype),
            "null_count": int(series.isnull().sum()),
            "null_percentage": round(
                float(series.isnull().sum() / len(series) * 100), 2
            ) if len(series) > 0 else 0.0
        }

        if pd.api.types.is_numeric_dtype(series):
            stats.update({
                "mean": None if series.empty else round(float(series.mean()), 4),
                "median": None if series.empty else round(float(series.median()), 4),
                "std": None if series.empty else round(float(series.std()), 4),
                "min": None if series.empty else float(series.min()),
                "max": None if series.empty else float(series.max()),
            })
        else:
            stats.update({
                "unique_values": int(series.nunique()),
                "most_common": None if series.mode().empty else str(series.mode().iloc[0]),
            })

        return stats

    # ─────────────────────────────────────────────────────────────
    # Computed Columns — LLM Runtime Tools
    # ─────────────────────────────────────────────────────────────

    async def add_computed_column(
        self,
        dataset_name: str,
        column_name: str,
        func: str,
        columns: List[str],
        description: str = "",
        **kwargs: Any,
    ) -> str:
        """Add a computed column to an existing dataset at runtime.

        The function must be registered in the computed-function registry.
        If the dataset is already loaded, the column is applied immediately
        and the guide is regenerated.

        Args:
            dataset_name: Name or alias of the target dataset.
            column_name: Name of the new column to create.
            func: Function name from the computed-function registry.
                  Call ``list_available_functions()`` to see available functions.
            columns: Source column names the function operates on (in order).
            description: Optional human-readable description of the new column.
            **kwargs: Extra keyword arguments forwarded to the function
                      (e.g. ``operation="subtract"`` for ``math_operation``).

        Returns:
            Confirmation message if successful, or an error message if
            the function/dataset/columns could not be resolved.
        """
        from .computed import get_computed_function, ComputedColumnDef

        # Validate function
        fn = get_computed_function(func)
        if fn is None:
            from .computed import list_computed_functions
            available = list_computed_functions()
            return (
                f"Unknown function '{func}'. "
                f"Available functions: {available}. "
                f"Call list_available_functions() to see the full list."
            )

        # Resolve dataset
        resolved = self._resolve_name(dataset_name)
        entry = self._datasets.get(resolved)
        if entry is None:
            return (
                f"Dataset '{dataset_name}' not found. "
                f"Available datasets: {list(self._datasets.keys())}."
            )

        # Validate source columns exist when dataset is loaded or has schema
        known_cols: List[str] = []
        if entry.loaded and entry._df is not None:
            known_cols = entry._df.columns.tolist()
        elif entry.columns:
            known_cols = entry.columns

        if known_cols:
            missing = [c for c in columns if c not in known_cols]
            if missing:
                return (
                    f"Source column(s) not found in dataset '{resolved}': {missing}. "
                    f"Available columns: {known_cols}."
                )

        # Create and store the definition
        col_def = ComputedColumnDef(
            name=column_name,
            func=func,
            columns=columns,
            kwargs=dict(kwargs),
            description=description,
        )
        entry._computed_columns.append(col_def)

        # Apply immediately if dataset is loaded
        if entry.loaded and entry._df is not None:
            try:
                entry._df = fn(entry._df, column_name, columns, **kwargs)
                if self.auto_detect_types:
                    entry._column_types = self.categorize_columns(entry._df)
            except Exception as exc:
                self.logger.error(
                    "Failed to apply computed column '%s' to '%s': %s",
                    column_name, resolved, exc,
                )
                # Remove the appended definition since application failed
                entry._computed_columns.pop()
                return (
                    f"Error applying computed column '{column_name}' to dataset "
                    f"'{resolved}': {exc}"
                )

        # Regenerate guide
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        return (
            f"Computed column '{column_name}' added to dataset '{resolved}' "
            f"using function '{func}' on columns {columns}."
        )

    async def list_available_functions(self) -> List[str]:
        """List all available computed-column functions.

        Returns the sorted list of function names that can be used with
        ``add_computed_column()`` or in ``ComputedColumnDef.func``.

        Returns:
            Sorted list of registered function name strings.
        """
        from .computed import list_computed_functions
        return list_computed_functions()

    # ─────────────────────────────────────────────────────────────
    # LLM-Exposed Tools (Async methods become tools via AbstractToolkit)
    # ─────────────────────────────────────────────────────────────

    async def list_datasets(self) -> List[Dict[str, Any]]:
        """
        List all datasets in the catalog with their status.

        CALL THIS FIRST before any analysis. Shows which datasets are already
        loaded (ready for python_repl_pandas) and which need fetch_dataset.

        Each entry includes: name, python_variable, python_alias, loaded status,
        shape, columns, and source type.

        Returns:
            List of dataset info dicts. Check 'loaded' field to know if data
            is already available in python_repl_pandas.
        """
        alias_map = self._get_alias_map()
        result = []
        for name, entry in self._datasets.items():
            info = entry.to_info(alias=alias_map.get(name)).model_dump()
            alias = alias_map.get(name, "")
            if entry.loaded:
                info["python_variable"] = name
                info["python_alias"] = alias
            else:
                # Don't advertise variable names for non-loaded datasets —
                # the LLM would try to use them in python_repl_pandas
                # and get NameError.
                info["python_variable"] = None
                info["python_alias"] = None
                if info.get("source_type") == "table":
                    info["action_required"] = (
                        f"Call get_source_schema(name='{name}') to see columns, "
                        f"then call fetch_dataset(name='{name}', "
                        f"sql='SELECT ...') with a targeted SQL query. "
                        f"IMPORTANT: Push aggregations to the database — use "
                        f"GROUP BY, COUNT, SUM, AVG in your SQL instead of "
                        f"fetching all rows and aggregating in pandas."
                    )
                elif info.get("source_type") == "iceberg":
                    info["action_required"] = (
                        f"Call fetch_dataset(name='{name}') for full table, "
                        f"or fetch_dataset(name='{name}', sql='SELECT ...') for SQL. "
                        f"Use get_source_schema(name='{name}') to see columns first."
                    )
                elif info.get("source_type") == "mongo":
                    info["action_required"] = (
                        f"Call fetch_dataset(name='{name}', "
                        f"filter={{\"field\": \"value\"}}, "
                        f"projection={{\"field\": 1, \"_id\": 0}}). "
                        f"Both filter and projection are required."
                    )
                elif info.get("source_type") == "deltatable":
                    info["action_required"] = (
                        f"Call fetch_dataset(name='{name}') for full table, "
                        f"fetch_dataset(name='{name}', sql='SELECT ...') for SQL, "
                        f"or fetch_dataset(name='{name}', columns=[...]) for column selection."
                    )
                elif info.get("source_type") == "composite":
                    info["action_required"] = (
                        f"Call fetch_dataset(name='{name}') to JOIN all components, "
                        f"or fetch_dataset(name='{name}', conditions={{\"column\": \"value\"}}) "
                        f"to filter components before joining."
                    )
                else:
                    info["action_required"] = (
                        f"Call fetch_dataset(name='{name}') to load this "
                        f"dataset. Use get_metadata(name='{name}') first "
                        f"if you need column names."
                    )
            result.append(info)
        return result

    async def list_available(self) -> List[Dict[str, Any]]:
        """Alias for list_datasets (backward compatibility)."""
        return await self.list_datasets()

    async def get_active(self) -> List[str]:
        """
        Get the names of all currently active datasets.

        Active datasets are available for analysis in python_repl_pandas.
        """
        return [
            name for name, entry in self._datasets.items()
            if entry.is_active
        ]

    async def get_datasets_summary(self) -> str:
        """Generate a bullet-list summary of all active datasets with descriptions.

        Each entry shows the dataset name and its description. Datasets without
        a description show ``(no description)``. Inactive datasets are excluded.

        Used both as an LLM-callable tool and internally for system prompt
        injection via ``_generate_dataframe_guide()``.

        Returns:
            Markdown-formatted bullet list of active datasets, or empty string
            when no active datasets are registered.
        """
        return self._build_datasets_summary_sync()

    def _build_datasets_summary_sync(self) -> str:
        """Build the datasets bullet-list summary synchronously.

        Shared implementation used by both the async ``get_datasets_summary``
        tool and the sync ``_generate_dataframe_guide`` method.

        Returns:
            Markdown bullet list of active datasets with descriptions.
        """
        lines = []
        for name, entry in self._datasets.items():
            if not entry.is_active:
                continue
            desc = entry.description or "(no description)"
            lines.append(f"- **{name}**: {desc}")
        return "\n".join(lines) if lines else ""

    async def get_metadata(
        self,
        name: str,
        include_eda: bool = False,
        include_samples: bool = True,
        include_column_stats: bool = False,
        include_metrics_guide: bool = False,
        column: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get comprehensive metadata about a dataset.

        Args:
            name: Dataset name or alias (e.g., 'sales_data' or 'df1')
            include_eda: Include EDA summary (row counts, missing values, memory)
            include_samples: Include sample rows from the DataFrame
            include_column_stats: Include detailed statistics for columns
            include_metrics_guide: Include formatted per-column metrics guide
            column: Get metadata for a specific column only

        Returns:
            Comprehensive dataset metadata including schema, EDA, and samples
        """
        resolved_name = self._resolve_name(name)
        entry = self._datasets.get(resolved_name)

        if not entry:
            available = list(self._datasets.keys())
            return {"error": f"Dataset '{name}' not found. Available: {available}"}

        if not entry.loaded:
            alias_map_unloaded = self._get_alias_map()
            info = entry.to_info(alias=alias_map_unloaded.get(resolved_name))
            source_type = info.source_type

            # Source-specific guidance telling the LLM how to call fetch_dataset.
            if source_type == "table":
                table_name = getattr(entry.source, 'table', resolved_name)
                message = (
                    f"Dataset not loaded. Call fetch_dataset(name='{resolved_name}', "
                    f"sql='SELECT … FROM {table_name} WHERE …') with a SQL query "
                    f"using the columns below. IMPORTANT: Push aggregations to "
                    f"the database — use GROUP BY, COUNT(), SUM(), AVG() in SQL "
                    f"instead of fetching all rows. For example, to count records "
                    f"per month: SELECT DATE_TRUNC('month', date_col) AS month, "
                    f"COUNT(*) FROM {table_name} WHERE … GROUP BY 1. "
                    f"Avoid SELECT * on large tables."
                )
            elif source_type == "sql":
                sql_template = getattr(entry.source, 'sql', '')
                placeholders = re.findall(r'\{(\w+)\}', sql_template)
                if placeholders:
                    message = (
                        f"Dataset not loaded. Call fetch_dataset(name='{resolved_name}', "
                        f"conditions={{{', '.join(repr(p) + ': …' for p in placeholders)}}}) "
                        f"providing values for: {', '.join(placeholders)}."
                    )
                else:
                    message = (
                        f"Dataset not loaded. Call fetch_dataset('{resolved_name}') "
                        f"to execute the query."
                    )
            elif source_type == "query_slug":
                message = (
                    f"Dataset not loaded. Call fetch_dataset('{resolved_name}') "
                    f"to load this dataset into memory."
                )
            elif source_type == "composite":
                message = (
                    f"Composite dataset not yet materialized. "
                    f"Call fetch_dataset('{resolved_name}') to JOIN all components, "
                    f"or fetch_dataset('{resolved_name}', conditions={{\"column\": \"value\"}}) "
                    f"to filter components before joining."
                )
            else:
                message = (
                    f"Dataset not loaded. Call fetch_dataset('{resolved_name}') "
                    f"to materialize."
                )

            response: Dict[str, Any] = {
                "name": resolved_name,
                "alias": info.alias,
                "loaded": False,
                "source_type": source_type,
                "source_description": info.source_description,
                "message": message,
            }
            if entry.query_slug:
                response["query_slug"] = entry.query_slug
            if info.columns:
                response["columns"] = info.columns
                response["column_types"] = info.column_types
            return response

        df = entry.df
        alias_map = self._get_alias_map()

        # Handle single column request
        if column:
            if column not in df.columns:
                return {"error": f"Column '{column}' not found. Available: {df.columns.tolist()}"}

            col_meta = entry._column_metadata.get(column, {})
            return {
                "dataframe": resolved_name,
                "alias": alias_map.get(resolved_name),
                "column": column,
                "metadata": col_meta,
                "statistics": self._compute_single_column_stats(df[column])
            }

        # Full dataset metadata
        result: Dict[str, Any] = {
            "dataframe": resolved_name,
            "alias": alias_map.get(resolved_name),
            "description": entry.description,
            "shape": {"rows": df.shape[0], "columns": df.shape[1]},
            "columns": entry._column_metadata,
            "column_types": entry.column_types,
            "is_active": entry.is_active,
        }

        if include_eda:
            result["eda_summary"] = self._generate_eda_summary(df)

        if include_samples:
            result["sample_rows"] = df.head(3).to_dict(orient='records')

        if include_column_stats:
            result["column_statistics"] = self._generate_column_statistics(df)

        if include_metrics_guide:
            result["metrics_guide"] = self.generate_metrics_guide(df)

        return result

    async def activate_datasets(self, names: List[str]) -> str:
        """
        Activate datasets for use in analysis.

        Use this when you want to include specific datasets in the current session.
        By default, all datasets are active when added.

        Args:
            names: List of dataset names or aliases to activate

        Returns:
            Confirmation message
        """
        if activated := self.activate(names):
            self._notify_change()
            return f"Activated datasets: {', '.join(activated)}"
        return f"No datasets found matching: {names}"

    async def deactivate_datasets(self, names: List[str]) -> str:
        """
        Deactivate datasets to exclude them from the current session.

        Deactivated datasets will not be available in python_repl_pandas
        until they are activated again.

        Args:
            names: List of dataset names or aliases to deactivate

        Returns:
            Confirmation message
        """
        if deactivated := self.deactivate(names):
            self._notify_change()
            return f"Deactivated datasets: {', '.join(deactivated)}"
        return f"No datasets found matching: {names}"

    async def remove_dataset(self, name: str) -> str:
        """
        Remove a dataset from the catalog entirely.

        This permanently removes the dataset. Use deactivate_datasets
        if you only want to temporarily exclude it.

        Args:
            name: Dataset name or alias to remove

        Returns:
            Confirmation message
        """
        resolved = self._resolve_name(name)
        try:
            result = self.remove(resolved)
            return result
        except ValueError as e:
            available = list(self._datasets.keys())
            return f"Error: {e}. Available datasets: {available}"

    async def get_dataframe(self, name: str) -> Dict[str, Any]:
        """
        Get a DataFrame by name or alias.

        Returns the DataFrame info and sample data. Use this to retrieve
        a specific dataset for inspection or further operations.

        Args:
            name: Dataset name or alias (e.g., 'sales_data' or 'df1')

        Returns:
            DataFrame information including shape, columns, and sample rows
        """
        resolved_name = self._resolve_name(name)
        entry = self._datasets.get(resolved_name)

        if not entry:
            available = list(self._datasets.keys())
            return {"error": f"Dataset '{name}' not found. Available: {available}"}

        if not entry.loaded:
            return {
                "name": resolved_name,
                "loaded": False,
                "message": "Dataset not loaded. Use activate_datasets first."
            }

        alias_map = self._get_alias_map()
        alias = alias_map.get(resolved_name, "")
        df = entry.df

        return {
            "name": resolved_name,
            "alias": alias,
            "python_variable": resolved_name,
            "python_alias": alias,
            "usage_hint": (
                f"In python_repl_pandas use `{resolved_name}` or `{alias}` "
                f"as the DataFrame variable. Do NOT invent variable names."
            ),
            "shape": {"rows": df.shape[0], "columns": df.shape[1]},
            "columns": df.columns.tolist(),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "column_types": entry.column_types,
            "is_active": entry.is_active,
            "null_count": entry.null_count,
            "sample_rows": df.head(3).to_dict(orient='records'),
        }

    async def store_dataframe(
        self,
        name: str,
        description: str = "",
    ) -> str:
        """
        Store a computed DataFrame from python_repl_pandas into the catalog.

        Use this ONLY when you have created a genuinely new DataFrame from
        computation (e.g., a filtered subset, aggregation, or join) and want
        to make it available for future queries.

        Do NOT call this for intermediate variables or for datasets that
        already exist in the catalog.

        Args:
            name: Variable name as it exists in python_repl_pandas.
            description: Short description of what this dataset contains.

        Returns:
            Confirmation message or error.
        """
        # Check if dataset already exists in the catalog
        resolved = self._resolve_name(name)
        if resolved in self._datasets and self._datasets[resolved].loaded:
            return f"Dataset '{resolved}' already exists in the catalog — no action needed."

        # Look up the variable from the REPL execution environment
        if self._repl_locals_getter is None:
            return (
                f"Cannot store '{name}': no REPL environment connected. "
                f"Create the DataFrame in python_repl_pandas first."
            )

        repl_locals = self._repl_locals_getter()
        df = repl_locals.get(name)
        if df is None or not isinstance(df, pd.DataFrame):
            available_dfs = [
                k for k, v in repl_locals.items()
                if isinstance(v, pd.DataFrame) and not k.startswith('_')
            ]
            return (
                f"Variable '{name}' not found or is not a DataFrame in "
                f"python_repl_pandas. Available DataFrames: {available_dfs}"
            )

        # Register in the catalog
        metadata = {"description": description} if description else {}
        self.add_dataframe(name, df, metadata=metadata, is_active=True)
        self._notify_change()

        alias_map = self._get_alias_map()
        alias = alias_map.get(name, "")
        return (
            f"DataFrame '{name}' stored in catalog "
            f"({df.shape[0]} rows x {df.shape[1]} columns). "
            f"Use `{name}` or `{alias}` in python_repl_pandas."
        )

    async def fetch_dataset(
        self,
        name: str,
        sql: Optional[str] = None,
        conditions: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Materialize a dataset by fetching data from its source.

        Use this to load data into memory before analysing it.
        - For TableSource: 'sql' is required — provide a SELECT using the schema columns.
        - For SQLQuerySource: 'conditions' injects {param} values into the SQL template.
        - For QuerySlugSource / InMemorySource: no extra params needed.

        After successful materialization the response includes the data (for small
        result sets) or sample rows (for large ones), plus schema and shape.

        **SQL QUERY STRATEGY for TableSource (IMPORTANT):**
        ALWAYS push computation to the database — do NOT fetch raw rows and
        aggregate in Python. Before writing your SQL, decide:
        1. Can the question be answered with a GROUP BY / COUNT / SUM / AVG?
           → Write that aggregation query directly. Example:
             "SELECT DATE_TRUNC('month', status_date) AS month, COUNT(*) ..."
        2. Do you need only a filtered subset? → Use WHERE + LIMIT.
        3. Only use SELECT * as a last resort for exploratory inspection of
           small tables or when you genuinely need every column and row.
        The database is far more efficient at aggregation than pandas on
        hundreds of thousands of rows.

        IMPORTANT: The response includes 'python_variable' and 'python_alias' fields.
        These are the ONLY valid variable names in python_repl_pandas.
        Always use one of these exact names — never modify or invent new names.

        Args:
            name: Dataset name or alias.
            sql: SQL query string (required for TableSource). ALWAYS write
                targeted queries with WHERE, GROUP BY, or LIMIT. Avoid SELECT *
                on large tables — push aggregations to the database.
            conditions: Dict of {param: value} pairs for SQLQuerySource templates.
            force_refresh: If True, bypass caches and re-fetch from source.

        Returns:
            Dict with status, shape, column schema, data or sample rows, and
            python_variable/python_alias for use in python_repl_pandas.
        """
        # ── Resolve entry early to tailor param handling per source type ──
        resolved = self._resolve_name(name)
        entry = self._datasets.get(resolved)
        if entry is None:
            return {
                "error": f"Dataset '{name}' not found.",
                "available": list(self._datasets.keys()),
                "hint": "Call list_datasets() to see all datasets.",
            }

        # Validate conditions type — LLMs sometimes pass a string instead of dict.
        if conditions is not None and not isinstance(conditions, dict):
            self.logger.warning(
                "fetch_dataset: 'conditions' must be a dict, got %s — ignoring",
                type(conditions).__name__,
            )
            conditions = None

        # ── Build params based on source type ─────────────────────────
        from .sources.query_slug import QuerySlugSource, MultiQuerySlugSource
        from .sources.memory import InMemorySource
        from .sources.table import TableSource
        from .sources.composite import CompositeDataSource

        params: Dict[str, Any] = {}
        if isinstance(entry.source, CompositeDataSource):
            # Composites accept a filter dict for per-component filtering.
            # Always force_refresh so the JOIN reflects current component state.
            if conditions:
                params['filter'] = conditions
            force_refresh = True
        elif isinstance(entry.source, (QuerySlugSource, MultiQuerySlugSource, InMemorySource)):
            # These sources do not accept sql or conditions — ignore them
            # to prevent the LLM from accidentally injecting invalid QS conditions.
            pass
        elif isinstance(entry.source, TableSource):
            # TableSource requires sql — reject calls without an explicit SQL
            # so the LLM is forced to write targeted queries (GROUP BY, WHERE,
            # LIMIT) instead of defaulting to SELECT *.
            if not sql:
                table_name = entry.source.table
                row_est = entry.source._row_count_estimate
                size_note = ""
                if row_est is not None:
                    size_note = f" This table has ~{row_est:,} rows."
                    warning = TableSource._size_warning(row_est)
                    if warning:
                        size_note += f" {warning}"
                return {
                    "error": (
                        f"TableSource '{table_name}' requires an explicit 'sql' parameter. "
                        f"Do NOT use SELECT * on large tables.{size_note}"
                    ),
                    "hint": (
                        f"Write a targeted SQL query. Examples:\n"
                        f"  - Aggregation: sql=\"SELECT DATE_TRUNC('month', date_col) AS month, "
                        f"COUNT(*) FROM {table_name} WHERE ... GROUP BY 1\"\n"
                        f"  - Filtered: sql=\"SELECT col1, col2 FROM {table_name} "
                        f"WHERE status = 'active' LIMIT 100\"\n"
                        f"  - Inspect schema first: call get_source_schema('{resolved}')"
                    ),
                }
            params['sql'] = sql
            if conditions:
                params.update(conditions)
            # Table sources ALWAYS re-fetch: the LLM generates a different
            # SQL each time (different columns, WHERE clauses, aggregations).
            # Serving stale in-memory or Redis-cached data from a prior SQL
            # causes wrong columns / missing filters.
            force_refresh = True
        else:
            if sql is not None:
                params['sql'] = sql
            if conditions:
                params.update(conditions)

        try:
            df = await self.materialize(name, force_refresh=force_refresh, **params)
        except Exception as exc:
            self.logger.error("fetch_dataset '%s' failed: %s", name, exc)
            # Provide source-aware guidance so the LLM can self-correct.
            source_type = type(entry.source).__name__
            if isinstance(entry.source, TableSource):
                hint = (
                    f"Source type is '{source_type}' (table='{entry.source.table}'). "
                    "A default SELECT * was attempted but the query failed. "
                    "Check database connectivity and table permissions."
                )
            else:
                hint = (
                    f"Source type is '{source_type}'. "
                    f"For QuerySlugSource/InMemorySource call fetch_dataset(name='{name}') "
                    "with no extra parameters. "
                    "For SQLQuerySource provide conditions=."
                )
            return {
                "error": f"Error fetching dataset '{name}': {exc}",
                "hint": hint,
            }

        nan_warnings = self.check_dataframes_for_nans([resolved])

        # Sync PythonPandasTool BEFORE reading alias map so aliases are
        # up-to-date with the just-materialized dataset.
        self._notify_change()

        alias_map = self._get_alias_map()
        alias = alias_map.get(resolved, "")

        # ── Determine how much data to return ─────────────────────────
        # Small result sets (targeted queries with WHERE/GROUP BY) are returned
        # in full so the LLM can answer directly without extra tool calls.
        # Large datasets get a sample + a note to use python_repl_pandas.
        #
        # Threshold scales with column count: narrow DataFrames (few columns)
        # can afford more rows inline without blowing up context.
        n_rows = len(df)
        n_cols = df.shape[1]
        if n_cols <= 5:
            max_inline = 500
        elif n_cols <= 15:
            max_inline = 200
        else:
            max_inline = 100
        return_all = n_rows <= max_inline

        # Sample size also scales — show more rows so the LLM sees a
        # representative preview, not just 10 rows.
        if return_all:
            sample_size = n_rows
        elif n_rows <= 1000:
            sample_size = min(50, n_rows)
        else:
            sample_size = 20

        try:
            source_df = df if return_all else df.head(sample_size)
            data_records = self._clean_records(source_df)
        except Exception:
            data_records = []

        result: Dict[str, Any] = {
            "status": "materialized",
            "dataset": resolved,
            "python_variable": resolved,
            "python_alias": alias,
            "usage_hint": (
                f"In python_repl_pandas, the DataFrame is available as "
                f"`{resolved}` or `{alias}`. "
                f"Use ONLY these variable names — no other names exist."
            ),
            "shape": {"rows": n_rows, "columns": n_cols},
            "columns": df.columns.tolist(),
            "column_schema": {
                str(col): str(dtype) for col, dtype in df.dtypes.items()
            },
        }

        if return_all:
            result["data"] = data_records
            result["complete"] = True
        else:
            result["eda_summary"] = self._generate_eda_summary(df)
            result["sample_rows"] = data_records
            result["complete"] = False
            result["note"] = (
                f"Dataset has {n_rows:,} rows — only {sample_size} shown here as preview. "
                f"The FULL dataset ({n_rows:,} rows) is loaded in memory as "
                f"`{resolved}` (or `{alias}`)."
            )
            result["action_required"] = (
                f"DO NOT print or repeat all {n_rows:,} rows in your response. "
                f"Instead, set data_variable='{resolved}' in your structured output "
                f"and the system will deliver the full dataset automatically. "
                f"Use python_repl_pandas ONLY if you need to filter, transform, "
                f"or compute something — then assign the result to a variable "
                f"and set data_variable to that variable name."
            )

        if nan_warnings:
            result["warnings"] = nan_warnings
        return result

    async def evict_dataset(self, name: str) -> str:
        """
        Release a materialized dataset from memory.

        Source reference and schema are retained. The dataset can be re-fetched
        with fetch_dataset later.

        Args:
            name: Dataset name or alias.

        Returns:
            Confirmation message.
        """
        return self.evict(name)

    async def get_source_schema(self, name: str) -> str:
        """
        Return the schema (column → type) for a registered source.

        For TableSource: schema is available before materialization (prefetched on registration).
        For other source types: requires a prior fetch_dataset call.

        Args:
            name: Dataset name or alias.

        Returns:
            Formatted schema string or error message.
        """
        resolved = self._resolve_name(name)
        entry = self._datasets.get(resolved)
        if entry is None:
            available = list(self._datasets.keys())
            return f"Dataset '{name}' not found. Available: {available}"

        # Prefer _column_types (post-fetch semantic types) over raw schema
        if entry._column_types:
            schema = entry._column_types
        else:
            schema = getattr(entry.source, '_schema', {})

        if not schema:
            return (
                f"Schema for '{resolved}' is not yet available. "
                f"Call fetch_dataset('{resolved}') first to load the data."
            )

        lines = [f"Schema for '{resolved}' ({entry.source.describe()}):"]
        for col, dtype in schema.items():
            lines.append(f"  - {col}: {dtype}")

        # Add size warning for TableSource so the LLM knows to use aggregations
        from .sources.table import TableSource
        row_count = getattr(entry.source, '_row_count_estimate', None)
        if isinstance(entry.source, TableSource) and row_count is not None:
            warning = TableSource._size_warning(row_count)
            if warning:
                lines.append("")
                lines.append(warning)
            else:
                lines.append(f"\nEstimated rows: {row_count:,}")

        return "\n".join(lines)

    async def check_data_quality(
        self,
        names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run data quality checks on datasets.

        Checks for NaN/null values, duplicates, and completeness across
        specified datasets or all active datasets.

        Args:
            names: Specific dataset names to check (defaults to all active)

        Returns:
            Data quality report with NaN warnings and completeness metrics
        """
        nan_warnings = self.check_dataframes_for_nans(names)

        # Determine which datasets to report on
        if names:
            check_names = [self._resolve_name(n) for n in names]
        else:
            check_names = [
                name for name, entry in self._datasets.items()
                if entry.is_active and entry.loaded
            ]

        dataset_quality = {}
        for name in check_names:
            entry = self._datasets.get(name)
            if not entry or not entry.loaded:
                continue

            df = entry.df
            total_cells = df.size
            null_cells = int(df.isnull().sum().sum())
            duplicate_rows = int(df.duplicated().sum())

            dataset_quality[name] = {
                "rows": len(df),
                "columns": len(df.columns),
                "total_cells": total_cells,
                "null_cells": null_cells,
                "completeness_pct": round((1 - null_cells / total_cells) * 100, 2) if total_cells > 0 else 100.0,
                "duplicate_rows": duplicate_rows,
                "duplicate_pct": round((duplicate_rows / len(df)) * 100, 2) if len(df) > 0 else 0.0,
            }

        return {
            "datasets_checked": len(dataset_quality),
            "nan_warnings": nan_warnings,
            "dataset_quality": dataset_quality,
        }

    # ─────────────────────────────────────────────────────────────
    # DataFrame Guide Generation
    # ─────────────────────────────────────────────────────────────
    def _generate_dataframe_guide(self) -> str:
        """Generate DataFrame guide for the LLM — supports mixed load states."""
        if not self._datasets:
            return "No datasets registered."

        alias_map = self._get_alias_map()
        active_entries = {
            name: entry for name, entry in self._datasets.items() if entry.is_active
        }
        if not active_entries:
            return "No active datasets."

        guide_parts = [
            "# DataFrame Guide",
            "",
            f"**Total active datasets**: {len(active_entries)}",
            "",
        ]

        # Prepend dataset summary section with descriptions
        summary = self._build_datasets_summary_sync()
        if summary:
            guide_parts.extend([
                "## Available Datasets",
                "",
                summary,
                "",
                "---",
                "",
            ])

        guide_parts.append("## Dataset Details:")

        for ds_name, entry in active_entries.items():
            alias = alias_map.get(ds_name, "")
            info = entry.to_info(alias=alias)
            source_label = info.source_type.upper().replace("_", " ")

            if entry.loaded and entry._df is not None:
                df = entry._df
                header = f"### `{ds_name}` [{source_label} — loaded]"
                if alias:
                    header += f" (alias: `{alias}`)"
                guide_parts.extend([
                    header,
                    f"- **Shape**: {df.shape[0]:,} rows × {df.shape[1]} columns",
                    f"- **Columns**: {', '.join(df.columns.tolist()[:10])}{'...' if len(df.columns) > 10 else ''}",
                    "",
                ])

                if self.include_summary_stats:
                    numeric_cols = df.select_dtypes(include=[np.number]).columns
                    if len(numeric_cols) > 0:
                        guide_parts.append("- **Numeric Summary**:")
                        guide_parts.extend(
                            f"  - `{col}`: min={df[col].min():.2f}, max={df[col].max():.2f}, mean={df[col].mean():.2f}"
                            for col in numeric_cols[:5]
                        )
                        guide_parts.append("")

                null_counts = df.isnull().sum()
                if null_counts.sum() > 0:
                    null_summary = [f"`{col}`: {count}" for col, count in null_counts.items() if count > 0]
                    guide_parts.extend([
                        "- **Missing Values**:",
                        f"  {', '.join(null_summary)}",
                        "",
                    ])
            else:
                # Not yet loaded — show schema if available (e.g. TableSource)
                header = f"### `{ds_name}` [{source_label} — not loaded]"
                guide_parts.append(header)
                guide_parts.append(f"- **Source**: {info.source_description}")

                if info.columns:
                    guide_parts.append("- **Columns (from schema)**:")
                    col_types = info.column_types or {}
                    for col in info.columns[:20]:
                        col_type = col_types.get(col, "unknown")
                        guide_parts.append(f"  - {col} ({col_type})")
                    if len(info.columns) > 20:
                        guide_parts.append(f"  ... and {len(info.columns) - 20} more")
                else:
                    guide_parts.append("- **Columns**: unknown until fetched")

                if info.source_type == "table":
                    guide_parts.append(
                        f'\n- **To use**: `fetch_dataset("{ds_name}", sql="SELECT ... FROM {info.source_description}")`'
                    )
                elif info.source_type == "iceberg":
                    table_id = getattr(entry.source, '_table_id', ds_name)
                    guide_parts.append(
                        f'\n- **To use** (full table): `fetch_dataset("{ds_name}")`'
                    )
                    guide_parts.append(
                        f'- **To use** (SQL): `fetch_dataset("{ds_name}", sql="SELECT ... FROM {table_id} WHERE ...")`'
                    )
                    if info.table_size_warning:
                        guide_parts.append(f'- **⚠️ Size warning**: {info.table_size_warning}')
                elif info.source_type == "mongo":
                    guide_parts.append(
                        f'\n- **To use**: `fetch_dataset("{ds_name}", filter={{"field": "value"}}, projection={{"field": 1, "_id": 0}})`'
                    )
                    guide_parts.append(
                        '- **Required**: Both `filter` and `projection` must be provided. No full-collection scans.'
                    )
                elif info.source_type == "deltatable":
                    table_alias = getattr(entry.source, '_table_name', ds_name.upper())
                    guide_parts.append(
                        f'\n- **To use** (full table): `fetch_dataset("{ds_name}")`'
                    )
                    guide_parts.append(
                        f'- **To use** (SQL): `fetch_dataset("{ds_name}", sql="SELECT ... FROM {table_alias} WHERE ...")`'
                    )
                    guide_parts.append(
                        f'- **To use** (columns): `fetch_dataset("{ds_name}", columns=["col1", "col2"])`'
                    )
                    if info.table_size_warning:
                        guide_parts.append(f'- **⚠️ Size warning**: {info.table_size_warning}')
                elif info.source_type == "composite":
                    from .sources.composite import CompositeDataSource as _CDS
                    source = entry.source
                    if isinstance(source, _CDS):
                        components = ", ".join(sorted(source.component_names))
                        guide_parts.append(f"- **Components**: {components}")
                        for j in source.joins:
                            on_str = j.on if isinstance(j.on, str) else ", ".join(j.on)
                            guide_parts.append(
                                f"  - {j.left} {j.how.upper()} JOIN {j.right} ON {on_str}"
                            )
                    guide_parts.append(
                        f'\n- **To use**: `fetch_dataset("{ds_name}")` or '
                        f'`fetch_dataset("{ds_name}", conditions={{"column": "value"}})` '
                        f'to filter components before joining.'
                    )
                else:
                    guide_parts.append(f'\n- **To use**: `fetch_dataset("{ds_name}")`')

                guide_parts.append("")

        # Usage section — only for loaded dataframes
        active_loaded = {n: e._df for n, e in active_entries.items() if e.loaded and e._df is not None}
        if active_loaded:
            guide_parts.extend([
                "---",
                "## Usage Examples",
                "",
                "**IMPORTANT**: Always use the PRIMARY dataframe names in your code:",
                "",
                "```python",
            ])
            first_name = list(active_loaded.keys())[0]
            first_alias = alias_map.get(first_name, f"{self.df_prefix}1")
            guide_parts.extend([
                "# ✅ CORRECT: Use original names",
                f"print({first_name}.shape)",
                f"result = {first_name}.groupby('column_name').size()",
                f"filtered = {first_name}[{first_name}['column'] > 100]",
                "",
                "# ✅ ALSO WORKS: Use aliases if more convenient",
                f"print({first_alias}.shape)  # Same DataFrame, different name",
                "```",
                "",
                "## Key Points",
                "",
                f"1. **Primary Names**: Use the original dataset names (e.g., `{first_name}`)",
                f"2. **Aliases Available**: You can also use `{self.df_prefix}1`, `{self.df_prefix}2`, etc.",
                "3. **Both Work**: The DataFrames are accessible by BOTH names in the execution environment",
                "4. **Recommendation**: Use original names for clarity, aliases for brevity",
                "",
            ])

        return "\n".join(guide_parts)

    def get_guide(self) -> str:
        """Return the current DataFrame guide."""
        if not self.df_guide and self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()
        return self.df_guide

    # ─────────────────────────────────────────────────────────────
    # Data Loading & Caching
    # ─────────────────────────────────────────────────────────────

    async def _get_redis_connection(self) -> aioredis.Redis:
        """Get or create a pooled Redis connection (binary mode for Parquet)."""
        if self._redis is None:
            self._redis = aioredis.Redis.from_url(
                REDIS_DATASET_URL, decode_responses=False
            )
        return self._redis

    # ── Per-source Parquet caching (new) ──────────────────────────

    async def _cache_df(self, source: DataSource, df: pd.DataFrame, ttl: int) -> None:
        """Serialize df to Parquet bytes and store in Redis with TTL."""
        try:
            redis_conn = await self._get_redis_connection()
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, compression='snappy')
            key = f"dataset:{source.cache_key}"
            await redis_conn.setex(key, ttl, buf.getvalue())
        except Exception as exc:
            self.logger.warning("Failed to cache dataset '%s': %s", source.cache_key, exc)

    async def _get_cached_df(self, source: DataSource) -> Optional[pd.DataFrame]:
        """Retrieve and deserialize Parquet bytes from Redis."""
        try:
            redis_conn = await self._get_redis_connection()
            key = f"dataset:{source.cache_key}"
            data = await redis_conn.get(key)
            if data is None:
                return None
            return pd.read_parquet(io.BytesIO(data))
        except Exception as exc:
            self.logger.warning("Failed to read cache for '%s': %s", source.cache_key, exc)
            return None

    # ── Materialization ──────────────────────────────────────────

    async def materialize(
        self,
        name: str,
        force_refresh: bool = False,
        **params,
    ) -> pd.DataFrame:
        """On-demand materialization with Redis Parquet caching.

        Flow for sources WITHOUT built-in caching (SQL, Table, InMemory):
          1. If already loaded and not force_refresh → return in-memory _df.
          2. Check Redis: hit → deserialize Parquet → set entry._df → return.
          3. Miss → entry.materialize(**params) → _cache_df → return.

        Flow for sources WITH built-in caching (QuerySlugSource, MultiQuerySlugSource):
          1. If already loaded and not force_refresh → return in-memory _df.
          2. Delegate entirely to source.fetch(force_refresh=force_refresh, **params).
             The source bubbles force_refresh → QS ``refresh`` condition so QS
             handles its own cache invalidation. DatasetManager does NOT wrap
             these sources in a redundant Redis layer.

        Args:
            name: Dataset name or alias.
            force_refresh: If True, bypass in-memory and any cache; re-fetch from source.
            **params: Passed to source.fetch() (e.g. sql= for TableSource).

        Returns:
            The materialized DataFrame.

        Raises:
            ValueError: If dataset not found.
        """
        resolved = self._resolve_name(name)
        entry = self._datasets.get(resolved)
        if entry is None:
            raise ValueError(f"Dataset '{name}' not found. Available: {list(self._datasets.keys())}")

        # Already in memory and no refresh needed
        if entry.loaded and not force_refresh:
            return entry._df

        # QS-backed sources manage their own cache — skip DatasetManager Redis layer.
        if entry.source.has_builtin_cache:
            df = await entry.materialize(force=True, force_refresh=force_refresh, **params)
            if self.generate_guide:
                self.df_guide = self._generate_dataframe_guide()
            return df

        # Try Redis cache (non-QS sources only, skip if no_cache)
        if not force_refresh and not entry.no_cache:
            cached = await self._get_cached_df(entry.source)
            if cached is not None:
                entry._df = cached
                if self.auto_detect_types:
                    entry._column_types = self.categorize_columns(cached)
                self.logger.debug("Cache hit for dataset '%s'", resolved)
                return cached

        # Fetch from source and store in Redis (skip cache write if no_cache)
        df = await entry.materialize(force=True, **params)
        if not entry.no_cache:
            await self._cache_df(entry.source, df, entry.cache_ttl)

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        return df

    # ── Eviction ─────────────────────────────────────────────────

    def evict(self, name: str) -> str:
        """Release a materialized DataFrame from memory.

        Source reference and schema are retained; dataset can be re-materialized.

        Args:
            name: Dataset name or alias.

        Returns:
            Confirmation message.
        """
        resolved = self._resolve_name(name)
        entry = self._datasets.get(resolved)
        if entry is None:
            return f"Dataset '{name}' not found."
        entry.evict()
        self.logger.debug("Evicted dataset '%s' from memory", resolved)
        return f"Dataset '{resolved}' evicted from memory."

    def evict_all(self) -> str:
        """Release all materialized DataFrames from memory.

        Returns:
            Confirmation message with count.
        """
        count = sum(1 for e in self._datasets.values() if e.loaded)
        for entry in self._datasets.values():
            entry.evict()
        return f"Evicted {count} datasets from memory."

    def evict_table_sources(self) -> int:
        """Evict all loaded TableSource DataFrames from memory.

        Table sources contain query-specific data (different columns/filters
        per SQL).  Evicting them between conversation turns forces the LLM
        to call ``fetch_dataset`` again with a fresh SQL appropriate to the
        new question.

        Eagerly-loaded DataFrames (InMemorySource) and QuerySlugSources are
        NOT evicted — they are complete datasets, not query fragments.

        Returns:
            Number of datasets evicted.
        """
        from .sources.table import TableSource

        count = 0
        for name, entry in self._datasets.items():
            if isinstance(entry.source, TableSource) and entry.loaded:
                entry.evict()
                self.logger.debug("Evicted table source '%s'", name)
                count += 1
        if count:
            self._notify_change()
        return count

    def evict_unactive(self) -> str:
        """Release inactive (is_active=False) materialized DataFrames from memory.

        Returns:
            Confirmation message with count.
        """
        count = 0
        for entry in self._datasets.values():
            if not entry.is_active and entry.loaded:
                entry.evict()
                count += 1
        return f"Evicted {count} inactive datasets from memory."

    async def load_data(
        self,
        query: Union[List[str], Dict, str],
        agent_name: str,
        refresh: bool = False,
        cache_expiration: int = 48,
        no_cache: bool = False,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """Deprecated: bulk query-loading helper kept for PandasAgent backward compat.

        For new code use ``add_query()`` + ``materialize()`` instead.
        """
        warnings.warn(
            "load_data() is deprecated. Use add_query() + materialize() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Use external loader (test mock or PandasAgent's internal loader) if set
        if self._query_loader:
            queries_list = [query] if isinstance(query, str) else query
            dfs = await self._query_loader(queries_list)
            for name, df in dfs.items():
                self.add_dataframe(name, df, is_active=True)
            return dfs

        # Fall back to QuerySource
        _qs_mod = lazy_import("querysource.queries.qs", package_name="querysource", extra="db")
        _QS = _qs_mod.QS
        dfs = {}
        queries_list = [query] if isinstance(query, str) else query
        if isinstance(queries_list, list):
            for slug in queries_list:
                try:
                    qy = _QS(slug=slug)
                    df, error = await qy.query(output_format='pandas')
                    if not error and isinstance(df, pd.DataFrame):
                        dfs[slug] = df
                except Exception as exc:
                    self.logger.error("load_data: slug '%s' failed: %s", slug, exc)
        for name, df in dfs.items():
            self.add_dataframe(name, df, is_active=True)
        return dfs
