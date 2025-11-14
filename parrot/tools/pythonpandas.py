import contextlib
from typing import Optional, Dict, Any, List
import numpy as np
import pandas as pd
from .pythonrepl import (
    PythonREPLTool,
    PythonREPLArgs,
    brace_escape
)

class PythonPandasTool(PythonREPLTool):
    """
    Python Pandas Tool with pre-loaded DataFrames and enhanced data science capabilities.

    Extends PythonREPLTool to provide:
    - Automatic DataFrame binding with ORIGINAL names as primary identifiers
    - Standardized aliases (df1, df2, etc.) as convenience references
    - DataFrame information generation and guides
    - Enhanced data exploration utilities
    - Safe DataFrame operations
    """

    name = "python_repl_pandas"
    description = "Execute Python code with pre-loaded DataFrames and enhanced pandas capabilities"
    args_schema = PythonREPLArgs

    # Available plotting libraries configuration
    PLOTTING_LIBRARIES = {
        'matplotlib': {
            'import_as': 'plt',
            'import_statement': 'import matplotlib.pyplot as plt',
            'description': 'Traditional plotting library with extensive customization',
            'best_for': ['statistical plots', 'publication-quality figures', 'fine-grained control'],
            'examples': [
                'plt.figure(figsize=(10, 6))',
                'plt.plot(df1["column"], df1["value"])',
                'plt.hist(df1["numeric_column"], bins=20)',
                'plt.scatter(df1["x"], df1["y"])',
                'save_current_plot("my_plot.png")'
            ]
        },
        'plotly': {
            'import_as': 'px, go, pio',
            'import_statement': 'import plotly.express as px\nimport plotly.graph_objects as go\nimport plotly.io as pio',
            'description': 'Interactive web-based plotting library',
            'best_for': ['interactive plots', 'dashboards', 'web applications'],
            'examples': [
                'fig = px.scatter(df1, x="column1", y="column2", color="category")',
                'fig = px.histogram(df1, x="numeric_column")',
                'fig = go.Figure(data=go.Bar(x=df1["category"], y=df1["value"]))',
                'fig.show()  # Note: may not display in REPL, use fig.write_html("plot.html")'
            ]
        },
        'bokeh': {
            'import_as': 'bokeh',
            'import_statement': 'from bokeh.plotting import figure, show, output_file\nfrom bokeh.models import ColumnDataSource',
            'description': 'Interactive visualization library for web browsers',
            'best_for': ['large datasets', 'real-time streaming', 'web deployment'],
            'examples': [
                'p = figure(title="My Plot", x_axis_label="X", y_axis_label="Y")',
                'p.circle(df1["x"], df1["y"], size=10)',
                'output_file("plot.html")',
                'show(p)'
            ]
        },
        'altair': {
            'import_as': 'alt',
            'import_statement': 'import altair as alt',
            'description': 'Declarative statistical visualization (Grammar of Graphics)',
            'best_for': ['exploratory analysis', 'statistical plots', 'clean syntax'],
            'examples': [
                'chart = alt.Chart(df1).mark_circle().encode(x="column1", y="column2")',
                'chart = alt.Chart(df1).mark_bar().encode(x="category", y="count()")',
                'chart.show()  # or chart.save("plot.html")'
            ]
        },
        'holoviews': {
            'import_as': 'hv',
            'import_statement': 'import holoviews as hv\nhv.extension("bokeh")  # or "matplotlib"',
            'description': 'High-level data visualization with multiple backends',
            'best_for': ['multi-dimensional data', 'animated plots', 'complex layouts'],
            'examples': [
                'hv.Scatter(df1, "x", "y")',
                'hv.Histogram(df1["numeric_column"])',
                'hv.HeatMap(df1, ["category1", "category2"], "value")'
            ]
        }
    }

    def __init__(
        self,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,
        df_prefix: str = "df",
        generate_guide: bool = True,
        include_summary_stats: bool = False,
        include_sample_data: bool = False,
        sample_rows: int = 3,
        auto_detect_types: bool = True,
        **kwargs
    ):
        """
        Initialize the Python Pandas tool with DataFrame management.

        Args:
            dataframes: Dictionary of DataFrames to bind {name: DataFrame}
            df_prefix: Prefix for auto-generated DataFrame aliases (default: "df")
            generate_guide: Whether to generate DataFrame information guide
            include_summary_stats: Include summary statistics in guide
            include_sample_data: Include sample data in guide
            sample_rows: Number of sample rows to show
            auto_detect_types: Automatically detect and categorize column types
            **kwargs: Additional arguments for PythonREPLTool
        """
        # Configuration
        self.df_prefix = df_prefix
        self.generate_guide = generate_guide
        self.include_summary_stats = include_summary_stats
        self.include_sample_data = include_sample_data
        self.sample_rows = sample_rows
        self.auto_detect_types = auto_detect_types

        # DataFrame storage
        self.dataframes = dataframes or {}
        self.df_locals = {}
        self.df_guide = ""

        # Process DataFrames before initializing parent
        self._process_dataframes()

        # ✅ Sync df_locals to execution environment
        # self.locals.update(self.df_locals)
        # self.globals.update(self.df_locals)

        # Set up locals with DataFrames
        df_locals = kwargs.get('locals_dict', {})
        df_locals.update(self.df_locals)
        kwargs['locals_dict'] = df_locals

        # Initialize parent class
        super().__init__(**kwargs)

        # Generate guide after initialization
        if self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

    def _generate_plotting_guide(self) -> str:
        """Generate comprehensive plotting libraries guide for the LLM."""
        guide_parts = [
            "# Plotting Libraries Guide",
            "",
            "## Available Libraries",
            ""
        ]

        for lib_name, lib_info in self.PLOTTING_LIBRARIES.items():
            guide_parts.extend([
                f"### {lib_name.title()}",
                f"**Import**: `{lib_info['import_statement']}`",
                f"**Best for**: {', '.join(lib_info['best_for'])}",
                "",
                "**Examples**:",
            ])
            guide_parts.extend(f"- `{example}`" for example in lib_info['examples'])
            guide_parts.append("")

        # Add general recommendations
        guide_parts.extend([
            "## General Tips",
            "- For static plots: Use `save_current_plot('filename.png')` with matplotlib",
            "- For interactive plots: Use plotly and save as HTML",
            "- For large datasets: Consider aggregation or sampling first",
            "",
        ])

        return "\n".join(guide_parts)

    def _process_dataframes(self) -> None:
        """Process and bind DataFrames to the local environment.

        IMPORTANT:
        Original names are the PRIMARY identifiers, aliases are CONVENIENCE references.
        """
        self.df_locals = {}

        for i, (df_name, df) in enumerate(self.dataframes.items()):
            # Standardized DataFrame alias (for convenience)
            df_alias = f"{self.df_prefix}{i + 1}"

            # Bind DataFrame with both original name and standardized key
            self.df_locals[df_name] = df          # PRIMARY: Original name
            self.df_locals[df_alias] = df         # ALIAS: Convenience reference

            for key in [df_name, df_alias]:
                self.df_locals[f"{key}_row_count"] = len(df)
                self.df_locals[f"{key}_col_count"] = len(df.columns)
                self.df_locals[f"{key}_shape"] = df.shape
                self.df_locals[f"{key}_columns"] = df.columns.tolist()
                self.df_locals[f"{key}_info"] = self._get_dataframe_info(df)

    def _get_dataframe_info(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Get comprehensive information about a DataFrame."""
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
            info['column_types'] = self._categorize_columns(df)

        return info

    def _categorize_columns(self, df: pd.DataFrame) -> Dict[str, str]:
        """Categorize DataFrame columns into data types."""
        column_types = {}

        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
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
                unique_ratio = df[col].nunique() / len(df) if len(df) > 0 else 0
                if unique_ratio < 0.1 and df[col].nunique() < 50:
                    column_types[col] = "categorical_text"
                else:
                    column_types[col] = "text"

        return column_types

    def _metrics_guide(self, df_key: str, df_name: str, columns: List[str]) -> str:
        """Generate column information guide."""
        df = self.df_locals[df_key]
        column_info = []

        for col in columns:
            dtype = str(df[col].dtype)
            category = self._categorize_columns(df)[col] if self.auto_detect_types else dtype
            null_count = df[col].isnull().sum()
            unique_count = df[col].nunique()

            # Additional info based on data type
            extra_info = []
            if category in ['integer', 'float']:
                min_val, max_val = df[col].min(), df[col].max()
                extra_info.append(f"Range: {min_val} - {max_val}")
            elif category in ['text', 'categorical_text']:
                extra_info.append(f"Unique values: {unique_count}")
                if unique_count <= 10:
                    unique_vals = df[col].unique()[:5]
                    extra_info.append(f"Sample values: {list(unique_vals)}")

            extra_str = f" ({', '.join(extra_info)})" if extra_info else ""
            null_str = f" [Nulls: {null_count}]" if null_count > 0 else ""

            column_info.append(f"- **{col}**: {dtype} → {category}{extra_str}{null_str}")

        return "\n".join(column_info)

    def _generate_dataframe_guide(self) -> str:
        """Generate comprehensive DataFrame guide for the LLM."""
        if not self.dataframes:
            return "No DataFrames loaded."

        guide_parts = [
            "# DataFrame Guide",
            "",
            f"**Total DataFrames**: {len(self.dataframes)}",
            "",
            "## Available DataFrames:",
        ]

        for i, (df_name, df) in enumerate(self.dataframes.items()):
            df_alias = f"{self.df_prefix}{i + 1}"
            shape = df.shape

            guide_parts.extend([
                f"### DataFrame: `{df_name}` (alias: `{df_alias}`)",
                f"- **Primary Name**: `{df_name}` ← Use this in your code",
                f"- **Alias**: `{df_alias}` (convenience reference)",
                f"- **Shape**: {shape[0]:,} rows × {shape[1]} columns",
                f"- **Columns**: {', '.join(df.columns.tolist()[:10])}{'...' if len(df.columns) > 10 else ''}",
                ""
            ])
            # self._metrics_guide(df_key, df_name, df.columns.tolist()),

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
        if self.dataframes:
            first_name = list(self.dataframes.keys())[0]
            first_alias = f"{self.df_prefix}1"
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
            "1. **Primary Names**: Use the original DataFrame names (e.g., `epson_sales_brian_bi`)",
            f"2. **Aliases Available**: You can also use `{self.df_prefix}1`, `{self.df_prefix}2`, etc. if shorter names are preferred",
            "3. **Both Work**: The DataFrames are accessible by BOTH names in the execution environment",
            "4. **Recommendation**: Use original names for clarity, aliases for brevity",
            ""
        ])

        return "\n".join(guide_parts)

    def add_dataframe(self, name: str, df: pd.DataFrame, regenerate_guide: bool = True) -> str:
        """
        Add a new DataFrame to the tool.

        Args:
            name: Name for the DataFrame
            df: The DataFrame to add
            regenerate_guide: Whether to regenerate the guide

        Returns:
            Success message with DataFrame key
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("Object must be a pandas DataFrame")

        # Add to dataframes dict
        self.dataframes[name] = df

        # Reprocess all DataFrames
        self._process_dataframes()

        # Update locals in the execution environment
        self.locals.update(self.df_locals)
        self.globals.update(self.df_locals)

        # Regenerate guide if requested
        if regenerate_guide and self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        # Find the standardized key for this DataFrame
        df_alias = next(
            (
                f"{self.df_prefix}{i + 1}"
                for i, (df_name, _) in enumerate(self.dataframes.items())
                if df_name == name
            ),
            None,
        )

        return f"DataFrame '{name}' added successfully (alias: '{df_alias}')"

    def remove_dataframe(self, name: str, regenerate_guide: bool = True) -> str:
        """
        Remove a DataFrame from the tool.

        Args:
            name: Name of the DataFrame to remove
            regenerate_guide: Whether to regenerate the guide

        Returns:
            Success message
        """
        # Resolve alias to original name if needed
        resolved_name = next(
            (
                df_name
                for i, (df_name, _) in enumerate(self.dataframes.items())
                if f"{self.df_prefix}{i + 1}" == name
            ),
            name,
        )

        if resolved_name not in self.dataframes:
            raise ValueError(f"DataFrame '{name}' not found")

        # Remove from dataframes dict
        del self.dataframes[resolved_name]

        # Reprocess DataFrames
        self._process_dataframes()

        # Update execution environment
        self.locals.update(self.df_locals)
        self.globals.update(self.df_locals)

        # Regenerate guide if requested
        if regenerate_guide and self.generate_guide:
            self.df_guide = self._generate_dataframe_guide()

        return f"DataFrame '{resolved_name}' removed successfully"

    def get_dataframe_guide(self) -> str:
        """Get the current DataFrame guide."""
        return self.df_guide

    def list_dataframes(self) -> Dict[str, Dict[str, Any]]:
        """
        List all available DataFrames with their info.

        Returns original names as keys with alias info included.
        """
        result = {}
        for i, (df_name, df) in enumerate(self.dataframes.items()):
            df_alias = f"{self.df_prefix}{i + 1}"
            result[df_name] = {  # KEY CHANGE: Use original name as key
                'original_name': df_name,
                'alias': df_alias,
                'shape': df.shape,
                'columns': df.columns.tolist(),
                'memory_usage_mb': df.memory_usage(deep=True).sum() / 1024 / 1024,
                'null_count': df.isnull().sum().sum(),
            }
        return result

    def get_dataframe_summary(self, df_key: str) -> Dict[str, Any]:
        """Get detailed summary for a specific DataFrame (accepts both original name and alias)."""
        if df_key not in self.df_locals:
            available = list(self.dataframes.keys())
            raise ValueError(f"DataFrame '{df_key}' not found. Available: {available}")

        df = self.df_locals[df_key]
        return self._get_dataframe_info(df)

    def _setup_environment(self) -> None:
        """Override to add DataFrame-specific utilities."""
        # Call parent setup first
        super()._setup_environment()

        # Add DataFrame-specific utilities
        def list_available_dataframes():
            """List all available DataFrames."""
            return self.list_dataframes()

        def get_df_guide():
            """Get the DataFrame guide."""
            return self.get_dataframe_guide()

        def get_plotting_guide():
            """Get the plotting libraries guide."""
            return self._generate_plotting_guide()

        def quick_eda(df_key: str):
            """Quick exploratory data analysis for a DataFrame."""
            if df_key not in self.df_locals:
                return f"DataFrame '{df_key}' not found. Available: {list(self.dataframes.keys())}"

            df = self.df_locals[df_key]

            print(f"=== Quick EDA for {df_key} ===")
            print(f"Shape: {df.shape}")
            print(f"Columns: {df.columns.tolist()}")
            print(f"\nData Types:")
            print(df.dtypes)
            print(f"\nMissing Values:")
            print(df.isnull().sum())
            print(f"\nSample Data:")
            print(df.head())

            return f"EDA completed for {df_key}"

        # Add to locals
        self.locals.update({
            'list_available_dataframes': list_available_dataframes,
            'get_df_guide': get_df_guide,
            'quick_eda': quick_eda,
            'get_plotting_guide': get_plotting_guide,
        })

        # Update globals
        self.globals.update(self.locals)

    def _get_default_setup_code(self) -> str:
        """Override to include DataFrame-specific setup."""
        base_setup = super()._get_default_setup_code()

        # Generate the DataFrame info statically since we know the DataFrames at this point
        df_count = len(self.dataframes)
        df_info_lines = []

        if df_count > 0:
            df_info_lines.append("print('📊 Available DataFrames:')")
            for i, (name, df) in enumerate(self.dataframes.items()):
                df_alias = f"{self.df_prefix}{i + 1}"
                shape = df.shape
                df_info_lines.append(
                    f"print('  - {name} (alias: {df_alias}): "
                    f"{shape[0]} rows × {shape[1]} columns')"
                )

        df_info_code = '\n'.join(df_info_lines)

        df_setup = f"""
# DataFrame-specific setup
print("📊 DataFrames loaded: {df_count}")
{df_info_code}
print("💡 TIP: Use original names (e.g., 'bi_sales') or aliases (e.g., 'df1')")
print("🔧 Utilities: list_available_dataframes(), get_df_guide(), quick_eda()")
"""

        return base_setup + df_setup

    def get_environment_info(self) -> Dict[str, Any]:
        """Override to include DataFrame information."""
        info = super().get_environment_info()
        info.update({
            'dataframes_count': len(self.dataframes),
            'dataframes': self.list_dataframes(),
            'df_prefix': self.df_prefix,
            'guide_generated': bool(self.df_guide),
        })
        return info

    def get_execution_state(self) -> Dict[str, Any]:
        """
        Extract current execution state for use by formatters.

        Returns:
            Dictionary containing:
            - execution_results: All stored results
            - dataframes: Dict of available DataFrames
            - variables: Other variables from execution
        """
        state = {
            'execution_results': self.locals.get('execution_results', {}),
            'dataframes': {},
            'variables': {}
        }

        # Extract DataFrames
        for name, df in self.dataframes.items():
            state['dataframes'][name] = df
            # Also include by alias
            for i, (df_name, _) in enumerate(self.dataframes.items()):
                if df_name == name:
                    alias = f"{self.df_prefix}{i + 1}"
                    state['dataframes'][alias] = df
                    break

        # Extract other relevant variables (excluding functions, modules)
        for key, value in self.locals.items():
            if not key.startswith('_') and not callable(value) and (key not in ['execution_results'] and not key.endswith('_row_count')):
                with contextlib.suppress(Exception):
                    # Only include serializable or DataFrame-like objects
                    if isinstance(value, (str, int, float, bool, list, dict, pd.DataFrame, pd.Series)):
                        state['variables'][key] = value

        return state

    def clear_execution_results(self):
        """Clear execution_results dictionary for new queries."""
        if 'execution_results' in self.locals:
            self.locals['execution_results'].clear()
