"""
Correlation Analysis Tool - Analyze correlations between a key column and other columns.
"""
from typing import Any, Dict, Optional, List
from enum import Enum
from pathlib import Path
from datetime import datetime
import base64
import io
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field
from .abstract import AbstractTool


matplotlib.use('Agg')  # Use non-interactive backend


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
        description="Optional filename to save the heatmap (without extension)"
    )
    heatmap_style: str = Field(
        default="coolwarm",
        description="Color map for heatmap: coolwarm, viridis, plasma, etc."
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
    ) -> str:
        """
        Create a correlation heatmap.

        Args:
            correlations: Series with correlation values
            key_column: Name of the key column
            style: Color map style
            figure_size: Figure size tuple

        Returns:
            Base64 encoded image string
        """
        try:
            # Create figure
            fig, ax = plt.subplots(figsize=figure_size)

            # Prepare data for heatmap
            # Create a matrix with key column vs other columns
            corr_matrix = correlations.to_frame(name=key_column).T

            # Create heatmap
            sns.heatmap(
                corr_matrix,
                annot=True,
                cmap=style,
                center=0,
                fmt='.3f',
                cbar_kws={'label': 'Correlation Coefficient'},
                ax=ax
            )

            ax.set_title(f'Correlation Analysis: {key_column} vs Other Variables',
                        fontsize=14, fontweight='bold', pad=20)
            ax.set_xlabel('Variables', fontsize=12)
            ax.set_ylabel('Key Variable', fontsize=12)

            # Rotate x-axis labels for better readability
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()

            # Convert to base64
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')
            buf.close()
            plt.close(fig)

            return img_base64

        except Exception as e:
            self.logger.error(f"Error creating heatmap: {e}")
            return ""

    def _create_bar_chart(
        self,
        correlations: pd.Series,
        key_column: str,
        figure_size: tuple = (12, 6)
    ) -> str:
        """
        Create a bar chart of correlations.

        Args:
            correlations: Series with correlation values
            key_column: Name of the key column
            figure_size: Figure size tuple

        Returns:
            Base64 encoded image string
        """
        try:
            # Sort by absolute correlation value
            sorted_corr = correlations.reindex(
                correlations.abs().sort_values(ascending=True).index
            )

            # Create figure
            fig, ax = plt.subplots(figsize=figure_size)

            # Create bar chart
            colors = ['red' if x < 0 else 'blue' for x in sorted_corr.values]
            bars = ax.barh(range(len(sorted_corr)), sorted_corr.values, color=colors, alpha=0.7)

            # Customize chart
            ax.set_yticks(range(len(sorted_corr)))
            ax.set_yticklabels(sorted_corr.index)
            ax.set_xlabel('Correlation Coefficient')
            ax.set_title(f'Correlation Analysis: {key_column} vs Other Variables',
                        fontsize=14, fontweight='bold')
            ax.axvline(x=0, color='black', linestyle='-', alpha=0.3)
            ax.grid(True, alpha=0.3)

            # Add value labels on bars
            for i, (bar, value) in enumerate(zip(bars, sorted_corr.values)):
                ax.text(value + (0.01 if value >= 0 else -0.01), i, f'{value:.3f}',
                       ha='left' if value >= 0 else 'right', va='center')

            plt.tight_layout()

            # Convert to base64
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')
            buf.close()
            plt.close(fig)

            return img_base64

        except Exception as e:
            self.logger.error(f"Error creating bar chart: {e}")
            return ""

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
            heatmap_b64 = self._create_correlation_heatmap(
                correlations, key_column, heatmap_style, figure_size
            )

            # Create bar chart
            bar_chart_b64 = self._create_bar_chart(correlations, key_column, figure_size)

            result["heatmap_output"] = {
                "heatmap_image": heatmap_b64,
                "bar_chart_image": bar_chart_b64,
                "heatmap_style": heatmap_style,
                "figure_size": figure_size
            }

            # Save heatmap to file if filename provided
            if filename and heatmap_b64:
                try:
                    if not filename.endswith('.png'):
                        filename = f"{filename}_{timestamp}.png"

                    # Ensure output directory exists
                    if self.output_dir:
                        self.output_dir.mkdir(parents=True, exist_ok=True)
                        file_path = self.output_dir / filename
                    else:
                        file_path = Path(filename)

                    # Decode and save image
                    img_data = base64.b64decode(heatmap_b64)
                    with open(file_path, 'wb') as f:
                        f.write(img_data)

                    self.logger.info(f"Heatmap saved to: {file_path}")

                    result["heatmap_output"].update({
                        "file_path": str(file_path),
                        "file_url": self.to_static_url(file_path),
                        "file_size": file_path.stat().st_size
                    })

                except Exception as e:
                    self.logger.error(f"Failed to save heatmap: {e}")
                    result["heatmap_output"]["save_error"] = str(e)

        return result
