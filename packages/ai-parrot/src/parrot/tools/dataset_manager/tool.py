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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Any, Set, Tuple, Union, TYPE_CHECKING
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

# Runtime import (not TYPE_CHECKING): these contracts are referenced as string
# forward refs in tool method signatures (e.g. spatial_filter). Because this
# module uses `from __future__ import annotations`, ToolkitTool resolves those
# annotations via get_type_hints() at runtime — the names must exist in module
# globals or schema generation fails (NameError → empty args_schema). The
# contracts module is I/O-free (typing + pydantic only), so no circular import.
from .spatial.contracts import SpatialFilterSpec, SpatialResult, SpatialLayerResult

# FEAT-225: filtering contracts are I/O-free Pydantic models; safe to import at
# module level (no circular import).
from .filtering.contracts import FilterDefinition, FilterResult

if TYPE_CHECKING:
    from ...auth.dataset_guard import DatasetPolicyGuard
    from ...auth.dataplane_guard import DataPlanePolicyGuard
    from ...auth.permission import PermissionContext
    from ...auth.resolver import AbstractPermissionResolver

# _pctx_var is the module-level ContextVar that isolates the per-call
# PermissionContext for each asyncio task on a shared DatasetManager instance.
# Authoritative definition lives in parrot.auth.context to avoid cross-module
# coupling (FEAT-228 code-review fix [4]).  Re-exported here for backward
# compatibility with existing usages in this module and DatabaseQueryTool.
from parrot.auth.context import _pctx_var  # noqa: F401

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

    # Usage guidance — tells the LLM what this dataset CAN and CANNOT do
    usage_do: List[str] = Field(
        default_factory=list,
        description="What this dataset should be used for (e.g. 'Revenue analysis by project')",
    )
    usage_dont: List[str] = Field(
        default_factory=list,
        description="What this dataset should NOT be used for (e.g. 'Do not use for headcount')",
    )


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
        # Usage guidance — DO / DONT directives for the LLM
        usage_guidance: Optional[Dict[str, List[str]]] = None,
        # Protection flag — prevents LLM from overwriting or removing this dataset
        protected: bool = False,
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
        self.protected = protected

        # Usage guidance: {"do": [...], "dont": [...]}
        self.usage_guidance: Dict[str, List[str]] = usage_guidance or {}

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
            usage_do=self.usage_guidance.get("do", []),
            usage_dont=self.usage_guidance.get("dont", []),
        )


@dataclass
class FileEntry:
    """A file loaded into DatasetManager (not a DataFrame).

    Stores structural analysis and per-table markdown for files loaded
    via :meth:`DatasetManager.load_file`.
    """

    name: str
    path: Path
    file_type: str  # "csv" | "excel"
    markdown_content: Dict[str, str]  # table_id -> markdown string
    structural_summary: str  # Human-readable summary for LLM
    analysis: Optional[Any] = None  # Dict[str, SheetAnalysis] for Excel
    metadata: Optional[Dict[str, Any]] = None


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

    tool_prefix: str = "dataset"
    exclude_tools = ("setup", "add_dataset", "list_available")

    #: Universal decision rules for any agent driving a DatasetManager. Injected
    #: into the system prompt via ``get_usage_rules()`` so the LLM commits to one
    #: data path instead of probing the REPL, fetch_dataset and other tools in
    #: turn (a common cause of wasted iterations). Override per-agent by passing
    #: ``usage_rules=`` to the constructor.
    DEFAULT_USAGE_RULES: str = (
        "## How to work with datasets (read before calling any data tool)\n"
        "\n"
        "1. **Loaded DataFrames are ready now.** Datasets shown as *loaded* already "
        "exist in the `python_repl_pandas` environment under their name and `dfN` "
        "alias — use them directly (e.g. `df1.groupby(...)`). Never re-fetch a "
        "loaded dataset.\n"
        "2. **Aggregate tables in SQL, not pandas.** For a count / sum / ranking / "
        "filter over an *unloaded* table, call `fetch_dataset` with a SQL query that "
        "does the work in the database (`GROUP BY` / `WHERE` / `LIMIT`). Do NOT pull "
        "a whole table into the REPL to aggregate it there.\n"
        "3. **Pick one source and commit.** Read each dataset's description and "
        "`usage_guidance` first, choose the one dataset that fits the question, and "
        "use it. Do not probe several datasets hoping one returns data.\n"
        "4. **Empty datasets hold no data.** A dataset listed with 0 rows must be "
        "populated with `fetch_dataset` before you query it.\n"
        "5. **Inspect, don't guess.** If unsure of columns or grain, call "
        "`get_metadata(name=...)` instead of running trial-and-error code.\n"
    )

    def __init__(
        self,
        df_prefix: str = "df",
        generate_guide: bool = True,
        include_summary_stats: bool = False,
        auto_detect_types: bool = True,
        policy_guard: Optional["DatasetPolicyGuard"] = None,
        dataplane_guard: Optional["DataPlanePolicyGuard"] = None,
        usage_rules: Optional[str] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        # None → fall back to DEFAULT_USAGE_RULES; "" disables the block entirely.
        self._usage_rules: Optional[str] = usage_rules
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
        self._file_entries: Dict[str, FileEntry] = {}
        self._artifacts: List[Dict[str, Any]] = []
        # PBAC dataset-level policy enforcement (FEAT-151).
        # None → no enforcement (opt-in backwards compat).
        self._policy_guard: Optional["DatasetPolicyGuard"] = policy_guard
        # FEAT-228: data-plane authorization guard (L2).
        # Wraps every DataSource in AuthorizingDataSource at registration time.
        # None → no enforcement (opt-in backwards compat).
        self._dataplane_guard: Optional["DataPlanePolicyGuard"] = dataplane_guard
        # FEAT-225: instance-scoped filter definition store.
        # Keyed by FilterDefinition.name.  Never shared across instances.
        self._filter_defs: Dict[str, FilterDefinition] = {}
        # FEAT-225: per-instance TTL-free cache for get_filter_values results.
        # Keyed by filter name. Invalidated via clear_filter_values_cache().
        self._filter_values_cache: Dict[str, List[Any]] = {}
        # Per-call permission context is stored in the module-level _pctx_var
        # ContextVar (set by _pre_execute, read by _get_current_pctx).
        # Using a ContextVar instead of an instance attribute isolates concurrent
        # requests on a shared DatasetManager from cross-contaminating contexts.

    # ── FEAT-228: Data-plane authorization factory ────────────────

    def _make_source(self, source: "DataSource") -> "DataSource":
        """Wrap a DataSource in AuthorizingDataSource when a dataplane guard is set.

        This is the Option-D factory (Spec §2): every source that touches the
        network / storage passes through the guard's enforcement chain before
        its ``fetch()`` is called.

        ``InMemorySource`` is intentionally excluded — it has no driver and
        therefore no authorization surface.

        Args:
            source: Raw :class:`~parrot.tools.dataset_manager.sources.base.DataSource`
                instance to (optionally) wrap.

        Returns:
            The original source when no ``dataplane_guard`` is configured, or
            when the source is an ``InMemorySource``.  Otherwise returns an
            :class:`~parrot.tools.dataset_manager.sources.authorizing.AuthorizingDataSource`
            wrapping the original.
        """
        if self._dataplane_guard is None:
            return source
        from .sources.memory import InMemorySource
        if isinstance(source, InMemorySource):
            return source
        from .sources.authorizing import AuthorizingDataSource
        return AuthorizingDataSource(
            inner=source,
            guard=self._dataplane_guard,
            pctx_provider=lambda: _pctx_var.get(None),
        )

    def set_on_change(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked after dataset mutations (fetch, activate, deactivate)."""
        self._on_change_callback = callback

    def set_repl_locals_getter(self, getter: Callable[[], Dict[str, Any]]) -> None:
        """Register a callable that returns the REPL local variables.

        Used by ``store_dataframe`` to look up a computed DataFrame by name
        from the python_repl_pandas execution environment.
        """
        self._repl_locals_getter = getter

    def drain_artifacts(self) -> List[Dict[str, Any]]:
        """Return accumulated artifacts and clear the internal list.

        Called by the owning agent after a completion round to transfer
        artifacts (e.g. executed SQL queries) onto the AIMessage.
        """
        artifacts = list(self._artifacts)
        self._artifacts.clear()
        return artifacts

    def _is_protected(self, name: str) -> bool:
        """Check if a dataset name is protected against LLM overwrites."""
        resolved = self._resolve_name(name)
        if resolved in self._datasets:
            return self._datasets[resolved].protected
        return False

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
        """Apply dictionary-based filters to a DataFrame.

        Each key is a column name. Each value is one of:

        - A **scalar**: rows where ``column == value`` are kept (``eq``).
        - A **list/tuple/set**: rows where column value is in the collection
          (``in`` / ``isin``).
        - A :class:`FilterCondition` instance: the condition's ``op`` field
          controls the comparison:

          - ``eq``     → ``column == value``
          - ``ne``     → ``column != value``
          - ``in``     → ``column.isin(value)``
          - ``not_in`` → ``~column.isin(value)``
          - ``range``  → ``column.between(min, max)``
            (value must be ``{"min": …, "max": …}`` or a 2-element sequence)

        All conditions are ANDed together.

        Args:
            df: The DataFrame to filter.
            filter_dict: Mapping of column names to required values or
                ``FilterCondition`` instances.

        Returns:
            Filtered DataFrame with reset index.

        Raises:
            ValueError: If a filter column is not found in the DataFrame or
                if a ``FilterCondition`` carries an unsupported operator.
        """
        from .filtering.compiler import FilterCompiler
        from .filtering.contracts import FilterCondition as _FC

        compiler = FilterCompiler()
        mask = pd.Series(True, index=df.index)

        for col, value in filter_dict.items():
            if col not in df.columns:
                raise ValueError(
                    f"Filter column '{col}' not found in DataFrame. "
                    f"Available: {list(df.columns)}"
                )
            if isinstance(value, _FC):
                # FEAT-225: delegate to FilterCompiler for structured conditions.
                mask &= compiler.compile_pandas(df, col, value)
            elif isinstance(value, (list, tuple, set)):
                # Legacy: list/tuple/set → isin (eq/in semantics)
                mask &= df[col].isin(value)
            else:
                # Legacy: scalar → equality
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
        usage_guidance: Optional[Dict[str, List[str]]] = None,
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
            source = self._make_source(QuerySlugSource(
                slug=query_slug, permanent_filter=permanent_filter,
            ))
            params = dict(conditions) if conditions else {}
            df = await source.fetch(**params)

        elif query is not None:
            if not driver:
                raise ValueError("driver is required when using query=")
            from .sources.sql import SQLQuerySource
            source = self._make_source(SQLQuerySource(
                sql=query,
                driver=driver,
                dsn=dsn,
                credentials=credentials,
            ))
            params = dict(conditions) if conditions else {}
            df = await source.fetch(**params)

        elif table is not None:
            if not driver:
                raise ValueError("driver is required when using table=")
            from .sources.table import TableSource
            source = self._make_source(TableSource(
                table=table,
                driver=driver,
                dsn=dsn,
                credentials=credentials,
                strict_schema=False,
                permanent_filter=permanent_filter,
            ))
            fetch_sql = sql or f"SELECT * FROM {table}"
            df = await source.fetch(sql=fetch_sql)

        if filter:
            df = self._apply_filter(df, filter)

        return self.add_dataframe(
            name=name, df=df, description=description, metadata=metadata,
            is_active=is_active, computed_columns=computed_columns,
            usage_guidance=usage_guidance,
        )

    def add_dataframe(
        self,
        name: str,
        df: pd.DataFrame,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        computed_columns: Optional[List[Any]] = None,
        usage_guidance: Optional[Dict[str, List[str]]] = None,
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
            usage_guidance: Optional dict with ``do`` and ``dont`` lists that
                tell the LLM what this dataset should (and should not) be used
                for.  Example::

                    {"do": ["Revenue analysis by project"],
                     "dont": ["Do not use for headcount queries"]}

        Returns:
            Confirmation message
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df must be a pandas DataFrame")

        # Prevent overwriting protected (core) datasets
        if self._is_protected(name):
            raise ValueError(
                f"Cannot overwrite protected dataset '{name}'. "
                f"Use a different name for this DataFrame."
            )

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
            usage_guidance=usage_guidance,
        )
        # Pre-load: InMemorySource has data immediately
        entry._df = df
        # Apply computed columns before type detection
        if entry._computed_columns:
            entry._apply_computed_columns()
        if self.auto_detect_types:
            entry._column_types = self.categorize_columns(entry._df)
        self._datasets[name] = entry

        # Evict any cached filter-values entries for this dataset name so that
        # a subsequent get_filter_values call re-scans the new data.
        self.clear_filter_values_cache(name)

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

    # ─────────────────────────────────────────────────────────────
    # File Loading (structural analysis, markdown-first)
    # ─────────────────────────────────────────────────────────────

    async def load_file(
        self,
        name: str,
        path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
        max_rows_per_table: int = 200,
        output_format: str = "markdown",
    ) -> str:
        """Load a CSV or Excel file for LLM context.

        Unlike add_dataframe_from_file() which converts to DataFrame,
        this method preserves the file's structural layout and produces
        clean markdown that can be passed directly to the LLM.

        Args:
            name: Identifier for the file in the catalog.
            path: Path to CSV or Excel file.
            metadata: Optional metadata.
            max_rows_per_table: Max rows per extracted table (token budget).
            output_format: 'markdown', 'csv', or 'json'.

        Returns:
            Structural summary string.
        """
        path = Path(path)
        file_size = path.stat().st_size
        if file_size > 100 * 1024 * 1024:  # 100 MB
            self.logger.warning(
                "File '%s' is %.1f MB — loading may be slow",
                path.name, file_size / (1024 * 1024),
            )

        extension = path.suffix.lower().lstrip(".")

        if extension == "csv":
            from .csv_reader import csv_to_markdown, csv_to_structural_summary

            markdown = csv_to_markdown(path, max_rows=max_rows_per_table)
            summary = csv_to_structural_summary(path)
            entry = FileEntry(
                name=name,
                path=path,
                file_type="csv",
                markdown_content={"table": markdown},
                structural_summary=summary,
                metadata=metadata,
            )
        elif extension in {"xls", "xlsx", "xlsm", "xlsb"}:
            from .excel_analyzer import ExcelStructureAnalyzer

            analyzer = ExcelStructureAnalyzer(path)
            analysis = analyzer.analyze_workbook()

            # Extract all tables as markdown.
            # Use composite key (sheet::table_id) to avoid collisions
            # across sheets that share the same table numbering.
            markdown_content: Dict[str, str] = {}
            for sheet_name, sheet_analysis in analysis.items():
                for table in sheet_analysis.tables:
                    df = analyzer.extract_table_as_dataframe(
                        sheet_name, table, include_totals=False,
                    )
                    if len(df) > max_rows_per_table:
                        df = df.head(max_rows_per_table)
                    key = f"{sheet_name}::{table.table_id}"
                    markdown_content[key] = df.to_markdown(index=False)

            # Build summary.
            summary_parts = [sa.to_summary() for sa in analysis.values()]
            structural_summary = "\n\n".join(summary_parts)

            entry = FileEntry(
                name=name,
                path=path,
                file_type="excel",
                markdown_content=markdown_content,
                structural_summary=structural_summary,
                analysis=analysis,
                metadata=metadata,
            )
            analyzer.close()
        else:
            raise ValueError(f"Unsupported file type: .{extension}")

        self._file_entries[name] = entry

        # Regenerate guide if enabled.
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        return entry.structural_summary

    async def get_file_context(self, name: str) -> str:
        """Get the full markdown context for a loaded file.

        Args:
            name: File identifier used in load_file().

        Returns:
            All table markdown concatenated with headers.
        """
        if name not in self._file_entries:
            raise KeyError(f"File '{name}' not found in catalog.")
        entry = self._file_entries[name]
        parts: list[str] = [f"# File: {entry.path.name}", ""]
        for table_id, md in entry.markdown_content.items():
            parts.append(f"## {table_id}")
            parts.append(md)
            parts.append("")
        return "\n".join(parts)

    async def get_file_table(self, name: str, table_id: str) -> str:
        """Get markdown for a specific table from a loaded file.

        Args:
            name: File identifier used in load_file().
            table_id: Table ID (e.g. 'T1', 'table').

        Returns:
            Markdown string for the requested table.
        """
        if name not in self._file_entries:
            raise KeyError(f"File '{name}' not found in catalog.")
        entry = self._file_entries[name]
        if table_id not in entry.markdown_content:
            available = ", ".join(entry.markdown_content.keys())
            raise KeyError(
                f"Table '{table_id}' not found in file '{name}'. "
                f"Available tables: {available}"
            )
        return entry.markdown_content[table_id]

    def add_source(
        self,
        source,
        capability_registry=None,
    ) -> str:
        """Register a pre-built DataSource instance with optional CapabilityRegistry hook.

        Provides a generic entry point for registering any ``DataSource``
        subclass directly, with automatic capability indexing when a registry
        is supplied.  The source is wrapped in a ``DatasetEntry`` and stored
        under the source's ``name`` attribute (or ``cache_key`` as fallback).

        Args:
            source: A DataSource subclass instance to register.  Should have a
                ``name`` attribute; ``cache_key`` is used as the fallback key.
            capability_registry: Optional ``CapabilityRegistry``. When provided,
                calls ``registry.register_from_datasource(source)`` so the
                source is discoverable by the intent router.

        Returns:
            Confirmation message string.

        Raises:
            ValueError: If source does not have a ``cache_key`` property.
        """
        if not hasattr(source, 'cache_key'):
            raise ValueError(
                f"DataSource {source!r} must implement 'cache_key' property."
            )
        name = getattr(source, 'name', None) or source.cache_key
        description = None
        try:
            description = source.describe()
        except Exception:  # noqa: BLE001
            pass
        entry = DatasetEntry(
            name=name,
            description=description,
            source=self._make_source(source),
            metadata=getattr(source, 'routing_meta', {}) or {},
            auto_detect_types=self.auto_detect_types,
            protected=True,
        )
        self._datasets[name] = entry
        if capability_registry is not None:
            try:
                capability_registry.register_from_datasource(source)
            except Exception:  # noqa: BLE001
                pass
        self.logger.debug("DataSource '%s' registered via add_source()", name)
        return f"DataSource '{name}' registered."

    def add_query(
        self,
        name: str,
        query_slug: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
        query_filter: Optional[Dict[str, Any]] = None,
        computed_columns: Optional[List[Any]] = None,
        usage_guidance: Optional[Dict[str, List[str]]] = None,
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
            query_filter: Alias for ``permanent_filter``. When both are
                provided, ``permanent_filter`` takes precedence.
            computed_columns: Optional list of ``ComputedColumnDef`` objects
                applied post-materialization.
            usage_guidance: Optional dict with ``do`` and ``dont`` lists that
                tell the LLM what this dataset should (and should not) be used
                for.

        Returns:
            Confirmation message.
        """
        from .sources.query_slug import QuerySlugSource

        resolved_filter = permanent_filter if permanent_filter is not None else query_filter
        source = QuerySlugSource(slug=query_slug, permanent_filter=resolved_filter)
        entry = DatasetEntry(
            name=name,
            description=description,
            source=self._make_source(source),
            metadata=metadata or {},
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            usage_guidance=usage_guidance,
            protected=True,
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
        query_filter: Optional[Dict[str, Any]] = None,
        allowed_columns: Optional[List[str]] = None,
        no_cache: bool = False,
        computed_columns: Optional[List[Any]] = None,
        usage_guidance: Optional[Dict[str, List[str]]] = None,
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
            query_filter: Alias for ``permanent_filter``. When both are
                provided, ``permanent_filter`` takes precedence.
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

        # Resolve filter alias: ``query_filter`` is a shorthand for ``permanent_filter``
        resolved_filter = permanent_filter if permanent_filter is not None else query_filter

        source = TableSource(
            table=table,
            driver=driver,
            dsn=dsn,
            credentials=credentials,
            strict_schema=strict_schema,
            permanent_filter=resolved_filter,
            allowed_columns=allowed_columns,
        )
        await source.prefetch_schema()  # raises on failure if strict_schema=True
        await source.prefetch_row_count()  # estimate row count for size warnings
        entry = DatasetEntry(
            name=name,
            description=description,
            source=self._make_source(source),
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            no_cache=no_cache,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            usage_guidance=usage_guidance,
            protected=True,
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
        usage_guidance: Optional[Dict[str, List[str]]] = None,
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
            source=self._make_source(source),
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            usage_guidance=usage_guidance,
            protected=True,
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
            source=self._make_source(source),
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            protected=True,
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
            source=self._make_source(source),
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            protected=True,
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
            source=self._make_source(source),
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            no_cache=no_cache,
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            protected=True,
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
            source=self._make_source(source),
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            no_cache=no_cache,
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            protected=True,
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
            source=self._make_source(source),
            metadata=metadata or {},
            cache_ttl=cache_ttl,
            no_cache=no_cache,
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            protected=True,
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
            source=self._make_source(source),
            metadata=metadata or {},
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
            computed_columns=computed_columns,
            protected=True,
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
    # PBAC Policy Enforcement (FEAT-151)
    # ─────────────────────────────────────────────────────────────

    def _get_current_pctx(self) -> Optional["PermissionContext"]:
        """Return the per-call PermissionContext for the current asyncio task.

        Reads from the module-level ``_pctx_var`` ContextVar, which is set by
        ``_pre_execute`` when the toolkit dispatch mechanism invokes a tool.
        Each asyncio task has its own copy of the ContextVar, so concurrent
        requests on a shared ``DatasetManager`` instance cannot cross-contaminate
        each other's permission contexts.

        Returns:
            ``PermissionContext`` for the current tool call, or ``None`` when
            no permission context is available (e.g., direct method invocation
            outside the toolkit dispatch path).
        """
        return _pctx_var.get()

    async def _filter_dataset_info_columns(
        self,
        pctx: Optional["PermissionContext"],
        info: DatasetInfo,
    ) -> DatasetInfo:
        """Filter columns in a ``DatasetInfo`` object via the policy guard.

        Trims ``info.columns`` and ``info.column_types`` in lockstep — the two
        fields are always filtered together so the model stays consistent.
        Drop-silent: the caller MUST NOT surface any indication that columns
        were hidden.

        Args:
            pctx: Per-call permission context. If ``None``, no filtering is
                applied.
            info: The ``DatasetInfo`` to filter.

        Returns:
            A new ``DatasetInfo`` instance with only the allowed columns, or
            the original ``info`` when no guard is configured or ``pctx`` is
            missing.
        """
        if not self._policy_guard or not pctx:
            return info
        allowed = await self._policy_guard.filter_columns(
            pctx, info.name, info.columns
        )
        if allowed == info.columns:
            return info  # no change
        allowed_set: Set[str] = set(allowed)
        col_types = info.column_types
        return info.model_copy(update={
            "columns": allowed,
            "column_types": (
                {k: v for k, v in col_types.items() if k in allowed_set}
                if col_types is not None
                else None
            ),
        })

    async def get_tools_filtered(
        self,
        permission_context: "PermissionContext",
        resolver: "AbstractPermissionResolver",
    ) -> List:
        """Filter toolkit tools by resolver and then by dataset policy.

        Delegates to ``super().get_tools_filtered()`` for the standard
        tool-level PBAC pass, then consults ``DatasetPolicyGuard.filter_datasets``
        to compute the set of accessible datasets.  Tools whose associated
        dataset name is denied are excluded; generic tools (no specific dataset
        association) are always kept.

        When ``self._policy_guard is None``, returns the base resolver result
        unchanged (opt-in backwards compat).

        Args:
            permission_context: User context for permission filtering.
            resolver: Permission resolver for the standard tool-level pass.

        Returns:
            Filtered list of ``AbstractTool`` instances.
        """
        tools = await super().get_tools_filtered(permission_context, resolver)
        if not self._policy_guard:
            return tools
        # Compute the accessible datasets for this user (used for per-dataset
        # tool registration in future; keeps all generic tools for now).
        allowed_datasets: Set[str] = await self._policy_guard.filter_datasets(
            permission_context, list(self._datasets.keys())
        )
        # All current DatasetManager tools are generic (they take 'name' as a
        # runtime parameter, not bound to a specific dataset).  Return all
        # tools whose optional dataset association is either None (generic) or
        # in the allowed set.
        def _tool_dataset_name(tool) -> Optional[str]:
            """Dataset name bound to a specific tool, or None for generic tools."""
            # Future: per-dataset tool registration would set a _dataset_name
            # attribute on the tool at generation time.
            return getattr(tool, "_dataset_name", None)

        return [
            t for t in tools
            if _tool_dataset_name(t) is None or _tool_dataset_name(t) in allowed_datasets
        ]

    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
        """PBAC Layer-2 per-call enforcement hook.

        Called by ``ToolkitTool._execute`` before invoking the bound method.
        Stores the per-call ``PermissionContext`` for downstream use and — when
        ``policy_guard`` is configured — performs a defence-in-depth dataset
        access check for tools that take a ``name`` argument.

        Failure mode: raises ``AuthorizationRequired`` when
        ``can_read_dataset()`` returns ``False``.  This exception propagates
        through ``AbstractTool.execute`` (which lets ``AuthorizationRequired``
        bubble up) and is converted into a structured forbidden response by
        ``ToolManager``.

        Args:
            tool_name: Name of the tool about to be executed.
            **kwargs: Tool arguments, including ``_permission_context`` injected
                by ``ToolkitTool._execute``.
        """
        # Store in the module-level ContextVar so concurrent tasks on this shared
        # instance each see their own context (not another request's context).
        # Save the returned token so _post_execute can reset the ContextVar to
        # its previous value after the call, preventing context leakage.
        import asyncio

        pctx = kwargs.get("_permission_context")
        token = _pctx_var.set(pctx)
        task = asyncio.current_task()
        if task is not None:
            if not hasattr(self, "_pctx_tokens"):
                self._pctx_tokens: Dict[int, Any] = {}
            self._pctx_tokens[id(task)] = token

        if not self._policy_guard or not pctx:
            return

        # Perform the dataset-level check only for tools that take a dataset name.
        # The 'name' kwarg is the dataset identifier for fetch_dataset, get_metadata,
        # activate, deactivate, etc.
        dataset_name = kwargs.get("name")
        if dataset_name is None:
            return

        # Resolve the name (handles aliases) so the policy check uses the canonical name.
        try:
            resolved = self._resolve_name(str(dataset_name))
        except Exception:
            resolved = str(dataset_name)

        allowed = await self._policy_guard.can_read_dataset(pctx, resolved)
        if not allowed:
            from ...auth.exceptions import AuthorizationRequired
            _user_id = (
                getattr(pctx.session, "user_id", "<unknown>")
                if pctx.session is not None
                else "<unknown>"
            )
            raise AuthorizationRequired(
                tool_name=tool_name,
                message=(
                    f"Access to dataset '{resolved}' denied by PBAC policy "
                    f"for user '{_user_id}' (Layer-2 defence-in-depth)."
                ),
            )

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:
        """Reset the ContextVar token after tool execution.

        Resets ``_pctx_var`` to its value before ``_pre_execute`` ran.  This
        prevents a stale ``PermissionContext`` from leaking into subsequent
        calls if the ContextVar is inspected outside of the normal
        ``_pre_execute`` → tool → ``_post_execute`` lifecycle.

        Args:
            tool_name: Name of the tool that just executed (unused).
            result: Raw result from the bound method.
            **kwargs: Tool arguments (unused here).

        Returns:
            The unchanged ``result``.
        """
        import asyncio

        task = asyncio.current_task()
        if task is not None and hasattr(self, "_pctx_tokens"):
            token = self._pctx_tokens.pop(id(task), None)
            if token is not None:
                _pctx_var.reset(token)
        return result

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
                        f"CRITICAL: You MUST use GROUP BY with AVG/SUM/COUNT "
                        f"in your SQL for any question about averages, totals, "
                        f"rankings, or time-period summaries. NEVER fetch all "
                        f"rows to aggregate in pandas — the database handles "
                        f"aggregation far more efficiently."
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
        # PBAC: filter out denied datasets (drop-silent)
        pctx = self._get_current_pctx()
        if self._policy_guard and pctx and result:
            allowed_names: Set[str] = await self._policy_guard.filter_datasets(
                pctx, [r["name"] for r in result]
            )
            result = [r for r in result if r["name"] in allowed_names]
        return result

    async def list_available(self) -> List[Dict[str, Any]]:
        """Alias for list_datasets (backward compatibility)."""
        return await self.list_datasets()

    async def get_active(self) -> List[str]:
        """
        Get the names of all currently active datasets.

        Active datasets are available for analysis in python_repl_pandas.
        """
        names = [
            name for name, entry in self._datasets.items()
            if entry.is_active
        ]
        # PBAC: filter out denied datasets (drop-silent)
        pctx = self._get_current_pctx()
        if self._policy_guard and pctx and names:
            allowed: Set[str] = await self._policy_guard.filter_datasets(pctx, names)
            names = [n for n in names if n in allowed]
        return names

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
            # PBAC: filter columns in the unloaded schema (drop-silent)
            pctx_unloaded = self._get_current_pctx()
            if self._policy_guard and pctx_unloaded and info.columns:
                info = await self._filter_dataset_info_columns(pctx_unloaded, info)
                if "columns" in response:
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

        # PBAC: filter columns in the loaded metadata (drop-silent)
        pctx_loaded = self._get_current_pctx()
        if self._policy_guard and pctx_loaded:
            _full_info = entry.to_info()
            _filtered_info = await self._filter_dataset_info_columns(pctx_loaded, _full_info)
            if set(_filtered_info.columns) != set(_full_info.columns):
                _allowed_set: Set[str] = set(_filtered_info.columns)
                # Filter _column_metadata dict (col → {description, dtype, ...})
                if isinstance(result.get("columns"), dict):
                    result["columns"] = {
                        k: v for k, v in result["columns"].items()
                        if k in _allowed_set
                    }
                # Filter column_types dict in lockstep
                if isinstance(result.get("column_types"), dict):
                    result["column_types"] = {
                        k: v for k, v in result["column_types"].items()
                        if k in _allowed_set
                    }
                # Filter sample_rows records if present
                if "sample_rows" in result:
                    result["sample_rows"] = [
                        {k: v for k, v in row.items() if k in _allowed_set}
                        for row in result["sample_rows"]
                    ]
                # Update shape column count to reflect filtering
                if isinstance(result.get("shape"), dict):
                    result["shape"]["columns"] = len(_allowed_set)

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
        Protected (core) datasets cannot be removed.

        Args:
            name: Dataset name or alias to remove

        Returns:
            Confirmation message
        """
        resolved = self._resolve_name(name)
        if resolved in self._datasets and self._datasets[resolved].protected:
            return (
                f"Cannot remove '{resolved}': this is a protected core dataset. "
                f"Use deactivate_datasets if you want to exclude it from analysis."
            )
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

        # PBAC: drop forbidden columns — drop-silent, same semantics as fetch_dataset.
        pctx_gdf = self._get_current_pctx()
        if self._policy_guard and pctx_gdf:
            _all_cols_gdf = df.columns.tolist()
            _allowed_cols_gdf: list = await self._policy_guard.filter_columns(
                pctx_gdf, resolved_name, _all_cols_gdf
            )
            if set(_allowed_cols_gdf) != set(_all_cols_gdf):
                df = df[_allowed_cols_gdf]

        # Filter column_types to only the visible columns (drop-silent).
        _visible_cols = set(df.columns)
        filtered_col_types = (
            {col: ct for col, ct in entry.column_types.items() if col in _visible_cols}
            if entry.column_types
            else None
        )

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
            "column_types": filtered_col_types,
            "is_active": entry.is_active,
            # Recompute from the visible-column df so the count is consistent.
            "null_count": int(df.isnull().sum().sum()),
            "sample_rows": df.head(3).to_dict(orient='records'),
        }

    async def store_dataframe(
        self,
        name: str,
        description: str = "",
    ) -> str:
        """
        Store a computed DataFrame from python_repl_pandas into the catalog.

        Use this ONLY when the user explicitly asks to save/persist a result
        for reuse in future questions. Storing is NEVER required to answer
        the current question — to return a result, assign it to a variable
        and declare it in `data_variable` instead.

        Do NOT call this for intermediate variables, for one-off answers, or
        for datasets that already exist in the catalog.

        Args:
            name: Variable name as it exists in python_repl_pandas.
            description: Short description of what this dataset contains.

        Returns:
            Confirmation message or error.
        """
        # Check if dataset already exists in the catalog
        resolved = self._resolve_name(name)
        if resolved in self._datasets:
            entry = self._datasets[resolved]
            if entry.protected:
                return (
                    f"Cannot store '{resolved}': a core dataset with that name "
                    f"already exists and is protected. Use a different name."
                )
            if entry.loaded:
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

        **SQL QUERY STRATEGY for TableSource (CRITICAL — READ CAREFULLY):**

        NEVER fetch raw rows to aggregate in Python. ALWAYS push aggregation
        to the database using GROUP BY / COUNT / SUM / AVG / MIN / MAX in SQL.

        DECISION TREE — follow this BEFORE writing your SQL:
        1. Does the question involve averages, totals, counts, or rankings?
           → Write a GROUP BY query. The database handles millions of rows
             efficiently; pandas on the same data wastes memory and time.
        2. Does the question ask for "monthly", "weekly", "daily" summaries?
           → Use DATE_TRUNC + GROUP BY, NOT fetch-all-then-resample.
        3. Do you need a filtered subset? → Use WHERE + LIMIT.
        4. Only fetch individual rows when the question truly requires
           row-level detail (e.g., "show me the raw records for kiosk X").

        EXAMPLES — follow these patterns:
        ✅ CORRECT (monthly averages):
          "SELECT kiosk_id, DATE_TRUNC('month', history_date) AS month,
           AVG(depletion_rate) AS avg_depletion, AVG(fill_rate) AS avg_fill
           FROM schema.daily_summary
           WHERE history_date BETWEEN '2025-01-01' AND '2025-12-31'
           GROUP BY kiosk_id, month ORDER BY month"
        ✅ CORRECT (top N by metric):
          "SELECT kiosk_id, SUM(units) AS total_units
           FROM schema.daily_summary GROUP BY kiosk_id
           ORDER BY total_units DESC LIMIT 20"
        ❌ WRONG (fetches millions of rows then aggregates in pandas):
          "SELECT kiosk_id, history_date, depletion_rate, fill_rate
           FROM schema.daily_summary
           WHERE history_date >= '2025-01-01' AND history_date <= '2025-12-31'"

        The database is orders of magnitude faster at aggregation than pandas.
        A query returning 2000 kiosks × 365 days = 730K rows is ALWAYS wrong
        when the user asked for monthly averages — push that to SQL.

        IMPORTANT: The response includes 'python_variable' and 'python_alias' fields.
        These are the ONLY valid variable names in python_repl_pandas.
        Always use one of these exact names — never modify or invent new names.

        Args:
            name: Dataset name or alias.
            sql: SQL query string (required for TableSource). MUST include
                GROUP BY with aggregate functions (AVG, SUM, COUNT, etc.) when
                the question involves summaries, averages, or rankings.
                NEVER fetch all rows to aggregate in pandas.
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
            # Composites accept a filters dict for per-component filtering.
            # Preserve the caller's force_refresh intent — components use their
            # own caches unless the caller explicitly requests a refresh.
            if conditions:
                params['filters'] = conditions
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
                from .sources.table import dialect_hint
                dhint = dialect_hint(entry.source.driver)
                dhint_line = f"\n  - {dhint}" if dhint else ""
                return {
                    "error": (
                        f"TableSource '{table_name}' requires an explicit 'sql' parameter. "
                        f"Do NOT use SELECT * on large tables.{size_note}"
                    ),
                    "hint": (
                        f"Write a targeted SQL query. Examples:\n"
                        f"  - Aggregation: sql=\"SELECT category, COUNT(*) AS n "
                        f"FROM {table_name} WHERE ... GROUP BY category\"\n"
                        f"  - Filtered: sql=\"SELECT col1, col2 FROM {table_name} "
                        f"WHERE status = 'active' LIMIT 100\"\n"
                        f"  - Inspect schema first: call get_source_schema('{resolved}')"
                        f"{dhint_line}"
                    ),
                }
            # ── Auto-rewrite dataset alias → real table name ──────────
            # The LLM often writes SQL using the dataset alias (e.g.
            # "us_census_data_2023") instead of the real BigQuery table
            # (e.g. "census_data.us_integrated_metrics_2023").  Detect
            # this and silently rewrite before the SQL reaches
            # TableSource.fetch() which would reject it.
            real_table = entry.source.table
            alias_name = resolved  # the dataset alias used in add_table_source
            if alias_name != real_table:
                # Also check original (pre-resolved) name the LLM passed
                _names_to_check = {alias_name}
                if name != resolved:
                    _names_to_check.add(name)
                for _alias in _names_to_check:
                    _alias_pat = re.escape(_alias)
                    if re.search(rf'\b{_alias_pat}\b', sql, re.IGNORECASE):
                        sql = re.sub(
                            rf'\b{_alias_pat}\b',
                            real_table,
                            sql,
                            count=0,
                            flags=re.IGNORECASE,
                        )
                        self.logger.debug(
                            "fetch_dataset: rewrote dataset alias '%s' → '%s' in SQL",
                            _alias, real_table,
                        )
                        break  # one rewrite is enough

            # Reject bare SELECT * early — it pulls every column and
            # overwhelms the model context.  Aggregate functions like
            # COUNT(*) are fine; only a bare star in the SELECT list is
            # rejected.
            _select_star = re.search(
                r'\bSELECT\b(.*?)\bFROM\b', sql, re.IGNORECASE | re.DOTALL
            )
            if _select_star:
                _cleaned_select = re.sub(r'\([^)]*\)', '', _select_star.group(1))
                if '*' in _cleaned_select:
                    table_name = entry.source.table
                    schema = entry.source._schema
                    col_hint = ""
                    if schema:
                        col_list = ', '.join(list(schema.keys())[:30])
                        col_hint = (
                            f" Available columns (first 30): {col_list}."
                            f" Call get_source_schema('{resolved}') for the full list."
                        )
                    return {
                        "error": (
                            f"SELECT * is not allowed on TableSource '{table_name}'. "
                            f"Specify only the columns you need to avoid exceeding "
                            f"the model context window."
                        ),
                        "hint": (
                            f"Rewrite your SQL to select only the required columns. "
                            f"Example: sql=\"SELECT col1, col2 FROM {table_name} "
                            f"WHERE ... LIMIT 100\"{col_hint}"
                        ),
                    }
            # ── Reject non-aggregated queries on large tables ──────
            # When a table has >10k estimated rows and the SQL lacks
            # GROUP BY / aggregate functions, the LLM is likely trying to
            # fetch all rows to aggregate in pandas — reject and hint.
            _row_est = getattr(entry.source, '_row_count_estimate', None)
            if _row_est is not None and _row_est > 10_000:
                _sql_upper = sql.upper()
                _has_aggregation = bool(
                    re.search(r'\bGROUP\s+BY\b', _sql_upper)
                    or re.search(
                        r'\b(COUNT|SUM|AVG|MIN|MAX|STDDEV|VARIANCE)\s*\(',
                        _sql_upper,
                    )
                )
                _has_limit = bool(re.search(r'\bLIMIT\s+\d+', _sql_upper))
                if not _has_aggregation and not _has_limit:
                    table_name = entry.source.table
                    from .sources.table import dialect_hint
                    dhint = dialect_hint(entry.source.driver)
                    dhint_text = f" {dhint}" if dhint else ""
                    return {
                        "error": (
                            f"Query on large table '{table_name}' "
                            f"(~{_row_est:,} rows) lacks GROUP BY or "
                            f"aggregate functions. Fetching all rows to "
                            f"aggregate in pandas is not allowed."
                        ),
                        "hint": (
                            f"Rewrite your SQL to push aggregation to the "
                            f"database. Use GROUP BY with AVG/SUM/COUNT. "
                            f"Example: SELECT category, AVG(metric) AS avg_metric "
                            f"FROM {table_name} WHERE ... GROUP BY category. "
                            f"If you truly need row-level data, add LIMIT N.{dhint_text}"
                        ),
                    }

            params['sql'] = sql
            # Record the (possibly rewritten) SQL as an artifact so it can
            # be surfaced on the AIMessage for debugging / transparency.
            self._artifacts.append({
                "type": "query",
                "content": sql,
                "dataset": resolved,
                "source": "TableSource",
            })
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
                table_name = entry.source.table
                # Build column hint from schema so the LLM can fix its SQL.
                schema = entry.source._schema
                if schema:
                    col_list = ', '.join(list(schema.keys())[:30])
                    col_hint = (
                        f" Available columns (first 30): {col_list}."
                        f" Call get_source_schema('{resolved}') for the full list."
                    )
                else:
                    col_hint = (
                        f" Call get_source_schema('{resolved}') to see available columns."
                    )
                from .sources.table import dialect_hint
                dhint = dialect_hint(entry.source.driver)
                dhint_text = f" {dhint}" if dhint else ""
                hint = (
                    f"Source type is '{source_type}' (table='{table_name}'). "
                    f"Your SQL query failed: {exc}. "
                    f"Do NOT fall back to SELECT * — fix the SQL instead. "
                    f"The table MUST be referenced as '{table_name}' in your query.{col_hint}{dhint_text}"
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

        # PBAC: drop forbidden columns from the returned DataFrame (drop-silent).
        # The registered entry keeps its full data; only the *returned* df is trimmed.
        pctx_fetch = self._get_current_pctx()
        if self._policy_guard and pctx_fetch:
            _all_cols = df.columns.tolist()
            _allowed_cols: list = await self._policy_guard.filter_columns(
                pctx_fetch, resolved, _all_cols
            )
            if set(_allowed_cols) != set(_all_cols):
                _denied_cols = [c for c in _all_cols if c not in set(_allowed_cols)]
                df = df.drop(columns=_denied_cols)

        # Compute NaN warnings from the already-column-filtered df when a guard
        # is active, so denied column names never appear in warning messages.
        # Fall back to the standard helper for the no-guard path.
        if self._policy_guard:
            nan_warnings = []
            if not df.empty:
                _null_counts = df.isnull().sum()
                _total_rows = len(df)
                for _col, _cnt in _null_counts[_null_counts > 0].items():
                    _pct = (_cnt / _total_rows) * 100
                    nan_warnings.append(
                        f"- DataFrame '{resolved}' (column '{_col}'): "
                        f"Contains {_cnt} NaNs ({_pct:.1f}% of {_total_rows} rows)"
                    )
        else:
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

        # PBAC: drop forbidden columns from schema — drop-silent.
        pctx_gss = self._get_current_pctx()
        if self._policy_guard and pctx_gss and schema:
            _all_schema_cols = list(schema.keys())
            _allowed_schema_cols: list = await self._policy_guard.filter_columns(
                pctx_gss, resolved, _all_schema_cols
            )
            if set(_allowed_schema_cols) != set(_all_schema_cols):
                schema = {col: schema[col] for col in _allowed_schema_cols}

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
        # Determine which datasets to report on.
        if names:
            check_names = [self._resolve_name(n) for n in names]
        else:
            check_names = [
                name for name, entry in self._datasets.items()
                if entry.is_active and entry.loaded
            ]

        pctx_dq = self._get_current_pctx()
        nan_warnings: list = []
        dataset_quality: dict = {}

        for ds_name in check_names:
            entry = self._datasets.get(ds_name)
            if not entry or not entry.loaded:
                continue

            df = entry.df

            # PBAC: apply column-level filtering before computing metrics so
            # denied column names never appear in nan_warnings or counts.
            if self._policy_guard and pctx_dq:
                _all_cols_dq = df.columns.tolist()
                _allowed_cols_dq: list = await self._policy_guard.filter_columns(
                    pctx_dq, ds_name, _all_cols_dq
                )
                if set(_allowed_cols_dq) != set(_all_cols_dq):
                    df = df[_allowed_cols_dq]

            # Compute NaN warnings from the (already filtered) df.
            if not df.empty:
                null_counts = df.isnull().sum()
                total_rows = len(df)
                for col_name, count in null_counts[null_counts > 0].items():
                    pct = (count / total_rows) * 100
                    nan_warnings.append(
                        f"- DataFrame '{ds_name}' (column '{col_name}'): "
                        f"Contains {count} NaNs ({pct:.1f}% of {total_rows} rows)"
                    )

            total_cells = df.size
            null_cells = int(df.isnull().sum().sum())
            duplicate_rows = int(df.duplicated().sum())

            dataset_quality[ds_name] = {
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
        if not self._datasets and not self._file_entries:
            return "No datasets registered."

        alias_map = self._get_alias_map()
        active_entries = {
            name: entry for name, entry in self._datasets.items() if entry.is_active
        }
        if not active_entries and not self._file_entries:
            return "No active datasets."

        guide_parts = [
            "# DataFrame Guide",
            "",
        ]
        if active_entries:
            guide_parts.append(f"**Total active datasets**: {len(active_entries)}")
            guide_parts.append("")

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
                    # Use the actual table name (fully-qualified) for the SQL example
                    _table_name = getattr(entry.source, 'table', ds_name)
                    guide_parts.append(
                        f'\n- **To use**: `fetch_dataset("{ds_name}", '
                        f'sql="SELECT col1, col2 FROM {_table_name} WHERE ...")`'
                    )
                    guide_parts.append(
                        f'- **⚠️ AGGREGATION REQUIRED**: For averages, totals, '
                        f'counts, or time-period summaries, you MUST use GROUP BY '
                        f'with AVG/SUM/COUNT in SQL. Example:\n'
                        f'  `sql="SELECT id, DATE_TRUNC(\'month\', date_col) AS month, '
                        f'AVG(metric) FROM {_table_name} GROUP BY id, month"`\n'
                        f'  Do NOT fetch all rows and aggregate in pandas.'
                    )
                    if getattr(entry.source, 'schema_name', None):
                        guide_parts.append(
                            f'- **⚠️ IMPORTANT**: Always use the fully-qualified table name '
                            f'`{_table_name}` in SQL — NOT just `{entry.source.short_table_name}`'
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

            # Usage guidance (DO / DONT) — rendered for both loaded and unloaded
            guidance = entry.usage_guidance
            do_items = guidance.get("do", []) if guidance else []
            dont_items = guidance.get("dont", []) if guidance else []
            if do_items or dont_items:
                if do_items:
                    guide_parts.append("- **Use this dataset for**:")
                    guide_parts.extend(f"  - {item}" for item in do_items)
                if dont_items:
                    guide_parts.append("- **Do NOT use this dataset for**:")
                    guide_parts.extend(f"  - {item}" for item in dont_items)
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

        # ── File entries section ──────────────────────────────────
        if self._file_entries:
            guide_parts.extend([
                "---",
                "## Loaded Files (structural / markdown)",
                "",
            ])
            for fe_name, fe in self._file_entries.items():
                table_count = len(fe.markdown_content)
                guide_parts.append(
                    f"### `{fe_name}` [{fe.file_type.upper()}]"
                )
                guide_parts.append(
                    f"- **Path**: {fe.path.name}"
                )
                guide_parts.append(
                    f"- **Tables**: {table_count} "
                    f"({', '.join(fe.markdown_content.keys())})"
                )
                guide_parts.append(
                    f'- **To inspect**: `get_file_context("{fe_name}")` '
                    f'or `get_file_table("{fe_name}", "<table_id>")`'
                )
                guide_parts.append("")

        return "\n".join(guide_parts)

    def get_guide(self) -> str:
        """Return the current DataFrame guide."""
        if not self.df_guide and self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()
        return self.df_guide

    def get_usage_rules(self) -> str:
        """Return the decision rules an agent should inject into its system prompt.

        These are tool-level (not agent-specific): any agent driving a
        DatasetManager benefits from the same guidance on when to use loaded
        DataFrames vs ``fetch_dataset`` vs ``get_metadata``. Returns the
        per-instance override when one was passed to the constructor, otherwise
        :attr:`DEFAULT_USAGE_RULES`. An explicit empty string disables the block.

        Returns:
            The usage-rules markdown block, or ``""`` when disabled.
        """
        if self._usage_rules is None:
            return self.DEFAULT_USAGE_RULES
        return self._usage_rules

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

    # ─────────────────────────────────────────────────────────────
    # Common-Field Filtering (FEAT-225)
    # ─────────────────────────────────────────────────────────────

    def define_filters(self, definitions: List[FilterDefinition]) -> None:
        """Validate and store common-field filter definitions on this instance.

        Each definition is validated against the datasets registered on *this*
        DatasetManager:

        - **Column coverage** — at least one registered dataset with a known
          schema should contain the target column(s).  If no such dataset is
          found a warning is logged (non-fatal: datasets may not be materialized
          yet or may be added later).
        - **Spatial kind** — when ``kind="spatial"`` every registered dataset
          is checked against the spatial profile registry via
          ``get_spatial_profile``.  If no registered dataset has a spatial
          profile a ``ValueError`` is raised.
        - **Duplicate names** — replacing an existing definition is allowed and
          logged at DEBUG level.

        The definitions are stored in ``self._filter_defs`` (instance-scoped,
        never global).

        Args:
            definitions: List of validated :class:`FilterDefinition` instances.

        Raises:
            ValueError: When ``kind="spatial"`` and no registered dataset has
                a registered spatial profile.
        """
        from .filtering.store import columns_present_in_any, warn_if_no_coverage

        for defn in definitions:
            if defn.name in self._filter_defs:
                self.logger.debug(
                    "define_filters: replacing existing definition '%s'.", defn.name
                )

            if defn.kind == "spatial":
                # Spatial definitions require at least one registered dataset to
                # have a spatial profile. Validate against all known datasets.
                spatial_datasets = [
                    name
                    for name in self._datasets
                    if self._try_get_spatial_profile(name) is not None
                ]
                if not spatial_datasets:
                    raise ValueError(
                        f"define_filters: kind='spatial' for filter '{defn.name}' "
                        f"requires at least one registered dataset with a spatial "
                        f"profile, but none were found. "
                        f"Register a DatasetSpatialProfile via "
                        f"register_spatial_profile() first."
                    )
            else:
                compatible = columns_present_in_any(defn.columns, self._datasets)
                warn_if_no_coverage(defn.name, defn.columns, compatible, self.logger)

            self._filter_defs[defn.name] = defn
            self.logger.debug(
                "define_filters: stored filter '%s' (kind=%s, ops=%s).",
                defn.name,
                defn.kind,
                defn.ops,
            )

    def _try_get_spatial_profile(self, dataset_name: str) -> Any:
        """Return the spatial profile for *dataset_name*, or None if absent.

        Helper to avoid raising inside a list comprehension.

        Args:
            dataset_name: Canonical dataset name.

        Returns:
            DatasetSpatialProfile if registered, else None.
        """
        from .spatial.registry import SPATIAL_PROFILE_REGISTRY

        return SPATIAL_PROFILE_REGISTRY.get(dataset_name)

    async def get_filter_values(
        self,
        name: str,
        *,
        cardinality_cap: int = 1000,
    ) -> List[Any]:
        """Return distinct values for a named filter.

        Resolution order:

        1. **Declared ``values_source``** (from the FilterDefinition):
           - ``query_slug`` → run the slug via the query loader and extract the
             column (``values_source.column``) from the result.
           - ``column`` only → infer from datasets; restrict to
             ``values_source.dataset`` if specified.
        2. **Inference fallback** — union of distinct values from every
           in-memory dataset that has the target column.

        Results are de-duplicated, sorted, and capped at *cardinality_cap*
        (default 1000).  A simple per-instance in-memory cache avoids
        redundant work within a session.

        Args:
            name: The filter definition name to look up.
            cardinality_cap: Maximum number of distinct values to return.
                Values beyond the cap are truncated (a warning is logged).

        Returns:
            Sorted, de-duplicated list of distinct values.

        Raises:
            KeyError: When no filter definition with *name* exists.
        """
        from .filtering.values import apply_cardinality_cap, infer_values_from_datasets

        if name not in self._filter_defs:
            raise KeyError(
                f"get_filter_values: no filter definition named '{name}'. "
                f"Known filters: {sorted(self._filter_defs.keys())}"
            )

        # Simple per-instance TTL-free cache to avoid repeated scans in a session.
        # Initialized in __init__ as self._filter_values_cache; invalidated via
        # clear_filter_values_cache().
        cache: Dict[str, List[Any]] = self._filter_values_cache

        if name in cache:
            self.logger.debug("get_filter_values: cache hit for filter '%s'.", name)
            return cache[name]

        defn = self._filter_defs[name]
        vs = defn.values_source

        values: List[Any] = []

        if vs is not None and vs.query_slug:
            # Declared query_slug source: run the slug and extract the column.
            col = vs.column or (defn.columns[0] if defn.columns else None)
            if col is None:
                self.logger.warning(
                    "get_filter_values: filter '%s' has query_slug but no column "
                    "to extract; falling back to inference.",
                    name,
                )
            else:
                try:
                    df = await self.materialize(vs.query_slug)
                    if col in df.columns:
                        values = df[col].dropna().unique().tolist()
                        try:
                            values = sorted(values)
                        except TypeError:
                            values = sorted(values, key=str)
                    else:
                        self.logger.warning(
                            "get_filter_values: query_slug '%s' result does not "
                            "have column '%s'; falling back to inference.",
                            vs.query_slug,
                            col,
                        )
                except Exception as exc:
                    self.logger.warning(
                        "get_filter_values: query_slug '%s' failed (%s); "
                        "falling back to inference.",
                        vs.query_slug,
                        exc,
                    )

        if not values:
            # Inference: union DISTINCT across in-memory datasets with the column.
            col = (vs.column if vs else None) or (defn.columns[0] if defn.columns else None)
            restrict = vs.dataset if vs else None
            if col:
                values = infer_values_from_datasets(col, self._datasets, restrict)

        # Apply cardinality cap and cache.
        values = apply_cardinality_cap(values, cardinality_cap, name, self.logger)
        cache[name] = values
        self.logger.debug(
            "get_filter_values: filter '%s' → %d values.", name, len(values)
        )
        return values

    def clear_filter_values_cache(self, name: Optional[str] = None) -> None:
        """Invalidate the filter-values cache.

        Called automatically by ``add_dataframe`` and related dataset-mutation
        methods to evict stale entries when datasets change.  May also be
        called explicitly to force a full re-scan on the next
        ``get_filter_values`` call.

        Args:
            name: Dataset name to invalidate. If None, clears the entire cache.
        """
        if name is None:
            self._filter_values_cache.clear()
        else:
            self._filter_values_cache.pop(name, None)

    def get_filter_schema(self) -> List[Dict[str, Any]]:
        """Serialize the filter catalog for the frontend.

        Returns one entry per stored ``FilterDefinition``, including which
        registered datasets have the target column(s) (the "applicable" set).

        Returns:
            List of dicts, one per filter::

                [
                    {
                        "name": "region",
                        "kind": "categorical",
                        "ops": ["eq", "ne", "in"],
                        "label": "Region",
                        "required": False,
                        "datasets": ["stores", "sites"],  # datasets with the column
                    },
                    ...
                ]

            Datasets whose schema has not been loaded yet (``_column_types`` is
            empty and ``_df`` is None) are omitted from ``datasets`` — they are
            not excluded, just unknown.
        """
        schema: List[Dict[str, Any]] = []
        for defn in self._filter_defs.values():
            if defn.kind == "spatial":
                # Spatial filter: applicable datasets are those with a spatial profile.
                applicable = [
                    name for name in self._datasets
                    if self._try_get_spatial_profile(name) is not None
                ]
            else:
                applicable = []
                for ds_name, entry in self._datasets.items():
                    col_types = entry._column_types or {}
                    if col_types:
                        if all(c in col_types for c in defn.columns):
                            applicable.append(ds_name)
                    elif entry._df is not None:
                        if all(c in entry._df.columns for c in defn.columns):
                            applicable.append(ds_name)

            schema.append({
                "name": defn.name,
                "kind": defn.kind,
                "ops": defn.ops,
                "label": defn.label,
                "description": defn.description,
                "required": defn.required,
                "datasets": applicable,
                "columns": defn.columns,
            })
        return schema

    def suggest_filters(self, min_datasets: int = 1) -> List[FilterDefinition]:
        """Propose FilterDefinitions from column introspection (opt-in, no side effects).

        Scans loaded datasets and proposes filter definitions for columns that
        are present in at least *min_datasets* datasets with a known schema.

        Mapping from column kind to FilterDefinition:

        - ``categorical`` / ``categorical_text`` → ``kind="categorical"``, ops
          ``["eq","ne","in","not_in"]``.
        - ``integer`` / ``float`` → ``kind="numeric"``, ops ``["range","eq"]``.
        - ``datetime`` → ``kind="temporal"``, ops ``["range"]``.
        - Columns in a registered spatial profile (lat/lng pairs or geom col)
          → ``kind="spatial"``, ops ``["radius"]``.

        Args:
            min_datasets: Minimum number of datasets that must have the column
                for a suggestion to be made (default 1).

        Returns:
            List of proposed :class:`FilterDefinition` instances.
            This method has **no side effects** — definitions are NOT stored.

        Note:
            This method reads ``_column_types`` from each DatasetEntry.  Entries
            that have not been materialized yet will not contribute to the column
            census.
        """
        # Build a census: column → {semantic_type: ..., dataset_names: [...]}
        col_census: Dict[str, Dict] = {}

        for ds_name, entry in self._datasets.items():
            col_types = entry._column_types or {}
            for col, sem_type in col_types.items():
                if col not in col_census:
                    col_census[col] = {"sem_type": sem_type, "datasets": []}
                col_census[col]["datasets"].append(ds_name)

        # Also scan spatial profiles for lat/lng hints.
        from .spatial.registry import SPATIAL_PROFILE_REGISTRY

        proposals: List[FilterDefinition] = []
        seen_names: set = set()

        # Non-spatial suggestions
        _CAT_TYPES = {"categorical", "categorical_text"}
        _NUM_TYPES = {"integer", "float"}
        _KIND_MAP = {
            "categorical": ("categorical", ["eq", "ne", "in", "not_in"]),
            "categorical_text": ("categorical", ["eq", "ne", "in", "not_in"]),
            "integer": ("numeric", ["range", "eq"]),
            "float": ("numeric", ["range", "eq"]),
            "datetime": ("temporal", ["range"]),
        }

        for col, info in col_census.items():
            if len(info["datasets"]) < min_datasets:
                continue
            sem_type = info["sem_type"]
            if sem_type not in _KIND_MAP:
                continue  # boolean, text — no auto-suggestion
            kind, ops = _KIND_MAP[sem_type]
            if col not in seen_names:
                seen_names.add(col)
                proposals.append(FilterDefinition(
                    name=col,
                    columns=[col],
                    kind=kind,
                    ops=ops,
                    required=False,
                    label=col.replace("_", " ").title(),
                ))

        # Spatial suggestions from registered profiles intersecting this manager.
        # Snapshot before iterating to prevent RuntimeError if the registry is
        # mutated by a concurrent async task (FIX-5 / FEAT-225 code review).
        registry_snapshot = dict(SPATIAL_PROFILE_REGISTRY)
        for ds_name, profile in registry_snapshot.items():
            if ds_name not in self._datasets:
                continue
            # Build column list from profile
            if profile.lat_col and profile.lng_col:
                cols = [profile.lat_col, profile.lng_col]
                suggestion_name = f"{ds_name}_spatial"
            elif profile.geom_col:
                cols = [profile.geom_col]
                suggestion_name = f"{ds_name}_spatial"
            else:
                continue

            if suggestion_name not in seen_names:
                seen_names.add(suggestion_name)
                proposals.append(FilterDefinition(
                    name=suggestion_name,
                    columns=cols,
                    kind="spatial",
                    ops=["radius"],
                    required=False,
                    label=f"{ds_name} Location",
                ))

        skip_count = sum(
            1 for entry in self._datasets.values()
            if not entry.loaded and not getattr(entry.source, '_schema', None)
        )
        self.logger.debug(
            "suggest_filters: proposed %d filter(s) from column census of %d column(s) "
            "(%d unloaded datasets skipped).",
            len(proposals),
            len(col_census),
            skip_count,
        )
        return proposals

    # ─────────────────────────────────────────────────────────────
    # LLM-facing tool wrappers (FEAT-225 Module 7)
    # AbstractToolkit.get_tools() auto-collects async public methods.
    # ─────────────────────────────────────────────────────────────

    async def list_filters(self) -> List[Dict[str, Any]]:
        """List all defined common-field filters and their applicable datasets.

        Returns the filter schema — one entry per stored filter definition with
        its name, kind, supported operators, applicable datasets, and metadata.
        Call this to discover what filters are available before applying them.

        Returns:
            List of filter schema dicts (name, kind, ops, datasets, required, ...).
        """
        return self.get_filter_schema()

    async def set_filters(
        self,
        filter_definitions: List[Dict[str, Any]],
    ) -> str:
        """Define (or replace) common-field filters on this DatasetManager.

        Validates each definition against registered datasets and stores it
        on this instance (no global state). Existing definitions with the
        same name are replaced.

        Args:
            filter_definitions: List of filter definition dicts. Each must
                include "name" (str), "columns" (list of str), "kind"
                (categorical/numeric/temporal/text/spatial), and "ops"
                (list of operators). Optional: "required" (bool), "label" (str),
                "description" (str).

        Returns:
            Confirmation string listing stored filter names.

        Raises:
            ValueError: When a spatial filter has no registered spatial profile.
        """
        defs = [FilterDefinition(**d) for d in filter_definitions]
        self.define_filters(defs)
        names = [d.name for d in defs]
        return f"Stored {len(names)} filter(s): {names}"

    async def apply_filters(
        self,
        request: Dict[str, Any],
        *,
        persist: bool = False,
    ) -> "FilterResult":
        """Apply a filter request recursively across all matching datasets.

        Resolves each key in ``request`` against the stored filter catalog
        (``self._filter_defs``), then applies the condition to every registered
        dataset that contains the target column(s).

        Execution strategy per source type:
        - **In-memory DataFrames** (``InMemorySource`` or already materialized):
          filtered via the extended :meth:`_apply_filter` (pandas path).
        - **SQL-backed sources** (``TableSource``/``QuerySlugSource``): materialized
          first (fetching from the database if needed), then filtered via pandas.
          The :class:`FilterCompiler` SQL compile path is available for future
          in-database push-down; this orchestrator currently uses the
          materialize-then-filter strategy for reliability.
        - **kind="spatial"**: delegates entirely to :meth:`spatial_filter`.

        Datasets that lack the target column(s) are:
        - Silently skipped and recorded in ``result.skipped`` when
          ``definition.required is False`` (default).
        - Cause a ``ValueError`` naming the dataset when ``required is True``.

        Args:
            request: Mapping of filter name → value.  A bare scalar becomes
                ``FilterCondition(op="eq", value=scalar)``; a bare list becomes
                ``FilterCondition(op="in", value=list)``; a ``FilterCondition``
                or dict with ``{"op": ..., "value": ...}`` is used as-is.
            persist: When True, the filtered DataFrame for each dataset is
                registered in this manager under the name ``<original>__filtered``
                (with a collision guard).  Default is False (ephemeral).

        Returns:
            :class:`FilterResult` with ``applied`` and ``skipped`` lists.

        Raises:
            KeyError: When a request key does not match any stored definition.
            ValueError: When a ``required=True`` filter targets a dataset that
                lacks the column(s).
        """
        from .filtering.contracts import FilterCondition as _FC

        result = FilterResult()
        all_filtered: Dict[str, pd.DataFrame] = {}

        # ── Resolve request keys to FilterCondition objects ──────────
        resolved_conditions: Dict[str, _FC] = {}
        for req_key, req_val in request.items():
            if req_key not in self._filter_defs:
                raise KeyError(
                    f"apply_filters: no filter definition named '{req_key}'. "
                    f"Known filters: {sorted(self._filter_defs.keys())}"
                )
            if isinstance(req_val, _FC):
                condition = req_val
            elif isinstance(req_val, dict) and "op" in req_val:
                condition = _FC(**req_val)
            elif isinstance(req_val, (list, tuple, set)):
                condition = _FC(op="in", value=list(req_val))
            else:
                condition = _FC(op="eq", value=req_val)
            resolved_conditions[req_key] = condition

        # ── Spatial path ──────────────────────────────────────────────
        spatial_filter_names = [
            k for k, v in self._filter_defs.items()
            if v.kind == "spatial" and k in resolved_conditions
        ]
        for fname in spatial_filter_names:
            defn = self._filter_defs[fname]
            cond = resolved_conditions[fname]
            # Build SpatialFilterSpec from the condition's value.
            # value must be {"point": (lat, lng), "radius": r, "unit": "mi"/"km"/"m"}
            # or a similar structure.
            val = cond.value or {}
            if not isinstance(val, dict):
                raise ValueError(
                    f"apply_filters: spatial filter '{fname}' requires a dict value "
                    f"with 'point', 'radius', and 'unit' keys; got {type(val).__name__}."
                )
            # Find datasets that have this filter's spatial profile
            spatial_datasets = [
                name for name in self._datasets
                if self._try_get_spatial_profile(name) is not None
            ]
            if not spatial_datasets:
                if defn.required:
                    raise ValueError(
                        f"apply_filters: required spatial filter '{fname}' found no "
                        f"datasets with a registered spatial profile."
                    )
                result.skipped.extend(list(self._datasets.keys()))
                continue

            from .spatial.contracts import SpatialFilterSpec as _SFS
            spec = _SFS(
                point=val.get("point", (0.0, 0.0)),
                radius=val.get("radius", 0.0),
                unit=val.get("unit", "mi"),
                datasets=spatial_datasets,
            )
            spatial_result = await self.spatial_filter(spec)
            # Mark spatial datasets as applied
            for ds_name in spatial_datasets:
                result.applied.append(ds_name)
            # Return the spatial result embedded — callers can inspect it
            # via the returned FilterResult's extra data.
            # For now we store a reference in all_filtered under a sentinel key.
            all_filtered["__spatial__"] = spatial_result  # type: ignore[assignment]

        # ── Non-spatial path ──────────────────────────────────────────
        non_spatial_conditions = {
            k: v for k, v in resolved_conditions.items()
            if self._filter_defs[k].kind != "spatial"
        }

        for ds_name, entry in self._datasets.items():
            applicable: Dict[str, _FC] = {}

            for fname, cond in non_spatial_conditions.items():
                defn = self._filter_defs[fname]
                target_cols = defn.columns

                # Determine column presence
                col_types = entry._column_types or {}
                df_loaded = entry._df

                if col_types:
                    has_cols = all(c in col_types for c in target_cols)
                elif df_loaded is not None:
                    has_cols = all(c in df_loaded.columns for c in target_cols)
                else:
                    # Schema not yet known; skip (cannot confirm column presence).
                    has_cols = False

                if not has_cols:
                    if defn.required:
                        raise ValueError(
                            f"apply_filters: required filter '{fname}' targets "
                            f"column(s) {target_cols!r} not present in dataset "
                            f"'{ds_name}'. Either remove 'required=True' or ensure "
                            f"the dataset has these columns."
                        )
                    # Non-required missing column: record the per-filter skip and
                    # continue — this dataset may still match other filters.
                    if ds_name not in result.partial_skips:
                        result.partial_skips[ds_name] = []
                    result.partial_skips[ds_name].append(fname)
                    continue

                # Condition is applicable to this dataset
                # For multi-column filters (currently all single-column in v1),
                # use the first column.
                applicable[target_cols[0]] = cond

            if not applicable:
                # No conditions applied to this dataset (missing column(s)).
                # Only record as skipped if there were non-spatial conditions
                # in the request — otherwise the dataset is simply not targeted.
                if non_spatial_conditions:
                    result.skipped.append(ds_name)
                continue

            # Materialize the dataset if not already loaded.
            # TODO(FEAT-225-SQL-PUSHDOWN): For SQL-backed sources (TableSource,
            # QuerySlugSource) consider pushing predicates down to the database
            # using FilterCompiler.compile_where() instead of materializing the
            # full DataFrame here. The SQL compile path exists in FilterCompiler
            # but is deferred until we can reliably detect source capabilities
            # and handle partial push-down for mixed source types.
            if entry._df is None:
                try:
                    df = await self.materialize(ds_name)
                except Exception as exc:
                    self.logger.warning(
                        "apply_filters: could not materialize dataset '%s': %s",
                        ds_name,
                        exc,
                    )
                    result.skipped.append(ds_name)
                    continue
            else:
                df = entry._df

            # Apply all applicable conditions via extended _apply_filter
            try:
                filtered_df = self._apply_filter(df, applicable)
            except Exception as exc:
                self.logger.warning(
                    "apply_filters: filtering dataset '%s' failed: %s",
                    ds_name,
                    exc,
                )
                result.skipped.append(ds_name)
                continue

            all_filtered[ds_name] = filtered_df
            result.applied.append(ds_name)
            self.logger.debug(
                "apply_filters: dataset '%s' filtered — %d → %d rows.",
                ds_name,
                len(df),
                len(filtered_df),
            )

        # ── Persist ───────────────────────────────────────────────────
        if persist:
            for ds_name, filtered_df in all_filtered.items():
                if ds_name == "__spatial__":
                    continue  # spatial results are not DataFrames

                # Derive a name from the active filter conditions applied to
                # this dataset.  Use the filter value (slugified) so the
                # resulting dataset name is descriptive and reproducible.
                # E.g. stores__region_eq_North, stores__x_range_5_10
                def _sanitize(v: Any, max_len: int = 32) -> str:
                    """Slugify a filter value for use as a name fragment."""
                    import re as _re
                    s = str(v).replace(" ", "_")
                    s = _re.sub(r"[^\w\-]", "", s)
                    return s[:max_len]

                # Build a slug from the first applicable condition for this ds
                applied_conditions = {
                    k: v for k, v in resolved_conditions.items()
                    if self._filter_defs[k].kind != "spatial"
                    and all(
                        c in (entry._column_types or {})
                        or (entry._df is not None and c in entry._df.columns)
                        for c in self._filter_defs[k].columns
                    )
                } if ds_name in self._datasets else {}

                if applied_conditions:
                    fname, cond = next(iter(applied_conditions.items()))
                    op = cond.op
                    val = cond.value
                    if op == "eq":
                        slug = _sanitize(val)
                    elif op in ("in", "not_in"):
                        # Use first item for brevity
                        items = list(val) if isinstance(val, (list, tuple, set)) else [val]
                        slug = f"{op}_{_sanitize(items[0])}" if items else op
                    elif op == "range":
                        try:
                            lo = val.get("min", val[0]) if isinstance(val, dict) else val[0]
                            hi = val.get("max", val[1]) if isinstance(val, dict) else val[1]
                        except (KeyError, IndexError, TypeError):
                            lo, hi = "", ""
                        slug = f"range_{_sanitize(lo)}_{_sanitize(hi)}"
                    else:
                        slug = f"{op}_{_sanitize(val)}"
                    new_name = f"{ds_name}__{fname}_{slug}"
                else:
                    new_name = f"{ds_name}__filtered"

                # Collision guard: append numeric suffix until unique
                suffix = 1
                candidate = new_name
                while candidate in self._datasets:
                    candidate = f"{new_name}_{suffix}"
                    suffix += 1

                entry = DatasetEntry(
                    name=candidate,
                    df=filtered_df,
                    description=f"Filtered view of '{ds_name}'.",
                )
                self._datasets[candidate] = entry
                self.logger.info(
                    "apply_filters: persisted filtered dataset '%s' as '%s'.",
                    ds_name,
                    candidate,
                )

        return result

    # ─────────────────────────────────────────────────────────────
    # Spatial Filtering (FEAT-219)
    # ─────────────────────────────────────────────────────────────

    def get_manifest(self) -> List[Dict[str, Any]]:
        """Return a manifest of all datasets that have a spatial profile.

        Each entry carries the layer id, geodesic hint, and property columns
        for that dataset — the minimum the frontend needs to configure Leaflet
        layers and the LLM needs to understand which datasets are spatially
        queryable.

        Returns:
            List of dicts, one per spatially-profiled dataset::

                [
                    {
                        "dataset": "schools",
                        "layer": "schools",
                        "geodesic": True,
                        "property_cols": ["name", "type"],
                    },
                    ...
                ]

            Only datasets that (a) have a registered spatial profile AND
            (b) exist in this DatasetManager instance are included.  Profiles
            for unknown datasets are skipped with a debug log.
        """
        from .spatial.registry import SPATIAL_PROFILE_REGISTRY

        manifest = []
        # Snapshot before iterating to prevent RuntimeError if the registry is
        # mutated by a concurrent async task (FIX-5 / FEAT-225 code review).
        registry_snapshot = dict(SPATIAL_PROFILE_REGISTRY)
        for dataset_name, profile in registry_snapshot.items():
            # Only include datasets that actually exist in this manager instance
            resolved = self._resolve_name(dataset_name)
            if resolved not in self._datasets and dataset_name not in self._datasets:
                self.logger.debug(
                    "get_manifest: spatial profile for '%s' skipped — dataset not registered "
                    "in this DatasetManager instance.",
                    dataset_name,
                )
                continue
            manifest.append({
                "dataset": dataset_name,
                "layer": profile.layer,
                "geodesic": profile.geodesic,
                "property_cols": list(profile.property_cols),
            })
        self.logger.debug("get_manifest: returning %d spatial dataset(s).", len(manifest))
        return manifest

    async def spatial_filter(
        self,
        spec: "SpatialFilterSpec",
        cap_per_dataset: int = 1000,
    ) -> "SpatialResult":
        """Execute a spatial radius filter across one or more datasets.

        This is a **thin orchestration method** — it does not contain any SQL
        or geometry math.  All translation lives in :class:`SpatialCompiler`.

        Flow:
        1. Resolve each dataset name via ``_resolve_name``; validate that every
           dataset has a registered spatial profile (descriptive ``ValueError``).
        2. Group datasets by ``(driver, connection)`` so co-located tables share
           one AsyncDB connection.
        3. ``asyncio.gather`` per group, propagating the current
           ``PermissionContext`` via ``_pctx_var`` so concurrent requests remain
           isolated.
        4. Build a per-dataset ``SpatialResult`` (FEAT-221 G4) with one
           ``SpatialLayerResult`` per dataset, preserving individual capping
           and geodesic flags.  A back-compat ``as_feature_collection()`` helper
           is available for callers that still need the legacy merged shape.

        Args:
            spec: Spatial filter request — point, radius, datasets.  Backend-agnostic.
            cap_per_dataset: Hard cap on features returned per dataset.  Defaults to
                1000.  True count is always recorded in ``total_count``.

        Returns:
            A ``SpatialResult`` (versioned per-dataset grouping, FEAT-221 G4).
            Use ``result.as_feature_collection()`` to get the legacy merged shape.

        Raises:
            ValueError: If any dataset name in ``spec.datasets`` is not registered
                in this ``DatasetManager`` instance OR lacks a spatial profile.
        """
        import asyncio
        from .spatial.contracts import (
            SpatialResult,
            SpatialLayerResult,
            SpatialFilterSpec,
        )
        from .spatial.registry import get_spatial_profile, validate_profiles_exist
        from .spatial.compiler import SpatialCompiler

        # Coerce a dict spec into the Pydantic model. The tool framework may pass
        # ``spec`` as a raw dict (e.g. the LLM emits JSON args like
        # {"point": [...], "radius": 100, "unit": "km", "datasets": [...]})
        # rather than a constructed SpatialFilterSpec; without this, the
        # ``spec.datasets`` access below raises AttributeError and the spatial
        # query (Path A) fails for the map renderer.
        if isinstance(spec, dict):
            spec = SpatialFilterSpec(**spec)

        compiler = SpatialCompiler()

        # ── 1. Resolve names and validate profiles ───────────────────────────
        resolved_names = [self._resolve_name(name) for name in spec.datasets]

        # Validate every dataset exists in this manager
        missing_datasets = [n for n in resolved_names if n not in self._datasets]
        if missing_datasets:
            available = list(self._datasets.keys())
            raise ValueError(
                f"spatial_filter: dataset(s) not registered in this DatasetManager: "
                f"{missing_datasets}. Available: {available}"
            )

        # Validate every dataset has a spatial profile (descriptive error)
        validate_profiles_exist(resolved_names)
        profiles = {name: get_spatial_profile(name) for name in resolved_names}

        # ── 2. Group by (driver, connection) ─────────────────────────────────
        # Each group shares an AsyncDB connection type — co-located datasets can
        # potentially share a connection pool. For now, each dataset is its own
        # gather task; future optimisation can batch within a group.
        def _group_key(name: str) -> tuple:
            source = self._datasets[name].source
            driver = getattr(source, "driver", "") or ""
            # Use the DSN or a stable key for the connection identity
            if hasattr(source, "_get_connection_args"):
                try:
                    creds, dsn = source._get_connection_args()
                    conn_key = dsn or str(sorted((creds or {}).items()))
                except Exception:
                    conn_key = ""
            else:
                conn_key = ""
            return (driver, conn_key)

        groups: Dict[tuple, list] = {}
        for name in resolved_names:
            key = _group_key(name)
            groups.setdefault(key, []).append(name)

        # Snapshot the current PermissionContext so each task inherits it
        current_pctx = _pctx_var.get(None)

        # ── 3. asyncio.gather per group ───────────────────────────────────────

        async def _fetch_dataset(dataset_name: str) -> tuple:
            """Fetch spatial features for a single dataset.

            Returns:
                Tuple of (features, true_count, geodesic) where true_count is the
                number of matches before capping.  On error, returns ([], 0, True).
            """
            # Propagate PermissionContext into this task's ContextVar copy
            _pctx_var.set(current_pctx)

            entry = self._datasets[dataset_name]
            source = entry.source
            profile = profiles[dataset_name]

            # Create a per-dataset spec copy with just this dataset
            from .spatial.contracts import SpatialFilterSpec as _SFS

            # compile() and execute() are both inside the try block so a corrupt
            # profile or connection error activates the partial-results policy
            # rather than propagating out of asyncio.gather.
            try:
                single_spec = _SFS(
                    point=spec.point,
                    radius=spec.radius,
                    unit=spec.unit,
                    datasets=[dataset_name],
                )
                compiled = compiler.compile(single_spec, profile, source=source, cap=cap_per_dataset)
                features, true_count = await compiler.execute(compiled, source)
            except Exception as exc:
                # Partial failure policy: surface empty + error marker (logged)
                self.logger.error(
                    "spatial_filter: dataset '%s' failed: %s",
                    dataset_name, exc,
                )
                return [], 0, True

            return features, true_count, compiled.geodesic

        # Launch gather tasks
        tasks = [_fetch_dataset(name) for name in resolved_names]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # ── 4. Build per-dataset SpatialResult (FEAT-221 G4) ─────────────────
        layer_results: Dict[str, SpatialLayerResult] = {}
        for name, (raw_features, true_count, geodesic) in zip(resolved_names, results):
            profile = profiles[name]
            # Per-dataset cap: cap the returned features, keep the true count
            this_capped = true_count > cap_per_dataset
            if this_capped:
                raw_features = raw_features[:cap_per_dataset]

            layer_results[name] = SpatialLayerResult(
                layer=profile.layer,
                features=raw_features,
                total_count=true_count,
                capped=this_capped,
                geodesic=geodesic,
            )

        return SpatialResult(layers=layer_results)
