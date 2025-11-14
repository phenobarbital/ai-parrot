"""Metadata tool for describing DataFrame schemas to the LLM."""
from typing import Any, Dict, Optional
from pydantic import Field
import numpy as np
import pandas as pd
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class MetadataToolArgs(AbstractToolArgsSchema):
    """Arguments for the MetadataTool."""

    dataframe: Optional[str] = Field(
        default=None,
        description="Name of the DataFrame to inspect"
    )
    column: Optional[str] = Field(
        default=None,
        description="Specific column within the DataFrame to describe"
    )
    include_eda: bool = Field(
        default=True,
        description="Add Exploratory data analysis summary (statistics, missing values, memory usage)"
    )
    include_samples: bool = Field(
        default=True,
        description="Include sample rows from the DataFrame"
    )
    include_column_stats: bool = Field(
        default=False,
        description="Include detailed statistics for numeric and categorical columns"
    )



class MetadataTool(AbstractTool):
    """
    Expose DataFrame metadata with comprehensive EDA capabilities.

    Provides:
    - DataFrame schemas (columns, dtypes, shapes)
    - EDA summaries (row counts, column types, missing values, memory usage)
    - Sample rows for quick data inspection
    - Detailed column statistics (optional)
    """

    name = "dataframe_metadata"
    description = (
        "Retrieve comprehensive metadata about a single DataFrame including schema, "
        "exploratory data analysis (EDA) statistics, column descriptions, and sample rows. "
        "Use this tool to understand DataFrame structure, data types, missing values, "
        "and basic statistics before performing analysis. Call this tool for one DataFrame at a time."
    )
    args_schema = MetadataToolArgs

    def __init__(
        self,
        metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        alias_map: Optional[Dict[str, str]] = None,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,
        **kwargs
    ) -> None:
        """
        Initialize MetadataTool.

        Args:
            metadata: Pre-computed metadata dictionary
            alias_map: Mapping of DataFrame names to standardized aliases (df1, df2, etc.)
            dataframes: Reference to actual DataFrames for dynamic EDA generation
            **kwargs: Additional tool configuration
        """
        super().__init__(**kwargs)
        self.metadata: Dict[str, Dict[str, Any]] = metadata or {}
        self.alias_map: Dict[str, str] = alias_map or {}
        self.dataframes: Dict[str, pd.DataFrame] = dataframes or {}

    def update_metadata(
        self,
        metadata: Dict[str, Dict[str, Any]],
        alias_map: Optional[Dict[str, str]] = None,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None
    ) -> None:
        """
        Update the internal metadata dictionary, alias map, and dataframes.

        Args:
            metadata: New metadata dictionary
            alias_map: New alias mapping
            dataframes: New DataFrame references
        """
        self.metadata = metadata or {}
        self.alias_map = alias_map or {}
        if dataframes is not None:
            self.dataframes = dataframes

    async def _execute(
        self,
        dataframe: Optional[str] = None,
        column: Optional[str] = None,
        include_eda: bool = True,
        include_samples: bool = True,
        include_column_stats: bool = False,
        **_: Any
    ) -> ToolResult:
        """
        Execute metadata retrieval with optional EDA generation.

        Args:
            dataframe: Name or alias of the DataFrame to inspect
            column: Specific column to describe
            include_eda: Generate EDA summary dynamically
            include_samples: Include sample rows
            include_column_stats: Include detailed column statistics

        Returns:
            ToolResult with metadata and optional EDA information
        """
        if not self.metadata:
            return ToolResult(
                status="success",
                result={"message": "No metadata available. No DataFrames are currently loaded."},
                metadata={"tool_name": self.name}
            )

        if dataframe:
            try:
                result = self._describe_dataframe(
                    dataframe,
                    column,
                    include_eda=include_eda,
                    include_samples=include_samples,
                    include_column_stats=include_column_stats
                )
            except ValueError as exc:
                return ToolResult(
                    status="error",
                    result=None,
                    error=str(exc),
                    metadata={
                        "tool_name": self.name,
                        "dataframe": dataframe,
                        "column": column
                    }
                )
        else:
            # List all available DataFrames
            result = self._list_available_dataframes()

        return ToolResult(
            status="success",
            result=result,
            metadata={
                "tool_name": self.name,
                "dataframe": dataframe,
                "column": column,
                "include_eda": include_eda
            }
        )

    def _list_available_dataframes(self) -> Dict[str, Any]:
        """List all available DataFrames with basic information."""
        return {
            "message": "Available DataFrames for analysis",
            "total_dataframes": len(self.metadata),
            "dataframes": [
                {
                    "name": name,
                    "standardized_name": self.alias_map.get(name),
                    "description": meta.get('description'),
                    "shape": meta.get('shape'),
                    "row_count": meta.get('row_count'),
                    "column_count": meta.get('column_count'),
                    "columns": list(meta.get('columns', {}).keys()),
                    "memory_mb": meta.get('memory_usage_mb')
                }
                for name, meta in self.metadata.items()
            ]
        }

    def _describe_dataframe(
        self,
        dataframe: str,
        column: Optional[str] = None,
        include_eda: bool = True,
        include_samples: bool = True,
        include_column_stats: bool = False
    ) -> Dict[str, Any]:
        """
        Describe a DataFrame and optionally a specific column.

        Args:
            dataframe: DataFrame name or alias
            column: Optional specific column to describe
            include_eda: Generate dynamic EDA summary
            include_samples: Include sample rows
            include_column_stats: Include detailed column statistics

        Returns:
            Comprehensive DataFrame or column description
        """
        df_name = self._resolve_dataframe_name(dataframe)
        df_meta = self.metadata.get(df_name)

        if not df_meta:
            raise ValueError(
                f"DataFrame '{dataframe}' metadata not found. "
                f"Available DataFrames: {list(self.metadata.keys())}"
            )

        # Handle single column request
        if column:
            return self._describe_column(df_name, column, df_meta)

        # Build comprehensive DataFrame description
        response = {
            "dataframe": df_name,
            "standardized_name": self.alias_map.get(df_name),
            "description": df_meta.get('description'),
            "shape": df_meta.get('shape'),
            "row_count": df_meta.get('row_count'),
            "column_count": df_meta.get('column_count'),
        }

        # Add pre-computed metadata fields
        response |= {
            key: value
            for key, value in df_meta.items()
            if key not in ['name', 'columns', 'sample_data', 'eda_summary']
        }

        # Include column information
        response['columns'] = df_meta.get('columns', {})

        # Generate dynamic EDA if requested
        if include_eda:
            if eda_summary := self._generate_eda_summary(df_name):
                # Override with dynamic EDA if available
                response['eda_summary'] = eda_summary

        # Include sample rows if requested
        if include_samples:
            if sample_data := df_meta.get('sample_data', []):
                response['sample_rows'] = sample_data

        # Include detailed column statistics if requested
        if include_column_stats:
            if column_stats := self._generate_column_statistics(df_name):
                response['column_statistics'] = column_stats

        return response

    def _describe_column(
        self,
        df_name: str,
        column: str,
        df_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Describe a specific column with detailed information.

        Args:
            df_name: DataFrame name
            column: Column name
            df_meta: DataFrame metadata

        Returns:
            Column description dictionary
        """
        column_meta = df_meta.get('columns', {}).get(column)

        if not column_meta:
            available_columns = list(df_meta.get('columns', {}).keys())
            raise ValueError(
                f"Column '{column}' not found in DataFrame '{df_name}'. "
                f"Available columns: {available_columns}"
            )

        response = {
            "dataframe": df_name,
            "standardized_name": self.alias_map.get(df_name),
            "column": column,
            "metadata": column_meta
        }

        # Add column-specific statistics if DataFrame is available
        df = self.dataframes.get(df_name)
        if df is not None and column in df.columns:
            response['statistics'] = self._compute_column_stats(df[column])

        return response

    def _generate_eda_summary(self, df_name: str) -> Optional[Dict[str, Any]]:
        """
        Generate comprehensive exploratory data analysis summary for a DataFrame.

        This method generates EDA statistics dynamically from the actual DataFrame
        if available, or falls back to pre-computed metadata.

        Args:
            df_name: DataFrame identifier

        Returns:
            Dictionary containing EDA summary or None if unavailable
        """
        df = self.dataframes.get(df_name)

        if df is None:
            # Fallback to pre-computed EDA if available
            df_meta = self.metadata.get(df_name, {})
            if 'eda_summary' in df_meta:
                return {"summary_text": df_meta['eda_summary']}
            return None

        # Generate fresh EDA from DataFrame
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns
        datetime_cols = df.select_dtypes(include=['datetime64']).columns

        # Missing data analysis
        missing = df.isnull().sum()
        total_missing = int(missing.sum())
        missing_percentage = float(missing.sum() / df.size * 100) if df.size > 0 else 0.0

        # Memory usage
        memory_mb = float(df.memory_usage(deep=True).sum() / 1024 / 1024)

        # Columns with missing values
        columns_with_missing = [
            {
                "column": col,
                "missing_count": int(missing[col]),
                "missing_percentage": float(missing[col] / len(df) * 100) if len(df) > 0 else 0.0
            }
            for col in df.columns
            if missing[col] > 0
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
                "duplicate_rows": int(df.duplicated().sum()),
                "completeness_percentage": round((1 - missing_percentage / 100) * 100, 2)
            }
        }

    def _generate_column_statistics(self, df_name: str) -> Optional[Dict[str, Any]]:
        """
        Generate detailed statistics for all columns in a DataFrame.

        Args:
            df_name: DataFrame identifier

        Returns:
            Dictionary with column statistics or None
        """
        df = self.dataframes.get(df_name)
        if df is None:
            return None

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns

        stats = {
            "numeric_columns": {},
            "categorical_columns": {}
        }

        # Numeric column statistics
        for col in numeric_cols:
            stats["numeric_columns"][col] = self._compute_column_stats(df[col])

        # Categorical column statistics
        for col in categorical_cols:
            value_counts = df[col].value_counts()
            stats["categorical_columns"][col] = {
                "unique_values": int(df[col].nunique()),
                "most_common": value_counts.head(10).to_dict(),
                "null_count": int(df[col].isnull().sum())
            }

        return stats

    def _compute_column_stats(self, series: pd.Series) -> Dict[str, Any]:
        """
        Compute statistics for a single column/series.

        Args:
            series: pandas Series to analyze

        Returns:
            Dictionary of column statistics
        """
        stats = {
            "dtype": str(series.dtype),
            "null_count": int(series.isnull().sum()),
            "null_percentage": round(float(series.isnull().sum() / len(series) * 100), 2) if len(series) > 0 else 0.0
        }

        if pd.api.types.is_numeric_dtype(series):
            # Numeric statistics
            stats |= {
                "mean": None if series.empty else float(series.mean()),
                "median": None if series.empty else float(series.median()),
                "std": None if series.empty else float(series.std()),
                "min": None if series.empty else float(series.min()),
                "max": None if series.empty else float(series.max()),
                "q25": None if series.empty else float(series.quantile(0.25)),
                "q75": None if series.empty else float(series.quantile(0.75)),
            }
        else:
            # Categorical/string statistics
            stats |= {
                "unique_values": int(series.nunique()),
                "most_common": None if series.mode().empty else str(series.mode().iloc[0]),
            }

        return stats

    def _resolve_dataframe_name(self, identifier: str) -> str:
        """
        Resolve either a standardized key (df1) or original name to metadata key.

        Args:
            identifier: DataFrame name or alias

        Returns:
            Resolved DataFrame name
        """
        # Direct match
        if identifier in self.metadata:
            return identifier

        # Alias match (df1 -> actual_name)
        for name, alias in self.alias_map.items():
            if alias == identifier:
                return name

        # Case-insensitive match
        identifier_lower = identifier.lower()
        return next(
            (
                name
                for name in self.metadata.keys()
                if name.lower() == identifier_lower
            ),
            identifier,
        )
