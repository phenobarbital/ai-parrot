"""
SeasonalDetectionTool for detecting stationarity in time series data using ADF and KPSS tests.
"""
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pydantic import BaseModel, Field, field_validator
# Statistical tests
from statsmodels.tsa.stattools import adfuller, kpss
from statsmodels.tsa.seasonal import seasonal_decompose
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
from .abstract import AbstractTool


class SeasonalDetectionArgs(BaseModel):
    """Arguments schema for SeasonalDetectionTool."""

    dataframe: Any = Field(
        description="Pandas DataFrame containing the time series data"
    )
    title: str = Field(
        description="Title for the analysis report"
    )
    time_column: str = Field(
        description="Name of the column containing time series data (dates/timestamps)"
    )
    value_column: str = Field(
        description="Name of the column containing the values to analyze for stationarity"
    )
    confidence_level: float = Field(
        default=0.05,
        description="Significance level for statistical tests (default: 0.05 for 95% confidence)"
    )
    maxlag: Optional[int] = Field(
        default=None,
        description="Maximum lag for ADF test. If None, automatically determined"
    )
    regression: str = Field(
        default='c',
        description="Regression type for ADF test: 'c' (constant), 'ct' (constant+trend), 'ctt' (constant+trend+trend^2), 'n' (no constant)"
    )
    nlags: Optional[int] = Field(
        default=None,
        description="Number of lags for KPSS test. If None, automatically determined"
    )
    generate_plots: bool = Field(
        default=True,
        description="Whether to generate visualization plots"
    )
    perform_decomposition: bool = Field(
        default=True,
        description="Whether to perform seasonal decomposition analysis"
    )
    remove_trend: bool = Field(
        default=False,
        description="Whether to test stationarity after detrending the data"
    )
    filename: Optional[str] = Field(
        default=None,
        description="Optional filename prefix for saving plots (without extension)"
    )

    @field_validator('confidence_level')
    @classmethod
    def validate_confidence_level(cls, v):
        if not 0 < v < 1:
            raise ValueError("Confidence level must be between 0 and 1")
        return v

    @field_validator('regression')
    @classmethod
    def validate_regression(cls, v):
        valid_types = ['c', 'ct', 'ctt', 'n']
        if v not in valid_types:
            raise ValueError(f"Regression type must be one of {valid_types}")
        return v


class SeasonalDetectionTool(AbstractTool):
    """
    Tool for detecting stationarity and seasonality in time series data.

    This tool performs comprehensive stationarity analysis using:
    - Augmented Dickey-Fuller (ADF) test
    - Kwiatkowski-Phillips-Schmidt-Shin (KPSS) test
    - Visual inspection through plots
    - Optional seasonal decomposition
    - Trend removal and re-testing

    The tool helps determine if a time series is stationary (suitable for many
    time series models) or non-stationary (requiring differencing or detrending).
    """

    name = "seasonal_detection"
    description = "Analyze time series data for stationarity using ADF and KPSS statistical tests"
    args_schema = SeasonalDetectionArgs

    def __init__(self, **kwargs):
        """Initialize the SeasonalDetectionTool."""
        super().__init__(**kwargs)
        self.results = {}

    def _default_output_dir(self) -> Path:
        """Get the default output directory for seasonal detection outputs."""
        return self.static_dir / "reports" / "seasonal_detection"

    def _validate_dataframe(self, df: Any) -> pd.DataFrame:
        """
        Validate that the input is a valid pandas DataFrame.

        Args:
            df: Input data to validate

        Returns:
            pandas DataFrame

        Raises:
            ValueError: If input is not a valid DataFrame
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("Input must be a pandas DataFrame")

        if df.empty:
            raise ValueError("DataFrame is empty")

        return df

    def _validate_columns(self, df: pd.DataFrame, time_col: str, value_col: str) -> None:
        """
        Validate that required columns exist in the DataFrame.

        Args:
            df: DataFrame to validate
            time_col: Time column name
            value_col: Value column name

        Raises:
            ValueError: If columns are missing or invalid
        """
        if time_col not in df.columns:
            raise ValueError(f"Time column '{time_col}' not found. Available columns: {list(df.columns)}")

        if value_col not in df.columns:
            raise ValueError(f"Value column '{value_col}' not found. Available columns: {list(df.columns)}")

        # Check if time column can be converted to datetime
        try:
            pd.to_datetime(df[time_col])
        except Exception as e:
            raise ValueError(f"Time column '{time_col}' cannot be converted to datetime: {e}")

        # Check if value column is numeric
        if not pd.api.types.is_numeric_dtype(df[value_col]):
            try:
                pd.to_numeric(df[value_col])
            except Exception as e:
                raise ValueError(f"Value column '{value_col}' is not numeric and cannot be converted: {e}")

    def _prepare_time_series(self, df: pd.DataFrame, time_col: str, value_col: str) -> pd.Series:
        """
        Prepare time series data for analysis.

        Args:
            df: Input DataFrame
            time_col: Time column name
            value_col: Value column name

        Returns:
            Time series with datetime index
        """
        # Create a copy to avoid modifying original data
        df_copy = df.copy()

        # Convert time column to datetime
        df_copy[time_col] = pd.to_datetime(df_copy[time_col])

        # Convert value column to numeric
        df_copy[value_col] = pd.to_numeric(df_copy[value_col], errors='coerce')

        # Remove rows with NaN values
        df_copy = df_copy.dropna(subset=[time_col, value_col])

        if len(df_copy) == 0:
            raise ValueError("No valid data points after cleaning")

        # Sort by time
        df_copy = df_copy.sort_values(time_col)

        # Set time as index and return the series
        df_copy.set_index(time_col, inplace=True)

        return df_copy[value_col]

    def _perform_adf_test(self, series: pd.Series, maxlag: Optional[int], regression: str) -> Dict[str, Any]:
        """
        Perform Augmented Dickey-Fuller test.

        Args:
            series: Time series data
            maxlag: Maximum lag for test
            regression: Regression type

        Returns:
            Dictionary with test results
        """
        try:
            # Perform ADF test
            adf_result = adfuller(series.dropna(), maxlag=maxlag, regression=regression)

            # Extract results
            adf_statistic = adf_result[0]
            adf_pvalue = adf_result[1]
            adf_lags_used = adf_result[2]
            adf_nobs = adf_result[3]
            adf_critical_values = adf_result[4]

            # Determine stationarity based on p-value
            is_stationary_pvalue = adf_pvalue <= 0.05

            # Also check against critical values
            is_stationary_critical = adf_statistic < adf_critical_values['5%']

            return {
                'test_name': 'Augmented Dickey-Fuller',
                'statistic': adf_statistic,
                'p_value': adf_pvalue,
                'lags_used': adf_lags_used,
                'n_observations': adf_nobs,
                'critical_values': adf_critical_values,
                'is_stationary_pvalue': is_stationary_pvalue,
                'is_stationary_critical': is_stationary_critical,
                'interpretation': {
                    'null_hypothesis': 'Time series has a unit root (non-stationary)',
                    'alternative_hypothesis': 'Time series is stationary',
                    'conclusion_pvalue': 'Stationary' if is_stationary_pvalue else 'Non-stationary',
                    'conclusion_critical': 'Stationary' if is_stationary_critical else 'Non-stationary',
                    'confidence': f'{(1-0.05)*100}%'
                }
            }

        except Exception as e:
            return {
                'test_name': 'Augmented Dickey-Fuller',
                'error': str(e),
                'success': False
            }

    def _perform_kpss_test(self, series: pd.Series, nlags: Optional[int], regression: str) -> Dict[str, Any]:
        """
        Perform Kwiatkowski-Phillips-Schmidt-Shin test.

        Args:
            series: Time series data
            nlags: Number of lags
            regression: Regression type ('c' for level, 'ct' for trend)

        Returns:
            Dictionary with test results
        """
        try:
            # KPSS regression parameter mapping
            kpss_regression = 'c' if regression in ['c', 'n'] else 'ct'

            # Perform KPSS test
            kpss_result = kpss(series.dropna(), regression=kpss_regression, nlags=nlags)

            # Extract results
            kpss_statistic = kpss_result[0]
            kpss_pvalue = kpss_result[1]
            kpss_lags_used = kpss_result[2]
            kpss_critical_values = kpss_result[3]

            # Determine stationarity based on p-value (opposite of ADF)
            is_stationary_pvalue = kpss_pvalue > 0.05

            # Also check against critical values
            is_stationary_critical = kpss_statistic < kpss_critical_values['5%']

            return {
                'test_name': 'Kwiatkowski-Phillips-Schmidt-Shin',
                'statistic': kpss_statistic,
                'p_value': kpss_pvalue,
                'lags_used': kpss_lags_used,
                'critical_values': kpss_critical_values,
                'is_stationary_pvalue': is_stationary_pvalue,
                'is_stationary_critical': is_stationary_critical,
                'interpretation': {
                    'null_hypothesis': 'Time series is stationary',
                    'alternative_hypothesis': 'Time series has a unit root (non-stationary)',
                    'conclusion_pvalue': 'Stationary' if is_stationary_pvalue else 'Non-stationary',
                    'conclusion_critical': 'Stationary' if is_stationary_critical else 'Non-stationary',
                    'confidence': f'{(1-0.05)*100}%'
                }
            }

        except Exception as e:
            return {
                'test_name': 'Kwiatkowski-Phillips-Schmidt-Shin',
                'error': str(e),
                'success': False
            }

    def _perform_seasonal_decomposition(self, series: pd.Series) -> Dict[str, Any]:
        """
        Perform seasonal decomposition analysis.

        Args:
            series: Time series data

        Returns:
            Dictionary with decomposition results
        """
        try:
            # Determine frequency for decomposition
            freq = self._infer_frequency(series)

            if freq is None or freq < 4:
                return {
                    'success': False,
                    'error': 'Cannot perform seasonal decomposition: insufficient data or unclear frequency'
                }

            # Perform decomposition
            decomposition = seasonal_decompose(series, model='additive', period=freq)

            # Calculate variance explained by each component
            total_var = series.var()
            trend_var = decomposition.trend.var()
            seasonal_var = decomposition.seasonal.var()
            residual_var = decomposition.resid.var()

            return {
                'success': True,
                'frequency': freq,
                'trend_variance_explained': trend_var / total_var if total_var > 0 else 0,
                'seasonal_variance_explained': seasonal_var / total_var if total_var > 0 else 0,
                'residual_variance_explained': residual_var / total_var if total_var > 0 else 0,
                'decomposition': {
                    'trend': decomposition.trend,
                    'seasonal': decomposition.seasonal,
                    'residual': decomposition.resid,
                    'observed': decomposition.observed
                }
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _infer_frequency(self, series: pd.Series) -> Optional[int]:
        """
        Infer the frequency of the time series for seasonal decomposition.

        Args:
            series: Time series data

        Returns:
            Inferred frequency or None
        """
        try:
            # Try to infer from pandas
            if hasattr(series.index, 'freq') and series.index.freq:
                return series.index.freq

            # Estimate based on index differences
            if len(series) < 4:
                return None

            # Calculate time differences
            time_diffs = series.index.to_series().diff().dropna()
            mode_diff = time_diffs.mode().iloc[0] if len(time_diffs.mode()) > 0 else None

            if mode_diff is None:
                return None

            # Estimate frequency based on common patterns
            days = mode_diff.total_seconds() / (24 * 3600)

            if abs(days - 1) < 0.1:  # Daily data
                return 7  # Weekly seasonality
            elif abs(days - 7) < 0.5:  # Weekly data
                return 52  # Annual seasonality
            elif abs(days - 30.44) < 2:  # Monthly data (approximate)
                return 12  # Annual seasonality
            elif abs(days - 91.31) < 5:  # Quarterly data (approximate)
                return 4  # Annual seasonality
            else:
                # Default to square root of length for other frequencies
                return max(4, int(np.sqrt(len(series))))

        except Exception:
            return None

    def _detrend_series(self, series: pd.Series) -> pd.Series:
        """
        Remove trend from time series using differencing.

        Args:
            series: Original time series

        Returns:
            Detrended time series
        """
        return series.diff().dropna()

    def _create_visualizations(
        self, series: pd.Series, results: Dict[str, Any], output_prefix: str
    ) -> List[str]:
        """
        Create visualization plots for the analysis.

        Args:
            series: Time series data
            results: Analysis results
            output_prefix: Prefix for output files

        Returns:
            List of generated file paths
        """
        generated_files = []

        try:
            # Set up the plotting style
            plt.style.use('seaborn-v0_8-whitegrid')
            sns.set_palette("Set2")

            # 1. Time series plot with summary
            fig, axes = plt.subplots(2, 2, figsize=(15, 10))
            fig.suptitle('Time Series Stationarity Analysis', fontsize=16, fontweight='bold')

            # Original series
            axes[0, 0].plot(series.index, series.values, linewidth=1.5, color='steelblue')
            axes[0, 0].set_title('Original Time Series')
            axes[0, 0].set_xlabel('Time')
            axes[0, 0].set_ylabel('Value')
            axes[0, 0].grid(True, alpha=0.3)

            # Rolling statistics
            rolling_mean = series.rolling(window=min(30, len(series)//4)).mean()
            rolling_std = series.rolling(window=min(30, len(series)//4)).std()

            axes[0, 1].plot(series.index, series.values, alpha=0.7, label='Original', color='steelblue')
            axes[0, 1].plot(rolling_mean.index, rolling_mean.values, label='Rolling Mean', color='red', linewidth=2)
            axes[0, 1].plot(rolling_std.index, rolling_std.values, label='Rolling Std', color='orange', linewidth=2)
            axes[0, 1].set_title('Rolling Statistics')
            axes[0, 1].legend()
            axes[0, 1].grid(True, alpha=0.3)

            # ACF and PACF plots
            try:
                plot_acf(series.dropna(), ax=axes[1, 0], lags=min(40, len(series)//4), title='Autocorrelation Function')
                plot_pacf(series.dropna(), ax=axes[1, 1], lags=min(20, len(series)//8), title='Partial Autocorrelation Function')
            except Exception as e:
                axes[1, 0].text(0.5, 0.5, f'ACF plot error: {str(e)}', ha='center', va='center', transform=axes[1, 0].transAxes)
                axes[1, 1].text(0.5, 0.5, f'PACF plot error: {str(e)}', ha='center', va='center', transform=axes[1, 1].transAxes)

            plt.tight_layout()

            # Save the main plot
            main_plot_path = self.output_dir / f"{output_prefix}_stationarity_analysis.png"
            plt.savefig(main_plot_path, dpi=300, bbox_inches='tight')
            plt.close()
            generated_files.append(str(main_plot_path))

            # 2. Seasonal decomposition plot (if available)
            if 'decomposition' in results and results['decomposition']['success']:
                decomp_data = results['decomposition']['decomposition']

                fig, axes = plt.subplots(4, 1, figsize=(15, 12))
                fig.suptitle('Seasonal Decomposition', fontsize=16, fontweight='bold')

                # Plot each component
                components = [
                    ('Observed', decomp_data['observed'], 'steelblue'),
                    ('Trend', decomp_data['trend'], 'red'),
                    ('Seasonal', decomp_data['seasonal'], 'green'),
                    ('Residual', decomp_data['residual'], 'purple')
                ]

                for i, (name, data, color) in enumerate(components):
                    axes[i].plot(data.index, data.values, color=color, linewidth=1.5)
                    axes[i].set_title(f'{name} Component')
                    axes[i].grid(True, alpha=0.3)
                    if i == len(components) - 1:
                        axes[i].set_xlabel('Time')

                plt.tight_layout()

                # Save decomposition plot
                decomp_plot_path = self.output_dir / f"{output_prefix}_seasonal_decomposition.png"
                plt.savefig(decomp_plot_path, dpi=300, bbox_inches='tight')
                plt.close()
                generated_files.append(str(decomp_plot_path))

        except Exception as e:
            self.logger.error(f"Error creating visualizations: {e}")

        return generated_files

    async def _execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the seasonal detection analysis.

        Args:
            **kwargs: Tool arguments

        Returns:
            Dictionary with analysis results
        """
        try:
            # Extract arguments
            dataframe = kwargs['dataframe']
            title = kwargs['title']
            time_column = kwargs['time_column']
            value_column = kwargs['value_column']
            confidence_level = kwargs.get('confidence_level', 0.05)
            maxlag = kwargs.get('maxlag')
            regression = kwargs.get('regression', 'c')
            nlags = kwargs.get('nlags')
            generate_plots = kwargs.get('generate_plots', True)
            perform_decomposition = kwargs.get('perform_decomposition', True)
            remove_trend = kwargs.get('remove_trend', False)
            filename = kwargs.get('filename')

            # Validate DataFrame
            df = self._validate_dataframe(dataframe)

            # Validate columns
            self._validate_columns(df, time_column, value_column)

            # Prepare time series
            series = self._prepare_time_series(df, time_column, value_column)

            self.logger.info(f"Analyzing time series with {len(series)} observations")

            # Initialize results
            analysis_results = {
                'data_info': {
                    'dataframe_name': title,
                    'time_column': time_column,
                    'value_column': value_column,
                    'n_observations': len(series),
                    'date_range': {
                        'start': str(series.index.min()),
                        'end': str(series.index.max())
                    },
                    'missing_values': series.isnull().sum(),
                    'descriptive_stats': {
                        'mean': float(series.mean()),
                        'std': float(series.std()),
                        'min': float(series.min()),
                        'max': float(series.max()),
                        'skewness': float(series.skew()),
                        'kurtosis': float(series.kurtosis())
                    }
                },
                'stationarity_tests': {},
                'overall_conclusion': {}
            }

            # Perform ADF test
            self.logger.info("Performing Augmented Dickey-Fuller test...")
            adf_results = self._perform_adf_test(series, maxlag, regression)
            analysis_results['stationarity_tests']['adf'] = adf_results

            # Perform KPSS test
            self.logger.info("Performing KPSS test...")
            kpss_results = self._perform_kpss_test(series, nlags, regression)
            analysis_results['stationarity_tests']['kpss'] = kpss_results

            # Perform seasonal decomposition if requested
            if perform_decomposition:
                self.logger.info("Performing seasonal decomposition...")
                decomp_results = self._perform_seasonal_decomposition(series)
                analysis_results['decomposition'] = decomp_results

            # Test after detrending if requested
            if remove_trend:
                self.logger.info("Testing stationarity after detrending...")
                detrended_series = self._detrend_series(series)

                adf_detrended = self._perform_adf_test(detrended_series, maxlag, regression)
                kpss_detrended = self._perform_kpss_test(detrended_series, nlags, regression)

                analysis_results['detrended_tests'] = {
                    'adf': adf_detrended,
                    'kpss': kpss_detrended,
                    'n_observations': len(detrended_series)
                }

            # Overall conclusion
            adf_stationary = adf_results.get('is_stationary_pvalue', False)
            kpss_stationary = kpss_results.get('is_stationary_pvalue', False)

            if adf_stationary and kpss_stationary:
                conclusion = "STATIONARY"
                recommendation = "Both tests suggest the series is stationary. It's suitable for many time series models."
            elif not adf_stationary and not kpss_stationary:
                conclusion = "NON-STATIONARY"
                recommendation = "Both tests suggest the series is non-stationary. Consider differencing or detrending."
            else:
                conclusion = "INCONCLUSIVE"
                if adf_stationary:
                    recommendation = "ADF suggests stationary, KPSS suggests non-stationary. The series may be stationary around a deterministic trend."
                else:
                    recommendation = "KPSS suggests stationary, ADF suggests non-stationary. This is unusual and may indicate issues with the data or test assumptions."

            analysis_results['overall_conclusion'] = {
                'conclusion': conclusion,
                'recommendation': recommendation,
                'adf_stationary': adf_stationary,
                'kpss_stationary': kpss_stationary,
                'confidence_level': confidence_level
            }

            # Generate plots if requested
            generated_files = []
            if generate_plots:
                self.logger.info("Generating visualization plots...")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_prefix = f"{title}_{value_column}_{timestamp}"
                generated_files = self._create_visualizations(series, analysis_results, output_prefix)

                # Convert file paths to URLs
                analysis_results['generated_files'] = {
                    'file_paths': generated_files,
                    'file_urls': [self.to_static_url(fp) for fp in generated_files]
                }

            self.logger.info(f"Seasonal detection analysis completed. Conclusion: {conclusion}")

            return analysis_results

        except Exception as e:
            self.logger.error(f"Error in seasonal detection analysis: {e}")
            raise
