import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend

import matplotlib.pyplot as plt
# Import profiling
from ydata_profiling import ProfileReport
import seaborn as sns
import pandas as pd
import base64
import io
from html import escape
import os
from datetime import datetime
import re


def df_to_html_with_style(df_input, title=""):
    """Converts a DataFrame to an HTML table with some basic styling."""
    styler = df_input.style.set_table_attributes('class="dataframe"')
    if title:
        styler = styler.set_caption(title)
    # You can add more complex styling here if needed
    # e.g., .format('{:.2f}') for floats, add bar charts, etc.
    return styler.to_html()


def plot_to_base64(plt_figure):
    """Saves the current matplotlib figure to a base64 encoded string."""
    buf = io.BytesIO()
    plt_figure.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    plt.close(plt_figure) # Close the figure to free memory
    return img_base64


def generate_eda_report(dataframe=None, report_dir=None, df_name="DataFrame", minimal=False, explorative=True):
    """Generates a ydata-profiling report and saves it to an HTML file.

    Args:
        dataframe: The pandas DataFrame to profile (defaults to 'df' if None)
        df_name: Name to use in the report title and filename
        minimal: Set to True for faster, less detailed reports
        explorative: Set to True for detailed explorative analysis

    Returns:
        dict: Contains file path and other metadata
    """
    try:
        # Use provided dataframe or default to df
        df_to_profile = dataframe if dataframe is not None else None

        # Generate timestamp for the filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create filename with timestamp
        output_filename = f"profile_report_{df_name}_{timestamp}.html"
        output_path = os.path.join(report_dir, output_filename)

        # Configure report options
        config_kwargs = {
            "title": f"Profiling Report for {df_name}",
            "progress_bar": False,
            "minimal": minimal,
            "explorative": explorative
        }

        print(
            f"Generating profile report for dataframe with shape {df_to_profile.shape}..."
        )

        # Generate the report (might take a while for large datasets)
        profile = ProfileReport(df_to_profile, **config_kwargs)

        # Save to file
        profile.to_file(output_path)

        print(f"✅ Profile report saved to: {output_path}")

        # Return structured info with file path
        return {
            "type": "file",
            "file_type": "html",
            "message": "Profile report generated successfully",
            "file_path": output_path,
            "report_url": f"file://{os.path.abspath(output_path)}",
            "df_name": df_name,
            "df_shape": df_to_profile.shape
        }

    except Exception as e:
        print(f"❌ Error generating profile report: {str(e)}")
        return {
            "type": "error",
            "message": f"Failed to generate profile report: {str(e)}"
        }


def quick_eda(dataframe=None, report_dir=None):
    """Performs a quick Exploratory Data Analysis (EDA) on a pandas DataFrame
    and saves the results as an HTML file in the agent_report_dir directory."""
    # Create the directory if it doesn't exist
    os.makedirs(report_dir, exist_ok=True)

    # Generate a timestamp for the filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create filename if not provided
    output_filename = f"eda_report_{timestamp}.html"

    # Create full path
    output_path = os.path.join(report_dir, output_filename)

    df_to_analyze = dataframe if dataframe is not None else None
    if not isinstance(df_to_analyze, pd.DataFrame):
        return "<p>Error: Input is not a valid pandas DataFrame.</p>"

    html_parts = []

    # --- Basic HTML Setup and Styling ---
    html_parts.append("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Quick EDA Report</title>
        <style>
            body { font-family: sans-serif; margin: 20px; }
            h1, h2, h3 { color: #333; border-bottom: 1px solid #ccc; padding-bottom: 5px; }
            h2 { margin-top: 30px; }
            .dataframe { border-collapse: collapse; margin: 15px 0; font-size: 0.9em; }
            .dataframe th, .dataframe td { border: 1px solid #ddd; padding: 8px; }
            .dataframe th { background-color: #f2f2f2; text-align: left; }
            .dataframe caption { caption-side: top; font-weight: bold; margin-bottom: 5px; text-align: left; font-size: 1.1em; }
            img { max-width: 100%; height: auto; display: block; margin: 15px 0; border: 1px solid #eee; }
            .plot-container { margin-bottom: 20px; }
            .section { margin-bottom: 40px; padding: 15px; background-color: #f9f9f9; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .missing-values { color: #d9534f; } /* Style for missing values count */
        </style>
    </head>
    <body>
    """)
    html_parts.append("<h1>📊 Quick EDA Report</h1>")

    # --- Basic Info ---
    html_parts.append('<div class="section">')
    html_parts.append("<h2>📏 Basic Information</h2>")
    html_parts.append(f"<p>Shape: {df_to_analyze.shape[0]} rows, {df_to_analyze.shape[1]} columns</p>")
    html_parts.append('</div>')

    # --- Data Types ---
    html_parts.append('<div class="section">')
    html_parts.append("<h2>📋 Data Types</h2>")
    dtypes_df = df_to_analyze.dtypes.to_frame(name='DataType')
    html_parts.append(df_to_html_with_style(dtypes_df))
    html_parts.append('</div>')

    # --- Missing Values ---
    html_parts.append('<div class="section">')
    html_parts.append("<h2><span class='missing-values'>🔍 Missing Values</span></h2>")
    missing = df_to_analyze.isna().sum()
    missing_filtered = missing[missing > 0]
    if not missing_filtered.empty:
        missing_df = missing_filtered.to_frame(name='Missing Count')
        missing_df['Percentage (%)'] = (missing_df['Missing Count'] / len(df_to_analyze) * 100).round(2)
        html_parts.append(df_to_html_with_style(missing_df))
    else:
        html_parts.append("<p>No missing values found.</p>")
    html_parts.append('</div>')

    # --- Descriptive Statistics ---
    html_parts.append('<div class="section">')
    html_parts.append("<h2>📈 Descriptive Statistics (Numerical Columns)</h2>")
    try:
        desc_stats = df_to_analyze.describe().T
        if not desc_stats.empty:
            html_parts.append(df_to_html_with_style(desc_stats.round(3))) # Round for clarity
        else:
            html_parts.append("<p>No numerical columns to describe.</p>")
    except Exception as e:
        html_parts.append(f"<p>Could not generate descriptive statistics: {escape(str(e))}</p>")
    html_parts.append('</div>')

    # --- Correlations for numerical columns ---
    numeric_cols = df_to_analyze.select_dtypes(include=['number']).columns.tolist()
    if len(numeric_cols) > 1:
        html_parts.append('<div class="section">')
        html_parts.append("<h2>🔗 Correlation Matrix (Numerical Columns)</h2>")
        try:
            fig_corr, ax_corr = plt.subplots(figsize=(10, 8))
            corr = df_to_analyze[numeric_cols].corr()
            sns.heatmap(corr, annot=True, cmap='coolwarm', fmt=".2f", ax=ax_corr)
            ax_corr.set_title("Correlation Matrix")
            # plt.tight_layout() # Often handled by bbox_inches='tight' in savefig

            img_base64 = plot_to_base64(fig_corr)
            html_parts.append(f'<img src="data:image/png;base64,{img_base64}" alt="Correlation Matrix">')
        except Exception as e:
            html_parts.append(f"<p>Could not generate correlation matrix plot: {escape(str(e))}</p>")
            if 'fig_corr' in locals() and plt.fignum_exists(fig_corr.number): plt.close(fig_corr) # Ensure plot is closed on error
        html_parts.append('</div>')
    elif len(numeric_cols) <= 1:
        html_parts.append('<div class="section">')
        html_parts.append("<h2>🔗 Correlation Matrix (Numerical Columns)</h2>")
        html_parts.append("<p>Not enough numerical columns (need at least 2) to calculate correlations.</p>")
        html_parts.append('</div>')


    # --- Distribution of numerical columns ---
    if numeric_cols:
        html_parts.append('<div class="section">')
        html_parts.append("<h2>📊 Numerical Distributions (Sample)</h2>")
        # Limit to avoid overly large HTML files
        cols_to_plot = numeric_cols[:min(len(numeric_cols), 5)]
        html_parts.append(f"<p>Displaying distributions for the first {len(cols_to_plot)} numerical columns: {', '.join(map(escape, cols_to_plot))}</p>")

        for col in cols_to_plot:
            html_parts.append('<div class="plot-container">')
            html_parts.append(f"<h3>Distribution of {escape(col)}</h3>")
            try:
                # Create a figure with two subplots
                fig_dist, axes = plt.subplots(1, 2, figsize=(12, 4))

                # Histogram
                sns.histplot(df_to_analyze[col].dropna(), kde=True, ax=axes[0])
                axes[0].set_title(f"Histogram of {escape(col)}")

                # Boxplot
                sns.boxplot(y=df_to_analyze[col].dropna(), ax=axes[1])
                axes[1].set_title(f"Boxplot of {escape(col)}")

                fig_dist.tight_layout()
                img_base64 = plot_to_base64(fig_dist)
                html_parts.append(f'<img src="data:image/png;base64,{img_base64}" alt="Distribution plot for {escape(col)}">')

            except Exception as e:
                html_parts.append(f"<p>Could not generate distribution plot for {escape(col)}: {escape(str(e))}</p>")
                # Ensure plot is closed even if error occurs after figure creation
                if 'fig_dist' in locals() and plt.fignum_exists(fig_dist.number): plt.close(fig_dist)
            html_parts.append('</div>') # End plot-container
        html_parts.append('</div>') # End section


    # --- Top values for categorical columns ---
    cat_cols = df_to_analyze.select_dtypes(include=['object', 'category']).columns.tolist()
    if cat_cols:
        html_parts.append('<div class="section">')
        html_parts.append("<h2>📊 Categorical Value Counts (Sample)</h2>")
        # Limit to avoid overly large HTML files
        cols_to_plot = cat_cols[:min(len(cat_cols), 5)]
        html_parts.append(f"<p>Displaying value counts and plots for the first {len(cols_to_plot)} categorical columns: {', '.join(map(escape, cols_to_plot))}</p>")

        for col in cols_to_plot:
            html_parts.append('<div class="plot-container">')
            html_parts.append(f"<h3>Value Counts for: {escape(col)}</h3>")
            try:
                # Value Counts Table (Top 10)
                value_counts = df_to_analyze[col].value_counts().head(10)
                if not value_counts.empty:
                    vc_df = value_counts.to_frame(name='Count')
                    vc_df['Percentage (%)'] = (vc_df['Count'] / len(df_to_analyze[col].dropna()) * 100).round(2) # Pct of non-missing
                    html_parts.append(df_to_html_with_style(vc_df, title=f"Top {len(value_counts)} values"))

                    # Create bar chart for top categories
                    fig_cat, ax_cat = plt.subplots(figsize=(10, 5))
                    value_counts.plot(kind='bar', ax=ax_cat)
                    ax_cat.set_title(f"Top {len(value_counts)} values in {escape(col)}")
                    ax_cat.set_ylabel("Count")
                    ax_cat.set_xlabel(escape(col))
                    plt.xticks(rotation=45, ha='right')
                    fig_cat.tight_layout()

                    img_base64 = plot_to_base64(fig_cat)
                    html_parts.append(f'<img src="data:image/png;base64,{img_base64}" alt="Bar chart for top values in {escape(col)}">')
                else:
                    html_parts.append("<p>No values found for this column.</p>")

            except Exception as e:
                html_parts.append(f"<p>Could not generate value counts/plot for {escape(col)}: {escape(str(e))}</p>")
                if 'fig_cat' in locals() and plt.fignum_exists(fig_cat.number): plt.close(fig_cat)

            html_parts.append('</div>') # End plot-container
        html_parts.append('</div>') # End section
    elif not cat_cols:
        html_parts.append('<div class="section">')
        html_parts.append("<h2>📊 Categorical Value Counts</h2>")
        html_parts.append("<p>No categorical columns found.</p>")
        html_parts.append('</div>')

    # --- Footer ---
    html_parts.append('<hr><p style="text-align:center; color: #666; font-size: 0.9em;">✅ Quick EDA Report Generated</p>')
    html_parts.append("</body></html>")

    # --- Combine and write to file ---
    html_content = "\n".join(html_parts)

    # Write the HTML content to the file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"✅ EDA report saved to: {output_path}")
    return {
        "message": "EDA completed successfully",
        "file_path": output_path,
        "report_url": f"file://{os.path.abspath(output_path)}"
    }

def list_available_dataframes():
    # List all available dataframes in the current session.

    # Get all variables in the current scope
    all_vars = list(globals().items())

    # Filter for pandas DataFrames
    dfs = [
        (name, obj) for name, obj in all_vars if isinstance(obj, pd.DataFrame)
    ]

    print(f"Found {len(dfs)} dataframes:")
    for name, df in dfs:
        print(f"- {name}: {df.shape[0]} rows × {df.shape[1]} columns")

    return [name for name, _ in dfs]
