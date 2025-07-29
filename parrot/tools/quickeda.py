"""
Quick EDA Tool - Comprehensive Exploratory Data Analysis for pandas DataFrames.
"""
from typing import Any, Dict, Optional, List
from datetime import datetime
import base64
import io
from html import escape
from pathlib import Path
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from .abstract import AbstractTool


matplotlib.use('Agg')  # Use non-interactive backend

class QuickEdaArgs(BaseModel):
    """Arguments schema for Quick EDA analysis."""

    dataframe: Any = Field(
        description="Pandas DataFrame to analyze"
    )
    filename: Optional[str] = Field(
        default=None,
        description="Optional filename to save the EDA report (without extension)"
    )
    title: str = Field(
        default="Quick EDA Report",
        description="Title for the EDA report"
    )
    max_numeric_plots: int = Field(
        default=5,
        description="Maximum number of numerical columns to plot"
    )
    max_categorical_plots: int = Field(
        default=5,
        description="Maximum number of categorical columns to plot"
    )
    include_correlations: bool = Field(
        default=True,
        description="Whether to include correlation matrix"
    )
    include_distributions: bool = Field(
        default=True,
        description="Whether to include distribution plots"
    )
    include_value_counts: bool = Field(
        default=True,
        description="Whether to include value counts for categorical columns"
    )
    plot_style: str = Field(
        default="whitegrid",
        description="Seaborn plot style"
    )
    color_palette: str = Field(
        default="husl",
        description="Color palette for plots"
    )
    figure_size: tuple = Field(
        default=(12, 8),
        description="Default figure size for plots"
    )
    include_missing_analysis: bool = Field(
        default=True,
        description="Whether to include detailed missing value analysis"
    )


class QuickEdaTool(AbstractTool):
    """
    Tool for performing comprehensive Exploratory Data Analysis on pandas DataFrames.

    This tool generates a detailed HTML report with statistics, visualizations,
    and insights about the DataFrame structure and data distribution.
    """

    name: str = "quick_eda"
    description: str = "Perform comprehensive Exploratory Data Analysis on pandas DataFrame"
    args_schema = QuickEdaArgs
    return_direct: bool = False

    def _default_output_dir(self) -> Optional[Path]:
        """Default output directory for EDA reports."""
        return self.static_dir / "eda_reports" if self.static_dir else None

    def _get_eda_css(self) -> str:
        """Get comprehensive CSS styles for the EDA report."""
        return """
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f8f9fa;
                line-height: 1.6;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                background-color: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }
            h1 {
                color: #2c3e50;
                border-bottom: 3px solid #3498db;
                padding-bottom: 10px;
                text-align: center;
                font-size: 2.5em;
                margin-bottom: 30px;
            }
            h2 {
                color: #34495e;
                border-bottom: 2px solid #ecf0f1;
                padding-bottom: 8px;
                margin-top: 40px;
                font-size: 1.8em;
            }
            h3 {
                color: #2c3e50;
                margin-top: 25px;
                font-size: 1.3em;
            }
            .dataframe {
                border-collapse: collapse;
                margin: 20px 0;
                font-size: 0.9em;
                width: 100%;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            .dataframe th, .dataframe td {
                border: 1px solid #bdc3c7;
                padding: 12px 15px;
                text-align: left;
            }
            .dataframe th {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .dataframe tbody tr:nth-child(even) {
                background-color: #f8f9fa;
            }
            .dataframe tbody tr:hover {
                background-color: #e3f2fd;
                transition: background-color 0.3s ease;
            }
            .dataframe caption {
                caption-side: top;
                font-weight: bold;
                margin-bottom: 10px;
                text-align: left;
                font-size: 1.2em;
                color: #2c3e50;
            }
            img {
                max-width: 100%;
                height: auto;
                display: block;
                margin: 20px auto;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }
            .plot-container {
                margin-bottom: 30px;
                background-color: #fafafa;
                padding: 20px;
                border-radius: 8px;
                border-left: 4px solid #3498db;
            }
            .section {
                margin-bottom: 40px;
                padding: 25px;
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            }
            .missing-values {
                color: #e74c3c;
                font-weight: bold;
            }
            .info-box {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                text-align: center;
            }
            .info-box h3 {
                color: white;
                margin-top: 0;
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin: 20px 0;
            }
            .stat-card {
                background: white;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            .stat-number {
                font-size: 2em;
                font-weight: bold;
                color: #3498db;
            }
            .stat-label {
                color: #7f8c8d;
                font-size: 0.9em;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .footer {
                text-align: center;
                color: #95a5a6;
                font-size: 0.9em;
                margin-top: 50px;
                padding-top: 20px;
                border-top: 1px solid #ecf0f1;
            }
            .alert {
                padding: 15px;
                margin: 15px 0;
                border: 1px solid transparent;
                border-radius: 4px;
            }
            .alert-warning {
                color: #856404;
                background-color: #fff3cd;
                border-color: #ffeaa7;
            }
            .alert-info {
                color: #0c5460;
                background-color: #d1ecf1;
                border-color: #bee5eb;
            }
        </style>
        """

    def _plot_to_base64(self, plt_figure) -> str:
        """Convert matplotlib figure to base64 encoded string."""
        buf = io.BytesIO()
        plt_figure.savefig(buf, format='png', bbox_inches='tight', dpi=100, facecolor='white')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        buf.close()
        plt.close(plt_figure)
        return img_base64

    def _df_to_html_with_style(self, df_input: pd.DataFrame, title: str = "") -> str:
        """Convert DataFrame to HTML with styling."""
        styler = df_input.style.set_table_attributes('class="dataframe"')
        if title:
            styler = styler.set_caption(title)
        return styler.to_html()

    def _generate_basic_info_section(self, df: pd.DataFrame) -> str:
        """Generate basic information section."""
        html = ['<div class="section">']
        html.append('<h2>📏 Dataset Overview</h2>')

        # Create info cards
        html.append('<div class="stats-grid">')
        html.append(f'''
            <div class="stat-card">
                <div class="stat-number">{df.shape[0]:,}</div>
                <div class="stat-label">Rows</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{df.shape[1]:,}</div>
                <div class="stat-label">Columns</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{df.memory_usage(deep=True).sum() / 1024**2:.1f} MB</div>
                <div class="stat-label">Memory Usage</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{df.duplicated().sum():,}</div>
                <div class="stat-label">Duplicate Rows</div>
            </div>
        ''')
        html.append('</div>')
        html.append('</div>')
        return '\n'.join(html)

    def _generate_data_types_section(self, df: pd.DataFrame) -> str:
        """Generate data types section."""
        html = ['<div class="section">']
        html.append('<h2>📋 Column Information</h2>')

        # Create comprehensive column info
        col_info = []
        for col in df.columns:
            dtype = str(df[col].dtype)
            null_count = df[col].isna().sum()
            null_pct = (null_count / len(df)) * 100
            unique_count = df[col].nunique()

            col_info.append({
                'Column': col,
                'Data Type': dtype,
                'Non-Null Count': f"{len(df) - null_count:,}",
                'Null Count': f"{null_count:,}",
                'Null %': f"{null_pct:.1f}%",
                'Unique Values': f"{unique_count:,}"
            })

        col_info_df = pd.DataFrame(col_info)
        html.append(self._df_to_html_with_style(col_info_df, "Column Details"))
        html.append('</div>')
        return '\n'.join(html)

    def _generate_missing_values_section(self, df: pd.DataFrame) -> str:
        """Generate missing values analysis section."""
        html = ['<div class="section">']
        html.append('<h2><span class="missing-values">🔍 Missing Values Analysis</span></h2>')

        missing = df.isna().sum()
        missing_filtered = missing[missing > 0].sort_values(ascending=False)

        if not missing_filtered.empty:
            missing_df = missing_filtered.to_frame(name='Missing Count')
            missing_df['Percentage (%)'] = (missing_df['Missing Count'] / len(df) * 100).round(2)
            html.append(self._df_to_html_with_style(missing_df, "Missing Values Summary"))

            # Add alert if high missing values
            high_missing = missing_df[missing_df['Percentage (%)'] > 50]
            if not high_missing.empty:
                html.append('<div class="alert alert-warning">')
                html.append(f'<strong>Warning:</strong> {len(high_missing)} column(s) have more than 50% missing values.')
                html.append('</div>')
        else:
            html.append('<div class="alert alert-info">')
            html.append('<strong>Great!</strong> No missing values found in the dataset.')
            html.append('</div>')

        html.append('</div>')
        return '\n'.join(html)

    def _generate_descriptive_stats_section(self, df: pd.DataFrame) -> str:
        """Generate descriptive statistics section."""
        html = ['<div class="section">']
        html.append('<h2>📈 Descriptive Statistics</h2>')

        try:
            # Numerical statistics
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                html.append('<h3>Numerical Columns</h3>')
                desc_stats = df[numeric_cols].describe().T
                desc_stats = desc_stats.round(3)
                html.append(self._df_to_html_with_style(desc_stats, "Numerical Statistics"))

            # Categorical statistics
            cat_cols = df.select_dtypes(include=['object', 'category']).columns
            if len(cat_cols) > 0:
                html.append('<h3>Categorical Columns</h3>')
                cat_stats = []
                for col in cat_cols:
                    stats = {
                        'Column': col,
                        'Unique Values': df[col].nunique(),
                        'Most Frequent': df[col].mode().iloc[0] if not df[col].mode().empty else 'N/A',
                        'Frequency': df[col].value_counts().iloc[0] if not df[col].value_counts().empty else 0
                    }
                    cat_stats.append(stats)

                cat_stats_df = pd.DataFrame(cat_stats)
                html.append(self._df_to_html_with_style(cat_stats_df, "Categorical Statistics"))

        except Exception as e:
            html.append(f'<div class="alert alert-warning">Could not generate descriptive statistics: {escape(str(e))}</div>')

        html.append('</div>')
        return '\n'.join(html)

    def _generate_correlation_section(self, df: pd.DataFrame, plot_style: str, color_palette: str, figure_size: tuple) -> str:
        """Generate correlation analysis section."""
        html = ['<div class="section">']
        html.append('<h2>🔗 Correlation Analysis</h2>')

        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

        if len(numeric_cols) > 1:
            try:
                sns.set_style(plot_style)
                sns.set_palette(color_palette)

                fig_corr, ax_corr = plt.subplots(figsize=figure_size)
                corr = df[numeric_cols].corr()

                # Create heatmap
                sns.heatmap(corr, annot=True, cmap='RdYlBu_r', fmt=".2f",
                           center=0, square=True, ax=ax_corr, cbar_kws={"shrink": .8})
                ax_corr.set_title("Correlation Matrix", fontsize=16, pad=20)
                plt.tight_layout()

                img_base64 = self._plot_to_base64(fig_corr)
                html.append('<div class="plot-container">')
                html.append(f'<img src="data:image/png;base64,{img_base64}" alt="Correlation Matrix">')
                html.append('</div>')

                # Find high correlations
                high_corr_pairs = []
                for i in range(len(corr.columns)):
                    for j in range(i+1, len(corr.columns)):
                        corr_val = corr.iloc[i, j]
                        if abs(corr_val) > 0.7:  # High correlation threshold
                            high_corr_pairs.append({
                                'Variable 1': corr.columns[i],
                                'Variable 2': corr.columns[j],
                                'Correlation': round(corr_val, 3)
                            })

                if high_corr_pairs:
                    html.append('<h3>High Correlations (|r| > 0.7)</h3>')
                    high_corr_df = pd.DataFrame(high_corr_pairs)
                    html.append(self._df_to_html_with_style(high_corr_df))

            except Exception as e:
                html.append(f'<div class="alert alert-warning">Could not generate correlation matrix: {escape(str(e))}</div>')
        else:
            html.append('<div class="alert alert-info">Need at least 2 numerical columns to calculate correlations.</div>')

        html.append('</div>')
        return '\n'.join(html)

    def _generate_distribution_section(self, df: pd.DataFrame, max_plots: int, plot_style: str, color_palette: str, figure_size: tuple) -> str:
        """Generate distribution analysis section."""
        html = ['<div class="section">']
        html.append('<h2>📊 Distribution Analysis</h2>')

        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

        if numeric_cols:
            cols_to_plot = numeric_cols[:min(len(numeric_cols), max_plots)]
            html.append(f'<p>Displaying distributions for {len(cols_to_plot)} numerical columns: <strong>{", ".join(map(escape, cols_to_plot))}</strong></p>')

            sns.set_style(plot_style)
            sns.set_palette(color_palette)

            for col in cols_to_plot:
                html.append('<div class="plot-container">')
                html.append(f'<h3>Distribution of {escape(col)}</h3>')

                try:
                    fig_dist, axes = plt.subplots(2, 2, figsize=(15, 10))
                    fig_dist.suptitle(f'Distribution Analysis: {escape(col)}', fontsize=16)

                    # Remove NaN values for plotting
                    data = df[col].dropna()

                    # Histogram with KDE
                    sns.histplot(data, kde=True, ax=axes[0, 0], alpha=0.7)
                    axes[0, 0].set_title('Histogram with KDE')

                    # Boxplot
                    sns.boxplot(y=data, ax=axes[0, 1])
                    axes[0, 1].set_title('Boxplot')

                    # Q-Q plot
                    from scipy import stats
                    stats.probplot(data, dist="norm", plot=axes[1, 0])
                    axes[1, 0].set_title('Q-Q Plot (Normal)')

                    # Violin plot
                    sns.violinplot(y=data, ax=axes[1, 1])
                    axes[1, 1].set_title('Violin Plot')

                    plt.tight_layout()
                    img_base64 = self._plot_to_base64(fig_dist)
                    html.append(f'<img src="data:image/png;base64,{img_base64}" alt="Distribution analysis for {escape(col)}">')

                except Exception as e:
                    html.append(f'<div class="alert alert-warning">Could not generate distribution plot for {escape(col)}: {escape(str(e))}</div>')

                html.append('</div>')
        else:
            html.append('<div class="alert alert-info">No numerical columns found for distribution analysis.</div>')

        html.append('</div>')
        return '\n'.join(html)

    def _generate_categorical_section(self, df: pd.DataFrame, max_plots: int, plot_style: str, color_palette: str, figure_size: tuple) -> str:
        """Generate categorical analysis section."""
        html = ['<div class="section">']
        html.append('<h2>📊 Categorical Analysis</h2>')

        cat_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()

        if cat_cols:
            cols_to_plot = cat_cols[:min(len(cat_cols), max_plots)]
            html.append(f'<p>Displaying analysis for {len(cols_to_plot)} categorical columns: <strong>{", ".join(map(escape, cols_to_plot))}</strong></p>')

            sns.set_style(plot_style)
            sns.set_palette(color_palette)

            for col in cols_to_plot:
                html.append('<div class="plot-container">')
                html.append(f'<h3>Analysis of {escape(col)}</h3>')

                try:
                    # Value counts table
                    value_counts = df[col].value_counts().head(15)  # Top 15 values
                    if not value_counts.empty:
                        vc_df = value_counts.to_frame(name='Count')
                        vc_df['Percentage (%)'] = (vc_df['Count'] / len(df[col].dropna()) * 100).round(2)
                        html.append(self._df_to_html_with_style(vc_df, f"Top {len(value_counts)} values"))

                        # Create visualization
                        fig_cat, axes = plt.subplots(1, 2, figsize=(15, 6))
                        fig_cat.suptitle(f'Categorical Analysis: {escape(col)}', fontsize=16)

                        # Bar chart
                        value_counts.head(10).plot(kind='bar', ax=axes[0], color=sns.color_palette(color_palette, len(value_counts.head(10))))
                        axes[0].set_title(f'Top 10 Values')
                        axes[0].set_ylabel('Count')
                        axes[0].tick_params(axis='x', rotation=45)

                        # Pie chart (for top 8 values + others)
                        pie_data = value_counts.head(8)
                        if len(value_counts) > 8:
                            others_count = value_counts.iloc[8:].sum()
                            pie_data = pd.concat([pie_data, pd.Series([others_count], index=['Others'])])

                        axes[1].pie(pie_data.values, labels=pie_data.index, autopct='%1.1f%%', startangle=90)
                        axes[1].set_title('Distribution (Top 8 + Others)')

                        plt.tight_layout()
                        img_base64 = self._plot_to_base64(fig_cat)
                        html.append(f'<img src="data:image/png;base64,{img_base64}" alt="Categorical analysis for {escape(col)}">')
                    else:
                        html.append('<div class="alert alert-info">No values found for this column.</div>')

                except Exception as e:
                    html.append(f'<div class="alert alert-warning">Could not generate analysis for {escape(col)}: {escape(str(e))}</div>')

                html.append('</div>')
        else:
            html.append('<div class="alert alert-info">No categorical columns found for analysis.</div>')

        html.append('</div>')
        return '\n'.join(html)

    async def _execute(
        self,
        dataframe: pd.DataFrame,
        filename: Optional[str] = None,
        title: str = "Quick EDA Report",
        max_numeric_plots: int = 5,
        max_categorical_plots: int = 5,
        include_correlations: bool = True,
        include_distributions: bool = True,
        include_value_counts: bool = True,
        plot_style: str = "whitegrid",
        color_palette: str = "husl",
        figure_size: tuple = (12, 8),
        include_missing_analysis: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the EDA analysis.

        Returns:
            Dictionary containing the HTML report and optional file information
        """

        # Validate input
        if not isinstance(dataframe, pd.DataFrame):
            raise ValueError("Input must be a pandas DataFrame")

        if dataframe.empty:
            raise ValueError("DataFrame is empty - cannot perform EDA")

        # Generate timestamp for unique identification
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Start building HTML report
        html_parts = []

        # HTML head and styling
        html_parts.append('<!DOCTYPE html>')
        html_parts.append('<html lang="en">')
        html_parts.append('<head>')
        html_parts.append('<meta charset="UTF-8">')
        html_parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        html_parts.append(f'<title>{title}</title>')
        html_parts.append(self._get_eda_css())
        html_parts.append('</head>')
        html_parts.append('<body>')
        html_parts.append('<div class="container">')

        # Title and header
        html_parts.append(f'<h1>📊 {title}</h1>')
        html_parts.append(f'<div class="info-box">')
        html_parts.append(f'<h3>Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</h3>')
        html_parts.append(f'<p>Dataset: {dataframe.shape[0]:,} rows × {dataframe.shape[1]:,} columns</p>')
        html_parts.append('</div>')

        # Generate sections
        try:
            # Basic information
            html_parts.append(self._generate_basic_info_section(dataframe))

            # Data types and column info
            html_parts.append(self._generate_data_types_section(dataframe))

            # Missing values analysis
            if include_missing_analysis:
                html_parts.append(self._generate_missing_values_section(dataframe))

            # Descriptive statistics
            html_parts.append(self._generate_descriptive_stats_section(dataframe))

            # Correlation analysis
            if include_correlations:
                html_parts.append(self._generate_correlation_section(
                    dataframe, plot_style, color_palette, figure_size
                ))

            # Distribution analysis
            if include_distributions:
                html_parts.append(self._generate_distribution_section(
                    dataframe, max_numeric_plots, plot_style, color_palette, figure_size
                ))

            # Categorical analysis
            if include_value_counts:
                html_parts.append(self._generate_categorical_section(
                    dataframe, max_categorical_plots, plot_style, color_palette, figure_size
                ))

        except Exception as e:
            html_parts.append(f'<div class="alert alert-warning">Error generating some sections: {escape(str(e))}</div>')
            self.logger.error(f"Error generating EDA sections: {e}")

        # Footer
        html_parts.append('<div class="footer">')
        html_parts.append('✅ EDA Report Generated Successfully')
        html_parts.append('</div>')
        html_parts.append('</div>')  # Close container
        html_parts.append('</body>')
        html_parts.append('</html>')

        # Combine HTML
        complete_html = '\n'.join(html_parts)

        # Prepare result
        result = {
            "html": complete_html,
            "title": title,
            "timestamp": timestamp,
            "dataset_shape": dataframe.shape,
            "columns": dataframe.columns.tolist(),
            "data_types": dataframe.dtypes.to_dict(),
            "missing_values": dataframe.isna().sum().to_dict()
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
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(complete_html)

                self.logger.info(f"EDA report saved to: {file_path}")

                result.update({
                    "file_path": str(file_path),
                    "file_url": self.to_static_url(file_path),
                    "file_size": file_path.stat().st_size
                })

            except Exception as e:
                self.logger.error(f"Failed to save EDA report: {e}")
                result["save_error"] = str(e)

        return result



# Additional utility functions for EDA
class EdaUtils:
    """Utility functions for EDA operations."""

    @staticmethod
    def detect_outliers(df: pd.DataFrame, columns: List[str] = None, method: str = 'iqr') -> Dict[str, List]:
        """
        Detect outliers in numerical columns.

        Args:
            df: DataFrame to analyze
            columns: Specific columns to check (default: all numerical)
            method: Method to use ('iqr', 'zscore', 'isolation_forest')

        Returns:
            Dictionary with column names as keys and outlier indices as values
        """
        if columns is None:
            columns = df.select_dtypes(include=['number']).columns.tolist()

        outliers = {}

        outlier_indices = []

        for col in columns:
            if method == 'iqr':
                Q1 = df[col].quantile(0.25)
                Q3 = df[col].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR
                outlier_indices = df[(df[col] < lower_bound) | (df[col] > upper_bound)].index.tolist()

            elif method == 'zscore':
                from scipy import stats
                z_scores = np.abs(stats.zscore(df[col].dropna()))
                outlier_indices = df[col].dropna()[z_scores > 3].index.tolist()

            elif method == 'isolation_forest':
                from sklearn.ensemble import IsolationForest
                iso_forest = IsolationForest(contamination=0.1, random_state=42)
                outlier_pred = iso_forest.fit_predict(df[[col]].dropna())
                outlier_indices = df[col].dropna()[outlier_pred == -1].index.tolist()

            outliers[col] = outlier_indices

        return outliers

    @staticmethod
    def suggest_data_types(df: pd.DataFrame) -> Dict[str, str]:
        """
        Suggest optimal data types for DataFrame columns.

        Args:
            df: DataFrame to analyze

        Returns:
            Dictionary with column names and suggested data types
        """
        suggestions = {}

        for col in df.columns:
            current_dtype = str(df[col].dtype)

            # Check if numeric column can be downcasted
            if df[col].dtype in ['int64', 'float64']:
                if df[col].dtype == 'int64':
                    max_val = df[col].max()
                    min_val = df[col].min()

                    if min_val >= 0 and max_val <= 255:
                        suggestions[col] = 'uint8'
                    elif min_val >= -128 and max_val <= 127:
                        suggestions[col] = 'int8'
                    elif min_val >= -32768 and max_val <= 32767:
                        suggestions[col] = 'int16'
                    elif min_val >= -2147483648 and max_val <= 2147483647:
                        suggestions[col] = 'int32'
                    else:
                        suggestions[col] = current_dtype

                elif df[col].dtype == 'float64':
                    # Check if can be converted to float32
                    if df[col].max() <= np.finfo(np.float32).max and df[col].min() >= np.finfo(np.float32).min:
                        suggestions[col] = 'float32'
                    else:
                        suggestions[col] = current_dtype

            # Check if object column should be category
            elif df[col].dtype == 'object':
                unique_ratio = df[col].nunique() / len(df)
                if unique_ratio < 0.5:  # Less than 50% unique values
                    suggestions[col] = 'category'
                else:
                    suggestions[col] = current_dtype

            else:
                suggestions[col] = current_dtype

        return suggestions

    @staticmethod
    def memory_usage_analysis(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyze memory usage of DataFrame.

        Args:
            df: DataFrame to analyze

        Returns:
            Dictionary with memory usage analysis
        """
        memory_usage = df.memory_usage(deep=True)
        total_memory = memory_usage.sum()

        analysis = {
            'total_memory_mb': total_memory / 1024**2,
            'column_memory': memory_usage.to_dict(),
            'largest_columns': memory_usage.nlargest(5).to_dict(),
            'memory_by_dtype': df.memory_usage(deep=True).groupby(df.dtypes).sum().to_dict()
        }

        return analysis
