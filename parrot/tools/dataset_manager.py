"""
DatasetManager: A Toolkit and Data Catalog for PandasAgent.

Provides:
- Dataset catalog with add/remove/activate/deactivate
- Full metadata/EDA capabilities (replaces MetadataTool)
- Column type categorization and metrics guide generation
- Data quality checks (NaN detection, completeness)
- LLM-exposed tools for discovery, metadata retrieval, and management
"""
from typing import Dict, List, Optional, Any, Union
from os import PathLike
from pydantic import BaseModel, Field
import numpy as np
import pandas as pd
from navconfig.logging import logging
from .toolkit import AbstractToolkit
import redis.asyncio as aioredis
from datetime import timedelta
from datamodel.parsers.json import json_encoder, json_decoder
from ..conf import REDIS_HISTORY_URL


try:
    logger = logging.getLogger(__name__)
except Exception:
    logger = logging


class DatasetInfo(BaseModel):
    """Schema for dataset information exposed to LLM."""

    name: str = Field(description="Dataset name/identifier")
    alias: Optional[str] = Field(default=None, description="Standardized alias (df1, df2, etc.)")
    description: str = Field(default="", description="Dataset description")
    shape: tuple[int, int] = Field(description="(rows, columns)")
    columns: List[str] = Field(description="List of column names")
    is_active: bool = Field(description="Whether dataset is currently active")
    loaded: bool = Field(description="Whether data is loaded in memory")
    memory_usage_mb: float = Field(default=0.0, description="Memory usage in MB")
    null_count: int = Field(default=0, description="Total number of null values across all columns")
    column_types: Optional[Dict[str, str]] = Field(
        default=None,
        description="Detected column type categories (integer, float, datetime, categorical_text, text, etc.)"
    )


class DatasetEntry:
    """Internal representation of a dataset in the catalog."""

    def __init__(
        self,
        name: str,
        df: Optional[pd.DataFrame] = None,
        query_slug: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        auto_detect_types: bool = True,
    ):
        self.name = name
        self.df = df
        self.query_slug = query_slug
        self.metadata = metadata or {}
        self.is_active = is_active
        self.auto_detect_types = auto_detect_types
        self._column_metadata: Dict[str, Dict[str, Any]] = {}
        self._column_types: Optional[Dict[str, str]] = None

        # Build column metadata if df is provided
        if df is not None:
            self._build_column_metadata(metadata)
            if auto_detect_types:
                self._column_types = DatasetManager.categorize_columns(df)

    def _build_column_metadata(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Build column metadata from DataFrame and optional user metadata."""
        if self.df is None:
            return

        column_meta = {}
        if metadata and isinstance(metadata.get('columns'), dict):
            column_meta = metadata['columns']
        elif metadata:
            # Check for column keys directly in metadata
            column_meta = {
                k: v for k, v in metadata.items()
                if k in self.df.columns
            }

        for col in self.df.columns:
            user_meta = column_meta.get(col)
            if isinstance(user_meta, str):
                self._column_metadata[col] = {'description': user_meta}
            elif isinstance(user_meta, dict):
                self._column_metadata[col] = user_meta.copy()
            else:
                self._column_metadata[col] = {}

            self._column_metadata[col].setdefault(
                'description',
                col.replace('_', ' ').title()
            )
            self._column_metadata[col].setdefault(
                'dtype',
                str(self.df[col].dtype)
            )

    @property
    def loaded(self) -> bool:
        return self.df is not None

    @property
    def shape(self) -> tuple[int, int]:
        if self.df is not None:
            return self.df.shape
        return (0, 0)

    @property
    def columns(self) -> List[str]:
        if self.df is not None:
            return self.df.columns.tolist()
        return []

    @property
    def memory_usage_mb(self) -> float:
        if self.df is not None:
            return self.df.memory_usage(deep=True).sum() / 1024 / 1024
        return 0.0

    @property
    def null_count(self) -> int:
        if self.df is not None:
            return int(self.df.isnull().sum().sum())
        return 0

    @property
    def column_types(self) -> Optional[Dict[str, str]]:
        return self._column_types

    def to_info(self, alias: Optional[str] = None) -> DatasetInfo:
        return DatasetInfo(
            name=self.name,
            alias=alias,
            description=self.metadata.get("description", ""),
            shape=self.shape,
            columns=self.columns,
            is_active=self.is_active,
            loaded=self.loaded,
            memory_usage_mb=round(self.memory_usage_mb, 2),
            null_count=self.null_count,
            column_types=self._column_types,
        )


class DatasetManager(AbstractToolkit):
    """
    Dataset catalog and toolkit for managing DataFrames.

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
        self.df_prefix = df_prefix
        self.generate_guide = generate_guide
        self.include_summary_stats = include_summary_stats
        self.auto_detect_types = auto_detect_types
        self.df_guide: str = ""
        self.logger = logger

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
        for name in self._datasets.keys():
            if name.lower() == identifier_lower:
                return name

        return identifier

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
            elif pd.api.types.is_categorical_dtype(df[col]):
                column_types[col] = "categorical"
            elif pd.api.types.is_bool_dtype(df[col]):
                column_types[col] = "boolean"
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
        warnings = []

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
                        warnings.append(
                            f"- DataFrame '{name}' (column '{col_name}'): "
                            f"Contains {count} NaNs ({percentage:.1f}% of {total_rows} rows)"
                        )

            except Exception as e:
                self.logger.warning(f"Error checking NaNs in dataframe '{name}': {e}")

        return warnings

    # ─────────────────────────────────────────────────────────────
    # Catalog Management (Internal Methods)
    # ─────────────────────────────────────────────────────────────

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

        self._datasets[name] = DatasetEntry(
            name=name,
            df=df,
            metadata=metadata,
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
        )

        # Regenerate guide if enabled
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        self.logger.debug(f"Dataset '{name}' added ({df.shape[0]} rows × {df.shape[1]} cols)")
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
        self._datasets[name] = DatasetEntry(
            name=name,
            query_slug=query_slug,
            metadata=metadata,
            is_active=is_active,
            auto_detect_types=self.auto_detect_types,
        )
        self.logger.debug(f"Query '{name}' registered (slug: {query_slug})")
        return f"Query '{name}' registered (slug: {query_slug})"

    def remove(self, name: str) -> str:
        """Remove a dataset from the catalog."""
        name = self._resolve_name(name)
        if name not in self._datasets:
            raise ValueError(f"Dataset '{name}' not found")
        del self._datasets[name]

        # Regenerate guide if enabled
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        self.logger.debug(f"Dataset '{name}' removed")
        return f"Dataset '{name}' removed"

    def set_query_loader(self, loader: Any) -> None:
        """Set the query loader callable (from PandasAgent)."""
        self._query_loader = loader



    async def _load_query(self, name: str) -> pd.DataFrame:
        """Load a dataset from its query slug."""
        entry = self._datasets.get(name)
        if not entry or not entry.query_slug:
            raise ValueError(f"No query slug for dataset '{name}'")

        if not self._query_loader:
            raise RuntimeError("Query loader not set")

        result = await self._query_loader([entry.query_slug])
        if result and name in result:
            entry.df = result[name]
            entry._build_column_metadata(entry.metadata)
        elif result:
            entry.df = list(result.values())[0]
            entry._build_column_metadata(entry.metadata)
        else:
            raise RuntimeError(f"Query returned no data for '{name}'")

        # Rebuild column types after loading
        if self.auto_detect_types and entry.df is not None:
            entry._column_types = self.categorize_columns(entry.df)

        return entry.df

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
            return {
                "name": resolved_name,
                "loaded": False,
                "query_slug": entry.query_slug,
                "message": "Dataset not loaded. Use activate_datasets to load."
            }

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
        activated = self.activate(names)
        if not activated:
            return f"No datasets found matching: {names}"
        return f"Activated datasets: {', '.join(activated)}"

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
        deactivated = self.deactivate(names)
        if not deactivated:
            return f"No datasets found matching: {names}"
        return f"Deactivated datasets: {', '.join(deactivated)}"

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
        """Generate comprehensive DataFrame guide for the LLM."""
        active_dfs = self.get_active_dataframes()
        if not active_dfs:
            return "No DataFrames loaded."

        alias_map = self._get_alias_map()

        guide_parts = [
            "# DataFrame Guide",
            "",
            f"**Total DataFrames**: {len(active_dfs)}",
            "",
            "## Available DataFrames:",
        ]

        for df_name, df in active_dfs.items():
            df_alias = alias_map.get(df_name, "")
            shape = df.shape

            guide_parts.extend([
                f"### DataFrame: `{df_name}` (alias: `{df_alias}`)",
                f"- **Primary Name**: `{df_name}` ← Use this in your code",
                f"- **Alias**: `{df_alias}` (convenience reference)",
                f"- **Shape**: {shape[0]:,} rows × {shape[1]} columns",
                f"- **Columns**: {', '.join(df.columns.tolist()[:10])}{'...' if len(df.columns) > 10 else ''}",
                ""
            ])

            # Add summary statistics for numeric columns
            if self.include_summary_stats:
                numeric_cols = df.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) > 0:
                    guide_parts.append("- **Numeric Summary**:")
                    guide_parts.extend(
                        f"  - `{col}`: min={df[col].min():.2f}, max={df[col].max():.2f}, mean={df[col].mean():.2f}"
                        for col in numeric_cols[:5]
                    )
                    guide_parts.append("")

            # Null value summary
            null_counts = df.isnull().sum()
            if null_counts.sum() > 0:
                null_summary = [f"`{col}`: {count}" for col, count in null_counts.items() if count > 0]
                guide_parts.extend([
                    "- **Missing Values**:",
                    f"  {', '.join(null_summary)}",
                    ""
                ])

        # Usage examples
        guide_parts.extend([
            "## Usage Examples",
            "",
            "**IMPORTANT**: Always use the PRIMARY dataframe names in your code:",
            "",
            "```python",
        ])

        # Add real examples using actual dataframe names
        if active_dfs:
            first_name = list(active_dfs.keys())[0]
            first_alias = alias_map.get(first_name, f"{self.df_prefix}1")
            guide_parts.extend([
                f"# ✅ CORRECT: Use original names",
                f"print({first_name}.shape)  # Access by original name",
                f"result = {first_name}.groupby('column_name').size()",
                f"filtered = {first_name}[{first_name}['column'] > 100]",
                "",
                f"# ✅ ALSO WORKS: Use aliases if more convenient",
                f"print({first_alias}.shape)  # Same DataFrame, different name",
                "",
                "# Store results for later use",
                "execution_results['my_analysis'] = result",
                "",
                "# Create visualizations",
                "import matplotlib.pyplot as plt",
                "plt.figure(figsize=(10, 6))",
                f"plt.hist({first_name}['numeric_column'])",
                "plt.title('Distribution')",
                "save_current_plot('histogram.png')",
            ])

        guide_parts.extend([
            "```",
            "",
            "## Key Points",
            "",
            f"1. **Primary Names**: Use the original DataFrame names (e.g., `{list(active_dfs.keys())[0] if active_dfs else 'df1'}`)",
            f"2. **Aliases Available**: You can also use `{self.df_prefix}1`, `{self.df_prefix}2`, etc. if shorter names are preferred",
            "3. **Both Work**: The DataFrames are accessible by BOTH names in the execution environment",
            "4. **Recommendation**: Use original names for clarity, aliases for brevity",
            ""
        ])

        return "\n".join(guide_parts)

    def get_guide(self) -> str:
        """Return the current DataFrame guide."""
        if not self.df_guide and self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()
        return self.df_guide

    # ─────────────────────────────────────────────────────────────
    # Data Loading & Caching (moved from PandasAgent)
    # ─────────────────────────────────────────────────────────────

    async def _get_redis_connection(self):
        """Get Redis connection."""
        return await aioredis.Redis.from_url(
            REDIS_HISTORY_URL,
            decode_responses=True
        )

    async def _get_cached_data(self, agent_name: str) -> Optional[Dict[str, pd.DataFrame]]:
        """Retrieve cached DataFrames from Redis."""
        try:
            redis_conn = await self._get_redis_connection()
            key = f"agent_{agent_name}"

            if not await redis_conn.exists(key):
                await redis_conn.close()
                return None

            # Get all dataframe keys
            df_keys = await redis_conn.hkeys(key)
            if not df_keys:
                await redis_conn.close()
                return None

            # Retrieve DataFrames
            dataframes = {}
            for df_key in df_keys:
                df_json = await redis_conn.hget(key, df_key)
                if df_json:
                    df_data = json_decoder(df_json)
                    dataframes[df_key] = pd.DataFrame.from_records(df_data)

            await redis_conn.close()
            return dataframes or None

        except Exception as e:
            self.logger.error(f"Error retrieving cache: {e}")
            return None

    async def _cache_data(
        self,
        agent_name: str,
        dataframes: Dict[str, pd.DataFrame],
        cache_expiration: int
    ) -> None:
        """Cache DataFrames in Redis."""
        try:
            if not dataframes:
                return

            redis_conn = await self._get_redis_connection()
            key = f"agent_{agent_name}"

            # Clear existing cache
            await redis_conn.delete(key)

            # Store DataFrames
            for df_key, df in dataframes.items():
                df_json = json_encoder(df.to_dict(orient='records'))
                await redis_conn.hset(key, df_key, df_json)

            # Set expiration
            expiration = timedelta(hours=cache_expiration)
            await redis_conn.expire(key, int(expiration.total_seconds()))

            self.logger.info(
                f"Cached data for agent {agent_name} "
                f"(expires in {cache_expiration}h)"
            )

            await redis_conn.close()

        except Exception as e:
            self.logger.error(f"Error caching data: {e}")

    async def _call_qs(self, queries: List[str]) -> Dict[str, pd.DataFrame]:
        """Execute QuerySource queries (Resilient)."""
        from querysource.queries.qs import QS
        dfs = {}
        for query in queries:
            if not isinstance(query, str):
                self.logger.error(f"Query {query} is not a string, skipping.")
                continue
            
            self.logger.info(f'EXECUTING QUERY SOURCE: {query}')
            try:
                qy = QS(slug=query)
                df, error = await qy.query(output_format='pandas')

                if error:
                    self.logger.error(f"Query {query} failed: {error}")
                    continue

                if not isinstance(df, pd.DataFrame):
                    self.logger.error(f"Query {query} did not return a DataFrame")
                    continue

                dfs[query] = df

            except Exception as e:
                self.logger.error(f"Failed to load query {query}: {e}")
                continue

        return dfs

    async def _call_multiquery(self, query: dict) -> Dict[str, pd.DataFrame]:
        """Execute MultiQuery queries."""
        from querysource.queries.multi import MultiQS
        _queries = query.pop('queries', {})
        _files = query.pop('files', {})

        if not _queries and not _files:
            raise ValueError("Queries or files are required")

        try:
            qs = MultiQS(
                slug=[],
                queries=_queries,
                files=_files,
                query=query,
                conditions={},
                return_all=True
            )
            result, _ = await qs.execute()

        except Exception as e:
            raise ValueError(f"Error executing MultiQuery: {e}") from e

        if not isinstance(result, dict):
            raise ValueError("MultiQuery did not return a dictionary")

        return result

    async def _execute_query(self, query: Union[list, dict, str]) -> Dict[str, pd.DataFrame]:
        """Execute query and return DataFrames."""
        if self._query_loader:
             # Support external loader (mainly for testing or overrides)
             if isinstance(query, str):
                 query = [query]
             return await self._query_loader(query)

        if isinstance(query, dict):
            return await self._call_multiquery(query)
        elif isinstance(query, (str, list)):
            if isinstance(query, str):
                query = [query]
            return await self._call_qs(query)
        else:
            raise ValueError(f"Expected list or dict, got {type(query)}")

    async def load_data(
        self,
        query: Union[List[str], Dict, str],
        agent_name: str,
        refresh: bool = False,
        cache_expiration: int = 48,
        no_cache: bool = False,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        Generate DataFrames from queries with Redis caching support.
        Replaces PandasAgent.gen_data.
        """
        # Try cache first
        if not refresh and not no_cache:
            cached_dfs = await self._get_cached_data(agent_name)
            if cached_dfs:
                self.logger.info(f"Using cached data for agent {agent_name}")
                # Add to manager
                for name, df in cached_dfs.items():
                    self.add_dataframe(name, df, is_active=True)
                return cached_dfs

        self.logger.info(f'GENERATING DATA FOR QUERY: {query}')
        # Generate data
        dfs = await self._execute_query(query)

        # Cache if enabled
        if not no_cache:
            await self._cache_data(agent_name, dfs, cache_expiration)

        # Add to manager
        for name, df in dfs.items():
            self.add_dataframe(name, df, is_active=True)

        return dfs
