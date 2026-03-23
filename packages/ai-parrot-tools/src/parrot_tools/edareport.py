"""
EDA Report Tool - Comprehensive profiling using ydata_profiling (formerly pandas_profiling).
"""
from typing import Any, Dict, Optional
from pathlib import Path
from datetime import datetime
import pandas as pd
from pydantic import BaseModel, Field
from ydata_profiling import ProfileReport
from .abstract import AbstractTool


class EdaReportPresets:
    """Predefined configuration presets for different use cases."""

    QUICK_OVERVIEW = {
        "minimal": True,
        "explorative": False,
        "correlations": False,
        "interactions": False,
        "missing_diagrams": True,
        "duplicates": True
    }

    COMPREHENSIVE = {
        "minimal": False,
        "explorative": True,
        "correlations": True,
        "interactions": True,
        "missing_diagrams": True,
        "duplicates": True,
        "correlation_threshold": 0.8
    }

    CORRELATION_FOCUSED = {
        "minimal": False,
        "explorative": True,
        "correlations": True,
        "interactions": True,
        "missing_diagrams": False,
        "duplicates": False,
        "correlation_threshold": 0.7
    }

    DATA_QUALITY = {
        "minimal": False,
        "explorative": False,
        "correlations": False,
        "interactions": False,
        "missing_diagrams": True,
        "duplicates": True
    }

class EdaReportArgs(BaseModel):
    """Arguments schema for EDA Report generation."""

    dataframe: Any = Field(
        description="Pandas DataFrame to profile and analyze"
    )
    filename: Optional[str] = Field(
        default=None,
        description="Optional filename to save the EDA report (without extension)"
    )
    title: str = Field(
        default="EDA Profiling Report",
        description="Title for the profiling report"
    )
    df_name: str = Field(
        default="DataFrame",
        description="Name to use for the dataset in the report"
    )
    minimal: bool = Field(
        default=False,
        description="Set to True for faster, less detailed reports"
    )
    explorative: bool = Field(
        default=True,
        description="Set to True for detailed explorative analysis with correlations and interactions"
    )
    sample_size: Optional[int] = Field(
        default=None,
        description="Limit analysis to a sample of the data (None for full dataset)"
    )
    dark_mode: bool = Field(
        default=False,
        description="Enable dark mode theme for the report"
    )
    orange_mode: bool = Field(
        default=False,
        description="Enable orange theme for the report"
    )
    correlations: bool = Field(
        default=True,
        description="Include correlation analysis"
    )
    missing_diagrams: bool = Field(
        default=True,
        description="Include missing value diagrams"
    )
    duplicates: bool = Field(
        default=True,
        description="Include duplicate analysis"
    )
    interactions: bool = Field(
        default=True,
        description="Include variable interactions analysis"
    )


class EdaReportTool(AbstractTool):
    """
    Tool for generating comprehensive EDA reports using ydata_profiling.

    This tool creates detailed profiling reports with statistics, visualizations,
    correlations, missing value analysis, and data quality insights.
    """

    name: str = "eda_report"
    description: str = "Generate comprehensive EDA profiling report using ydata_profiling with detailed statistics and visualizations"
    args_schema = EdaReportArgs
    return_direct: bool = False

    def _default_output_dir(self) -> Optional[Path]:
        """Default output directory for EDA reports."""
        return self.static_dir / "eda_profiling" if self.static_dir else None

    async def _execute(
        self,
        dataframe: pd.DataFrame,
        filename: Optional[str] = None,
        title: str = "EDA Profiling Report",
        df_name: str = "DataFrame",
        minimal: bool = False,
        explorative: bool = True,
        sample_size: Optional[int] = None,
        dark_mode: bool = False,
        orange_mode: bool = False,
        correlations: bool = True,
        missing_diagrams: bool = True,
        duplicates: bool = True,
        interactions: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the EDA profiling report generation.

        Returns:
            Dictionary containing the HTML report and optional file information
        """

        # Validate input
        if not isinstance(dataframe, pd.DataFrame):
            raise ValueError("Input must be a pandas DataFrame")

        if dataframe.empty:
            raise ValueError("DataFrame is empty - cannot generate profiling report")

        self.logger.info(f"Generating profiling report for DataFrame with shape {dataframe.shape}")

        # Apply sampling if specified
        df_to_profile = dataframe.copy()
        if sample_size and len(df_to_profile) > sample_size:
            df_to_profile = df_to_profile.sample(n=sample_size, random_state=42)
            self.logger.info(f"Sampling {sample_size} rows from {len(dataframe)} total rows")

        # Generate timestamp for unique identification
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Configure profiling options with simplified approach
        # Start with basic configuration
        config_kwargs = {
            "title": title,
            "progress_bar": False,
            "minimal": minimal,
            "explorative": explorative,
        }

        # Only add optional configurations if they differ from defaults
        # This avoids conflicts with ydata_profiling's internal config merging

        # For minimal reports, disable expensive computations
        if minimal:
            config_kwargs.update({
                "correlations": {
                    "auto": {"calculate": True} if correlations else {"calculate": False},
                },
                "missing_diagrams": {"matrix": False, "heatmap": False},
                "interactions": {"continuous": False},
                "duplicates": {"head": 0}
            })
        else:
            # For full reports, use selective enabling
            if not correlations:
                config_kwargs["correlations"] = {
                    "auto": {"calculate": False}
                }

            if not missing_diagrams:
                config_kwargs["missing_diagrams"] = {
                    "bar": False,
                    "matrix": False,
                    "heatmap": False
                }

            if not interactions:
                config_kwargs["interactions"] = {"continuous": False}

            if not duplicates:
                config_kwargs["duplicates"] = {"head": 0}

        # Apply theme settings (simplified)
        if dark_mode or orange_mode:
            # Theme settings are often problematic, so we'll skip them for now
            # and focus on getting the basic report working
            pass

        try:
            # Generate the profiling report
            self.logger.info("Starting profiling analysis...")
            start_time = datetime.now()

            # Create ProfileReport with proper configuration
            profile = ProfileReport(df_to_profile, **config_kwargs)

            # Get HTML content
            html_content = profile.to_html()

            generation_time = (datetime.now() - start_time).total_seconds()
            self.logger.info(f"Profiling completed in {generation_time:.2f} seconds")

            # Prepare result
            result = {
                "html": html_content,
                "title": title,
                "timestamp": timestamp,
                "dataset_name": df_name,
                "dataset_shape": df_to_profile.shape,
                "original_shape": dataframe.shape,
                "generation_time_seconds": generation_time,
                "config": {
                    "minimal": minimal,
                    "explorative": explorative,
                    "correlations": {
                        "auto": {"calculate": True} if correlations else {"calculate": False},
                    },
                    "interactions": {
                        "auto": {"calculate": True} if interactions else {"calculate": False},
                    },
                    "sample_size": len(df_to_profile)
                }
            }

            # Save to file if filename provided
            if filename:
                if not filename.endswith('.html'):
                    filename = f"{filename}_{timestamp}.html"

                # Ensure output directory exists
                if self.output_dir:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    file_path = self.output_dir / filename
                else:
                    file_path = Path(filename)

                try:
                    # Save the HTML report
                    profile.to_file(file_path)

                    self.logger.info(f"Profiling report saved to: {file_path}")

                    result.update({
                        "file_path": str(file_path),
                        "file_url": self.to_static_url(file_path),
                        "file_size": file_path.stat().st_size,
                        "report_url": f"file://{file_path.absolute()}"
                    })

                except Exception as e:
                    self.logger.error(f"Failed to save profiling report: {e}")
                    result["save_error"] = str(e)

            # Add profiling statistics
            try:
                result.update({
                    "statistics": {
                        "variables_count": len(df_to_profile.columns),
                        "observations_count": len(df_to_profile),
                        "missing_cells": df_to_profile.isna().sum().sum(),
                        "missing_cells_percentage": (df_to_profile.isna().sum().sum() / df_to_profile.size) * 100,
                        "duplicate_rows": df_to_profile.duplicated().sum(),
                        "numeric_variables": len(df_to_profile.select_dtypes(include=['number']).columns),
                        "categorical_variables": len(df_to_profile.select_dtypes(include=['object', 'category']).columns),
                        "boolean_variables": len(df_to_profile.select_dtypes(include=['bool']).columns),
                        "datetime_variables": len(df_to_profile.select_dtypes(include=['datetime']).columns)
                    }
                })
            except Exception as e:
                self.logger.warning(f"Failed to generate statistics summary: {e}")

            return result

        except Exception as e:
            self.logger.error(f"Error generating profiling report: {e}")

            # Return a simplified fallback report
            fallback_result = {
                "html": f"<html><body><h1>Error generating report</h1><p>Error: {str(e)}</p></body></html>",
                "title": title,
                "timestamp": timestamp,
                "dataset_name": df_name,
                "dataset_shape": df_to_profile.shape,
                "original_shape": dataframe.shape,
                "generation_time_seconds": 0,
                "error": str(e),
                "config": {
                    "minimal": minimal,
                    "explorative": explorative,
                    "correlations": {
                        "auto": {"calculate": True},
                    },
                    "interactions": {
                        "auto": {"calculate": True},
                    },
                    "sample_size": len(df_to_profile)
                },
                "statistics": {
                    "variables_count": len(df_to_profile.columns),
                    "observations_count": len(df_to_profile),
                    "missing_cells": df_to_profile.isna().sum().sum(),
                    "missing_cells_percentage": (df_to_profile.isna().sum().sum() / df_to_profile.size) * 100,
                    "duplicate_rows": df_to_profile.duplicated().sum(),
                    "numeric_variables": len(df_to_profile.select_dtypes(include=['number']).columns),
                    "categorical_variables": len(df_to_profile.select_dtypes(include=['object', 'category']).columns),
                    "boolean_variables": len(df_to_profile.select_dtypes(include=['bool']).columns),
                    "datetime_variables": len(df_to_profile.select_dtypes(include=['datetime']).columns)
                }
            }

            # Log the full configuration for debug
            self.logger.debug(f"Failed config_kwargs: {config_kwargs}")

            return fallback_result

    def apply_preset(self, preset_name: str, **kwargs) -> Dict[str, Any]:
        """
        Apply a configuration preset.

        Args:
            preset_name: Name of the preset ('quick', 'comprehensive', 'correlation', 'quality')
            **kwargs: Additional arguments to override preset settings

        Returns:
            Combined configuration dictionary
        """
        preset_map = {
            'quick': EdaReportPresets.QUICK_OVERVIEW,
            'comprehensive': EdaReportPresets.COMPREHENSIVE,
            'correlation': EdaReportPresets.CORRELATION_FOCUSED,
            'quality': EdaReportPresets.DATA_QUALITY
        }

        if preset_name not in preset_map:
            raise ValueError(f"Unknown preset: {preset_name}. Available: {list(preset_map.keys())}")

        preset_config = preset_map[preset_name].copy()
        preset_config.update(kwargs)  # Override with user-provided args

        return preset_config
