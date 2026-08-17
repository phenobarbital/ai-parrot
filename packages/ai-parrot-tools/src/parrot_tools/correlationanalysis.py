"""
Correlation Analysis Tool - Analyze correlations between a key column and other columns.

FEAT-423: matplotlib/seaborn replaced with altair. Heatmap and bar chart
outputs are Vega-Lite JSON specs the frontend renders natively, instead of
base64-encoded PNG images.
"""
from typing import Any, ClassVar, Dict, Optional, List
from enum import Enum
from pathlib import Path
from datetime import datetime
import json
import altair as alt
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field
from .abstract import AbstractTool


class CorrelationMethod(str, Enum):
    """Available correlation methods."""
    PEARSON = "pearson"
    SPEARMAN = "spearman"
    KENDALL = "kendall"


class OutputFormat(str, Enum):
    """Available output formats."""
    JSON = "json"
    DATAFRAME = "dataframe"
    HEATMAP = "heatmap"
    ALL = "all"


class CorrelationAnalysisArgs(BaseModel):
    """Arguments schema for Correlation Analysis."""

    dataframe: Any = Field(
        description="Pandas DataFrame to analyze"
    )
    key_column: str = Field(
        description="Column name to use as the key for correlation comparison"
    )
    comparison_columns: Optional[List[str]] = Field(
        default=None,
        description="List of column names to compare with key column. If None, uses all numeric columns except key column"
    )
    correlation_method: CorrelationMethod = Field(
        default=CorrelationMethod.PEARSON,
        description="Correlation method to use: pearson, spearman, or kendall"
    )
    output_format: OutputFormat = Field(
        default=OutputFormat.ALL,
        description="Output format: json, dataframe, heatmap, or all"
    )
    min_correlation_threshold: float = Field(
        default=0.0,
        description="Minimum absolute correlation value to include in results"
    )
    sort_by_correlation: bool = Field(
        default=True,
        description="Sort results by absolute correlation value (descending)"
    )
    exclude_self_correlation: bool = Field(
        default=True,
        description="Exclude the key column from correlation with itself"
    )
    filename: Optional[str] = Field(
        default=None,
        description="Optional filename to save the heatmap Vega-Lite spec as JSON (without extension)"
    )
    heatmap_style: str = Field(
        default="coolwarm",
        description="Vega-Lite color scheme for the heatmap: coolwarm (mapped "
                     "to 'redblue'), viridis, plasma, turbo, etc. — see "
                     "https://vega.github.io/vega/docs/schemes/"
    )
    figure_size: tuple = Field(
        default=(10, 8),
        description="Figure size for heatmap (width, height)"
    )


class CorrelationAnalysisTool(AbstractTool):
    """
    Tool for analyzing correlations between a key column and other columns in a DataFrame.

    This tool helps identify relationships between a target variable and potential
    predictor variables, useful for business analytics, feature selection, and
    exploratory data analysis.
    """

    name: str = "correlation_analysis"
    description: str = "Analyze correlations between a key column and other columns in a DataFrame"
    args_schema = CorrelationAnalysisArgs
    return_direct: bool = False

    # matplotlib/seaborn colormap names -> closest Vega-Lite scheme
    # (FEAT-423). Names not in this map (viridis, plasma, turbo, ...) are
    # already valid Vega-Lite scheme names and pass through unchanged.
    _CMAP_TO_VEGA_SCHEME: ClassVar[Dict[str, str]] = {
        "coolwarm": "redblue",
        "RdYlBu_r": "redyellowblue",
        "RdYlGn": "redyellowgreen",
        "bwr": "blueorange",
    }

    def _default_output_dir(self) -> Optional[Path]:
        """Default output directory for correlation analysis results."""
        return self.static_dir / "correlation_analysis" if self.static_dir else None

    def _calculate_correlations(
        self,
        df: pd.DataFrame,
        key_column: str,
        comparison_columns: List[str],
        method: str
    ) -> pd.Series:
        """
        Calculate correlations between key column and comparison columns.

        Args:
            df: DataFrame to analyze
            key_column: Key column name
            comparison_columns: List of columns to compare with
            method: Correlation method

        Returns:
            Series with correlation values
        """
        correlations = {}
        key_data = df[key_column]

        for col in comparison_columns:
            try:
                # Skip if column doesn't exist
                if col not in df.columns:
                    self.logger.warning(f"Column '{col}' not found in DataFrame")
                    continue

                # Skip non-numeric columns for pearson correlation
                if method == 'pearson' and not pd.api.types.is_numeric_dtype(df[col]):
                    self.logger.info(f"Skipping non-numeric column '{col}' for Pearson correlation")
                    continue

                # Calculate correlation
                corr_value = key_data.corr(df[col], method=method)

                # Handle NaN correlations
                if pd.isna(corr_value):
                    self.logger.warning(f"Correlation between '{key_column}' and '{col}' is NaN")
                    correlations[col] = 0.0
                else:
                    correlations[col] = corr_value

            except Exception as e:
                self.logger.error(f"Error calculating correlation for column '{col}': {e}")
                correlations[col] = 0.0

        return pd.Series(correlations)

    def _create_correlation_heatmap(
        self,
        correlations: pd.Series,
        key_column: str,
        style: str = "coolwarm",
        figure_size: tuple = (10, 8)
    ) -> Dict[str, Any]:
        """
        Create a correlation heatmap using altair (FEAT-423).

        Args:
            correlations: Series with correlation values
            key_column: Name of the key column
            style: Vega-Lite color scheme (matplotlib/seaborn cmap names are
                translated via ``_CMAP_TO_VEGA_SCHEME``)
            figure_size: Figure size tuple (used to scale chart dimensions)

        Returns:
            Vega-Lite JSON spec (dict) for the heatmap, or ``{}`` on error.
        """
        try:
            heatmap_df = pd.DataFrame({
                "key": key_column,
                "variable": correlations.index,
                "correlation": correlations.values,
            })

            scheme = self._CMAP_TO_VEGA_SCHEME.get(style, style)
            chart = alt.Chart(heatmap_df).mark_rect().encode(
                x=alt.X("variable:N", title="Variables", sort=None),
                y=alt.Y("key:N", title="Key Variable"),
                color=alt.Color(
                    "correlation:Q",
                    scale=alt.Scale(scheme=scheme, domain=[-1, 1]),
                    legend=alt.Legend(title="Correlation Coefficient"),
                ),
                tooltip=["variable", alt.Tooltip("correlation:Q", format=".3f")],
            ).properties(
                title=f"Correlation Analysis: {key_column} vs Other Variables",
                width=min(60 * max(len(correlations), 1), int(figure_size[0] * 80)),
                height=int(figure_size[1] * 15),
            )

            return chart.to_dict()

        except Exception as e:
            self.logger.error(f"Error creating heatmap: {e}")
            return {}

    def _create_bar_chart(
        self,
        correlations: pd.Series,
        key_column: str,
        figure_size: tuple = (12, 6)
    ) -> Dict[str, Any]:
        """
        Create a bar chart of correlations using altair (FEAT-423).

        Args:
            correlations: Series with correlation values
            key_column: Name of the key column
            figure_size: Figure size tuple (used to scale chart dimensions)

        Returns:
            Vega-Lite JSON spec (dict) for the bar chart, or ``{}`` on error.
        """
        try:
            # Sort by absolute correlation value
            sorted_corr = correlations.reindex(
                correlations.abs().sort_values(ascending=True).index
            )

            bar_df = pd.DataFrame({
                "variable": sorted_corr.index,
                "correlation": sorted_corr.values,
            })

            chart = alt.Chart(bar_df).mark_bar().encode(
                y=alt.Y("variable:N", sort=None, title=None),
                x=alt.X("correlation:Q", title="Correlation Coefficient"),
                color=alt.condition(
                    alt.datum.correlation < 0,
                    alt.value("#E74C3C"),
                    alt.value("#4A90D9"),
                ),
                tooltip=["variable", alt.Tooltip("correlation:Q", format=".3f")],
            ).properties(
                title=f"Correlation Analysis: {key_column} vs Other Variables",
                width=int(figure_size[0] * 40),
                height=max(200, 25 * len(sorted_corr)),
            )

            return chart.to_dict()

        except Exception as e:
            self.logger.error(f"Error creating bar chart: {e}")
            return {}

    async def _execute(
        self,
        dataframe: pd.DataFrame,
        key_column: str,
        comparison_columns: Optional[List[str]] = None,
        correlation_method: CorrelationMethod = CorrelationMethod.PEARSON,
        output_format: OutputFormat = OutputFormat.ALL,
        min_correlation_threshold: float = 0.0,
        sort_by_correlation: bool = True,
        exclude_self_correlation: bool = True,
        filename: Optional[str] = None,
        heatmap_style: str = "coolwarm",
        figure_size: tuple = (10, 8),
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute correlation analysis.

        Returns:
            Dictionary containing correlation results in requested formats
        """

        # Validate input
        if not isinstance(dataframe, pd.DataFrame):
            raise ValueError("Input must be a pandas DataFrame")

        if dataframe.empty:
            raise ValueError("DataFrame is empty")

        if key_column not in dataframe.columns:
            raise ValueError(f"Key column '{key_column}' not found in DataFrame")

        # Check if key column is numeric for pearson correlation
        if correlation_method == CorrelationMethod.PEARSON and not pd.api.types.is_numeric_dtype(dataframe[key_column]):
            raise ValueError(f"Key column '{key_column}' must be numeric for Pearson correlation")

        self.logger.info(f"Starting correlation analysis for key column: {key_column}")

        # Determine comparison columns
        if comparison_columns is None:
            # Use all numeric columns except the key column
            numeric_columns = dataframe.select_dtypes(include=[np.number]).columns.tolist()
            comparison_columns = [col for col in numeric_columns if col != key_column]
            self.logger.info(f"Using all numeric columns except key: {len(comparison_columns)} columns")
        else:
            # Validate provided columns
            missing_columns = [col for col in comparison_columns if col not in dataframe.columns]
            if missing_columns:
                raise ValueError(f"Columns not found in DataFrame: {missing_columns}")

        # Exclude self-correlation if requested
        if exclude_self_correlation and key_column in comparison_columns:
            comparison_columns = [col for col in comparison_columns if col != key_column]

        if not comparison_columns:
            raise ValueError("No valid comparison columns found")

        # Calculate correlations
        correlations = self._calculate_correlations(
            dataframe, key_column, comparison_columns, correlation_method.value
        )

        # Apply minimum threshold filter
        if min_correlation_threshold > 0:
            correlations = correlations[correlations.abs() >= min_correlation_threshold]
            self.logger.info(f"Filtered to {len(correlations)} correlations above threshold {min_correlation_threshold}")

        # Sort by correlation if requested
        if sort_by_correlation:
            correlations = correlations.reindex(correlations.abs().sort_values(ascending=False).index)

        # Generate timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Prepare base result
        result = {
            "key_column": key_column,
            "correlation_method": correlation_method.value,
            "comparison_columns_count": len(comparison_columns),
            "valid_correlations_count": len(correlations),
            "timestamp": timestamp,
            "analysis_summary": {
                "highest_positive_correlation": {
                    "column": correlations.idxmax() if len(correlations) > 0 else None,
                    "value": correlations.max() if len(correlations) > 0 else None
                },
                "highest_negative_correlation": {
                    "column": correlations.idxmin() if len(correlations) > 0 else None,
                    "value": correlations.min() if len(correlations) > 0 else None
                },
                "mean_absolute_correlation": correlations.abs().mean() if len(correlations) > 0 else 0,
                "strong_correlations_count": len(correlations[correlations.abs() >= 0.7]) if len(correlations) > 0 else 0
            }
        }

        # Generate outputs based on requested format
        if output_format in [OutputFormat.JSON, OutputFormat.ALL]:
            result["json_output"] = {
                "correlations": correlations.to_dict(),
                "sorted_correlations": [
                    {"column": col, "correlation": float(corr)}
                    for col, corr in correlations.items()
                ]
            }

        if output_format in [OutputFormat.DATAFRAME, OutputFormat.ALL]:
            correlation_df = pd.DataFrame({
                'column': correlations.index,
                'correlation': correlations.values,
                'abs_correlation': correlations.abs().values
            }).reset_index(drop=True)

            result["dataframe_output"] = {
                "correlation_dataframe": correlation_df.to_dict('records'),
                "dataframe_shape": correlation_df.shape,
                "dataframe_html": correlation_df.to_html(classes='correlation-table', table_id='correlation-results')
            }

        if output_format in [OutputFormat.HEATMAP, OutputFormat.ALL]:
            # Create heatmap
            heatmap_spec = self._create_correlation_heatmap(
                correlations, key_column, heatmap_style, figure_size
            )

            # Create bar chart
            bar_chart_spec = self._create_bar_chart(correlations, key_column, figure_size)

            result["heatmap_output"] = {
                # Vega-Lite JSON specs (FEAT-423) — the frontend renders
                # these natively; no base64 image bytes are produced.
                "heatmap_vegalite": heatmap_spec,
                "bar_chart_vegalite": bar_chart_spec,
                "heatmap_style": heatmap_style,
                "figure_size": figure_size
            }

            # Save heatmap spec to file if filename provided
            if filename and heatmap_spec:
                try:
                    if not filename.endswith('.json'):
                        filename = f"{filename}_{timestamp}.json"

                    # Ensure output directory exists
                    if self.output_dir:
                        self.output_dir.mkdir(parents=True, exist_ok=True)
                        file_path = self.output_dir / filename
                    else:
                        file_path = Path(filename)

                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(heatmap_spec, f, indent=2)

                    self.logger.info(f"Heatmap Vega-Lite spec saved to: {file_path}")

                    result["heatmap_output"].update({
                        "file_path": str(file_path),
                        "file_url": self.to_static_url(file_path),
                        "file_size": file_path.stat().st_size
                    })

                except Exception as e:
                    self.logger.error(f"Failed to save heatmap: {e}")
                    result["heatmap_output"]["save_error"] = str(e)

        return result
