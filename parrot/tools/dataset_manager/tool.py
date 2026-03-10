"""
DatasetManager: A Toolkit and Data Catalog for PandasAgent.

Provides:
- Dataset catalog with add/remove/activate/deactivate
- Full metadata/EDA capabilities (replaces MetadataTool)
- Column type categorization and metrics guide generation
- Data quality checks (NaN detection, completeness)
- LLM-exposed tools for discovery, metadata retrieval, and management
"""
import io
import re
import warnings
from typing import Callable, Dict, List, Literal, Optional, Any, Tuple, Union
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
    source_type: Literal["dataframe", "query_slug", "sql", "table", "airtable", "smartsheet"] = Field(
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
    """

    def __init__(
        self,
        name: str,
        source: Optional[DataSource] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        auto_detect_types: bool = True,
        cache_ttl: int = 3600,
        # Backward-compat kwargs — wrap in appropriate source if no source given
        df: Optional[pd.DataFrame] = None,
        query_slug: Optional[str] = None,
    ) -> None:
        self.name = name
        self.metadata = metadata or {}
        self.is_active = is_active
        self.auto_detect_types = auto_detect_types
        self.cache_ttl = cache_ttl

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

        # Internal state
        self._df: Optional[pd.DataFrame] = df  # pre-load when df provided directly
        self._column_types: Optional[Dict[str, str]] = None
        if df is not None and auto_detect_types:
            self._column_types = DatasetManager.categorize_columns(df)

    # ─────────────────────────────────────────────────────────────
    # Source-based lifecycle
    # ─────────────────────────────────────────────────────────────

    async def materialize(self, force: bool = False, **params) -> pd.DataFrame:
        """Fetch data from source if not already loaded (or if force=True).

        Args:
            force: If True, re-fetch even if _df is already populated.
            **params: Passed through to source.fetch() (e.g. sql=, conditions=).

        Returns:
            The loaded DataFrame.
        """
        if self._df is None or force:
            self._df = await self.source.fetch(**params)
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
        """Column names. Falls back to source schema (TableSource) when not loaded."""
        if self._df is not None:
            return self._df.columns.tolist()
        # Schema from prefetch (available for TableSource before materialization)
        schema = getattr(self.source, '_schema', {})
        return list(schema.keys())

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
        When not loaded, derives from source schema (TableSource prefetch).
        """
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

        _source_type_map: Dict[type, str] = {
            InMemorySource: "dataframe",
            QuerySlugSource: "query_slug",
            MultiQuerySlugSource: "query_slug",
            SQLQuerySource: "sql",
            TableSource: "table",
            AirtableSource: "airtable",
            SmartsheetSource: "smartsheet",
        }
        source_type = _source_type_map.get(type(self.source), "dataframe")

        # column_types: use post-fetch types if loaded, else source _schema for TableSource
        col_types = self._column_types
        if col_types is None:
            raw_schema = getattr(self.source, '_schema', {})
            col_types = raw_schema if raw_schema else None

        return DatasetInfo(
            name=self.name,
            alias=alias,
            description=self.metadata.get("description", ""),
            source_type=source_type,
            source_description=self.source.describe(),
            columns=self.columns,
            column_types=col_types,
            shape=self.shape if self.loaded else None,
            loaded=self.loaded,
            memory_usage_mb=round(self.memory_usage_mb, 2),
            null_count=self.null_count,
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

    exclude_tools = ("setup", "add_dataset")

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

    def _notify_change(self) -> None:
        """Invoke the on-change callback if registered."""
        if self._on_change_callback is not None:
            try:
                self._on_change_callback()
            except Exception as exc:
                self.logger.warning("on_change callback failed: %s", exc)

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

    async def add_dataset(
        self,
        name: str,
        *,
        query_slug: Optional[str] = None,
        query: Optional[str] = None,
        table: Optional[str] = None,
        dataframe: Optional[pd.DataFrame] = None,
        driver: Optional[str] = None,
        dsn: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        sql: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
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
            metadata: Optional metadata dict (description, etc.).
            is_active: Whether the dataset is active (default ``True``).

        Returns:
            Confirmation message with shape.

        Raises:
            ValueError: If the source arguments are ambiguous or incomplete.
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
            source = QuerySlugSource(slug=query_slug)
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
            )
            fetch_sql = sql or f"SELECT * FROM {table}"
            df = await source.fetch(sql=fetch_sql)

        return self.add_dataframe(
            name=name, df=df, metadata=metadata, is_active=is_active,
        )

    def add_dataframe(
        self,
        name: str,
        df: pd.DataFrame,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
    ) -> str:
        """
        Add a DataFrame to the catalog.

        Datasets are ACTIVE by default when added, meaning they are
        immediately available for analysis.

        Args:
            name: Name/identifier for the dataset
            df: pandas DataFrame to add
            metadata: Optional metadata dictionary with description, column info
            is_active: Whether dataset is active (default True)

        Returns:
            Confirmation message
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df must be a pandas DataFrame")

        from .sources.memory import InMemorySource

        source = InMemorySource(df=df, name=name)
        entry = DatasetEntry(
            name=name,
            source=source,
            metadata=metadata or {},
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
        )
        # Pre-load: InMemorySource has data immediately
        entry._df = df
        if self.auto_detect_types:
            entry._column_types = self.categorize_columns(df)
        self._datasets[name] = entry

        # Regenerate guide if enabled
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        self.logger.debug("Dataset '%s' added (%d rows × %d cols)", name, df.shape[0], df.shape[1])
        return f"Dataset '{name}' added ({df.shape[0]} rows × {df.shape[1]} cols)"

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
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
    ) -> str:
        """
        Register a query slug for lazy loading.

        Args:
            name: Name/identifier for the dataset
            query_slug: QuerySource slug to load data from
            metadata: Optional metadata dictionary
            is_active: Whether dataset is active (default True)

        Returns:
            Confirmation message
        """
        from .sources.query_slug import QuerySlugSource

        source = QuerySlugSource(slug=query_slug)
        entry = DatasetEntry(
            name=name,
            source=source,
            metadata=metadata or {},
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
        )
        self._datasets[name] = entry
        self.logger.debug("Query '%s' registered (slug: %s)", name, query_slug)
        return f"Query '{name}' registered (slug: {query_slug})"

    async def add_table_source(
        self,
        name: str,
        table: str,
        driver: str,
        dsn: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        strict_schema: bool = True,
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

        Returns:
            Confirmation message with column count and driver.
        """
        from .sources.table import TableSource

        source = TableSource(
            table=table,
            driver=driver,
            dsn=dsn,
            credentials=credentials,
            strict_schema=strict_schema,
        )
        await source.prefetch_schema()  # raises on failure if strict_schema=True
        entry = DatasetEntry(
            name=name,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
        )
        self._datasets[name] = entry

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        n_cols = len(source._schema)
        self.logger.debug("Table source '%s' registered (%d columns, %s)", name, n_cols, driver)
        return f"Table source '{name}' registered ({n_cols} columns, {driver})."

    def add_sql_source(
        self,
        name: str,
        sql: str,
        driver: str,
        dsn: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
    ) -> str:
        """Register a parameterized SQL source. Sync — no prefetch needed.

        The SQL may use {param} placeholders injected at fetch time.

        Args:
            name: Name/identifier for the dataset.
            sql: SQL template with optional {param} placeholders.
            driver: AsyncDB driver name, e.g. "pg", "bigquery", "mysql".
            dsn: Optional DSN string.
            metadata: Optional metadata dict.
            cache_ttl: Redis cache TTL in seconds (default 3600).

        Returns:
            Confirmation message.
        """
        from .sources.sql import SQLQuerySource

        source = SQLQuerySource(sql=sql, driver=driver, dsn=dsn)
        entry = DatasetEntry(
            name=name,
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
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
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        fetch_on_create: bool = True,
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
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
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
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        fetch_on_create: bool = True,
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
            source=source,
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
        )
        self._datasets[name] = entry

        if fetch_on_create:
            await self.materialize(name, force_refresh=True)

        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        self.logger.debug("Smartsheet source '%s' registered (%s)", name, sheet_id)
        return f"Smartsheet source '{name}' registered ({sheet_id})."

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
                "missing_percentage": round(float(missing[col] / len(df) * 100), 2) if len(df) > 0 else 0.0
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
            "null_percentage": round(float(series.isnull().sum() / len(series) * 100), 2) if len(series) > 0 else 0.0
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
    # LLM-Exposed Tools (Async methods become tools via AbstractToolkit)
    # ─────────────────────────────────────────────────────────────

    async def list_available(self) -> List[Dict[str, Any]]:
        """
        List all datasets in the catalog.

        Returns a list of dataset information including name, alias, shape,
        columns, active status, null count, column types, and whether data is loaded.
        """
        alias_map = self._get_alias_map()
        return [
            entry.to_info(alias=alias_map.get(name)).model_dump()
            for name, entry in self._datasets.items()
        ]

    async def get_active(self) -> List[str]:
        """
        Get the names of all currently active datasets.

        Active datasets are available for analysis in python_repl_pandas.
        """
        return [
            name for name, entry in self._datasets.items()
            if entry.is_active
        ]

    async def get_metadata(
        self,
        name: str,
        include_eda: bool = True,
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
                    f"using the columns below. Write targeted queries with WHERE, "
                    f"GROUP BY, or LIMIT — avoid SELECT * on large tables."
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
            "description": entry.metadata.get("description", ""),
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
        df = entry.df

        return {
            "name": resolved_name,
            "alias": alias_map.get(resolved_name),
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
        Store a computed DataFrame into the catalog.

        Use this when you have created a new DataFrame from operations
        (e.g., filtering, aggregation, joins) and want to make it
        available for future analysis.

        NOTE: This tool is used to REGISTER a DataFrame that already exists
        in the python_repl_pandas execution environment. After computation,
        call this to add the resulting DataFrame to the catalog.

        Args:
            name: Name for the new dataset
            description: Short description of what this dataset contains

        Returns:
            Confirmation message
        """
        # This tool is meant to be called by the LLM after creating a DataFrame
        # The actual DataFrame binding happens in PandasAgent via callback
        # For now, we return instructions for proper use
        return (
            f"To store DataFrame '{name}':\n"
            f"1. First create the DataFrame in python_repl_pandas\n"
            f"2. The agent will automatically register it when you use this tool\n"
            f"Description: {description or 'Not provided'}"
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

        After successful materialization, returns the dataset schema, EDA summary, and
        sample rows so you can immediately answer questions without additional tool calls.

        Args:
            name: Dataset name or alias.
            sql: SQL query string (required for TableSource).
            conditions: Dict of {param: value} pairs for SQLQuerySource templates.
            force_refresh: If True, bypass caches and re-fetch from source.

        Returns:
            Dict with status, shape, column schema, EDA summary, sample rows, and warnings.
        """
        params: Dict[str, Any] = {}
        if sql is not None:
            params['sql'] = sql
        if conditions:
            params.update(conditions)

        try:
            df = await self.materialize(name, force_refresh=force_refresh, **params)
        except Exception as exc:
            return {"error": f"Error fetching dataset '{name}': {exc}"}

        resolved = self._resolve_name(name)
        nan_warnings = self.check_dataframes_for_nans([resolved])

        # Build sample rows — convert numpy/pandas types to plain Python for serialization
        try:
            sample_df = df.head(10)
            sample_records = []
            for record in sample_df.to_dict(orient='records'):
                clean = {}
                for k, v in record.items():
                    if hasattr(v, 'item'):  # numpy scalar
                        v = v.item()
                    elif v is None or (isinstance(v, float) and v != v):  # NaN
                        v = None
                    clean[str(k)] = v
                sample_records.append(clean)
        except Exception:
            sample_records = []

        result: Dict[str, Any] = {
            "status": "materialized",
            "dataset": resolved,
            "shape": {"rows": df.shape[0], "columns": df.shape[1]},
            "column_schema": {
                str(col): str(dtype) for col, dtype in df.dtypes.items()
            },
            "eda_summary": self._generate_eda_summary(df),
            "sample_rows": sample_records,
        }
        if nan_warnings:
            result["warnings"] = nan_warnings
        self._notify_change()
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
            "## Available Datasets:",
        ]

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

        # Try Redis cache (non-QS sources only)
        if not force_refresh:
            cached = await self._get_cached_df(entry.source)
            if cached is not None:
                entry._df = cached
                if self.auto_detect_types:
                    entry._column_types = self.categorize_columns(cached)
                self.logger.debug("Cache hit for dataset '%s'", resolved)
                return cached

        # Fetch from source and store in Redis
        df = await entry.materialize(force=True, **params)
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
        from querysource.queries.qs import QS as _QS  # type: ignore[import]
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

