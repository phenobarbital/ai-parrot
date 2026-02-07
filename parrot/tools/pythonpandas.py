import contextlib
from typing import Optional, Dict, Any, List, TYPE_CHECKING
import pandas as pd
from .pythonrepl import (
    PythonREPLTool,
    PythonREPLArgs,
    brace_escape
)

if TYPE_CHECKING:
    from .dataset_manager import DatasetManager


class PythonPandasTool(PythonREPLTool):
    """
    Python Pandas Tool with pre-loaded DataFrames and enhanced data science capabilities.

    Extends PythonREPLTool to provide:
    - Automatic DataFrame binding with ORIGINAL names as primary identifiers
    - Standardized aliases (df1, df2, etc.) as convenience references
    - Integration with DatasetManager for catalog/metadata operations
    - Enhanced data exploration utilities
    - Safe DataFrame operations

    All metadata, EDA, column categorization, and data quality
    responsibilities are delegated to DatasetManager when available.
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
        dataset_manager: Optional['DatasetManager'] = None,
        df_prefix: str = "df",
        include_sample_data: bool = False,
        sample_rows: int = 3,
        **kwargs
    ):
        """
        Initialize the Python Pandas tool with DataFrame management.

        Args:
            dataframes: Dictionary of DataFrames to bind {name: DataFrame}.
                        Ignored if dataset_manager is provided (use manager's catalog instead).
            dataset_manager: DatasetManager instance for catalog/metadata operations.
                             When provided, all metadata and catalog management is delegated.
            df_prefix: Prefix for auto-generated DataFrame aliases (default: "df")
            include_sample_data: Include sample data in guide
            sample_rows: Number of sample rows to show
            **kwargs: Additional arguments for PythonREPLTool
        """
        # Configuration
        self.df_prefix = df_prefix
        self.include_sample_data = include_sample_data
        self.sample_rows = sample_rows

        # DatasetManager integration
        self._dataset_manager = dataset_manager
        self._df_guide_cache = ""

        # DataFrame storage - populated from manager or direct input
        if dataset_manager is not None:
            self.dataframes = dataset_manager.get_active_dataframes()
        else:
            self.dataframes = dataframes or {}

        # Execution environment bindings
        self.df_locals = {}

        # Process DataFrames before initializing parent
        self._process_dataframes()

        # Set up locals with DataFrames
        df_locals = kwargs.get('locals_dict', {})
        df_locals.update(self.df_locals)
        kwargs['locals_dict'] = df_locals

        # Initialize parent class
        super().__init__(**kwargs)

        # Update description with loaded DataFrames
        self._update_description()

    # ─────────────────────────────────────────────────────────────
    # DatasetManager Integration
    # ─────────────────────────────────────────────────────────────

    @property
    def dataset_manager(self) -> Optional['DatasetManager']:
        """Access the DatasetManager instance."""
        return self._dataset_manager

    @dataset_manager.setter
    def dataset_manager(self, manager: 'DatasetManager') -> None:
        """Set or replace the DatasetManager and sync dataframes."""
        self._dataset_manager = manager
        self.sync_from_manager()

    @property
    def df_guide(self) -> str:
        """Get the DataFrame guide from DatasetManager or cached value."""
        if self._dataset_manager:
            return self._dataset_manager.get_guide()
        return self._df_guide_cache

    @df_guide.setter
    def df_guide(self, value: str) -> None:
        """Set guide cache for standalone mode."""
        self._df_guide_cache = value

    def sync_from_manager(self) -> None:
        """
        Synchronize execution environment from DatasetManager's active datasets.

        Call this after adding/removing/activating/deactivating datasets
        in the DatasetManager to refresh the execution bindings.
        """
        if not self._dataset_manager:
            return

        # Clear old bindings
        self.clear_dataframes()

        # Get active DataFrames from manager
        self.dataframes = self._dataset_manager.get_active_dataframes()

        if not self.dataframes:
            return

        # Rebind to execution environment
        self._process_dataframes()
        self.locals.update(self.df_locals)
        self.globals.update(self.df_locals)

        # Update description
        self._update_description()

    # ─────────────────────────────────────────────────────────────
    # Description & Plotting Guide
    # ─────────────────────────────────────────────────────────────

    def _update_description(self) -> None:
        """Update tool description to include available DataFrames."""
        df_summary = ", ".join([
            f"{df_key}: {df.shape[0]} rows × {df.shape[1]} cols"
            for df_key, df in self.dataframes.items()
        ]) if self.dataframes else "No DataFrames"

        self.description = (
            f"Execute Python code with pandas DataFrames. "
            f"Available data: {df_summary}. "
            f"Use df1, df2, etc. to access DataFrames."
        )

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

    # ─────────────────────────────────────────────────────────────
    # DataFrame Processing (Execution Environment Binding)
    # ─────────────────────────────────────────────────────────────

    def _process_dataframes(self) -> None:
        """Process and bind DataFrames to the local environment.

        IMPORTANT:
        Original names are the PRIMARY identifiers, aliases are CONVENIENCE references.

        This method only handles execution environment binding.
        Metadata and catalog management is handled by DatasetManager.
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

    # ─────────────────────────────────────────────────────────────
    # DataFrame Management (Execution Environment Operations)
    # ─────────────────────────────────────────────────────────────

    def add_dataframe(self, name: str, df: pd.DataFrame) -> str:
        """
        Add a new DataFrame to the execution environment.

        If a DatasetManager is attached, also registers it in the catalog.

        Args:
            name: Name for the DataFrame
            df: The DataFrame to add

        Returns:
            Success message with DataFrame key
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("Object must be a pandas DataFrame")

        # Register in DatasetManager if available
        if self._dataset_manager:
            self._dataset_manager.add_dataframe(name, df)
            self.sync_from_manager()
        else:
            # Direct management (no DatasetManager)
            self.dataframes[name] = df
            self._process_dataframes()
            self.locals.update(self.df_locals)
            self.globals.update(self.df_locals)

        # Find the alias for this DataFrame
        df_alias = next(
            (
                f"{self.df_prefix}{i + 1}"
                for i, (df_name, _) in enumerate(self.dataframes.items())
                if df_name == name
            ),
            None,
        )

        # Update description
        self._update_description()

        return f"DataFrame '{name}' added successfully (alias: '{df_alias}')"

    def remove_dataframe(self, name: str) -> str:
        """
        Remove a DataFrame from the execution environment.

        If a DatasetManager is attached, also removes it from the catalog.

        Args:
            name: Name of the DataFrame to remove

        Returns:
            Success message
        """
        if self._dataset_manager:
            # Resolve alias via manager
            resolved_name = self._dataset_manager._resolve_name(name)
            self._dataset_manager.remove(resolved_name)
            self.sync_from_manager()
        else:
            # Direct management - resolve alias to original name
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

            del self.dataframes[resolved_name]
            self._process_dataframes()
            self.locals.update(self.df_locals)
            self.globals.update(self.df_locals)

        # Update description
        self._update_description()

        return f"DataFrame '{resolved_name}' removed successfully"

    def register_dataframes(
        self,
        dataframes: Dict[str, pd.DataFrame],
    ) -> None:
        """
        Register DataFrames to the tool execution environment.

        Clears any previously registered DataFrames and binds the new ones.
        This is the preferred method for DatasetManager integration.

        Args:
            dataframes: Dictionary mapping names to DataFrames
        """
        # Clear old DataFrame references from locals
        self.clear_dataframes()

        # Set new dataframes
        self.dataframes = dataframes or {}

        # Skip if no dataframes
        if not self.dataframes:
            return

        # Process and bind to environment
        self._process_dataframes()
        self.locals.update(self.df_locals)
        self.globals.update(self.df_locals)

        # Update description
        self._update_description()

    def clear_dataframes(self) -> None:
        """
        Clear all registered DataFrames from the execution environment.

        Removes DataFrame references from locals/globals and resets internal state.
        """
        # Remove old df_locals entries from locals/globals
        for key in list(self.df_locals.keys()):
            self.locals.pop(key, None)
            self.globals.pop(key, None)

        # Clear internal state
        self.dataframes = {}
        self.df_locals = {}
        self._df_guide_cache = ""

    # ─────────────────────────────────────────────────────────────
    # Delegated Methods (use DatasetManager when available)
    # ─────────────────────────────────────────────────────────────

    def get_dataframe_guide(self) -> str:
        """Get the current DataFrame guide."""
        return self.df_guide

    def list_dataframes(self) -> Dict[str, Dict[str, Any]]:
        """
        List all available DataFrames with their info.

        Delegates to DatasetManager if available, otherwise returns basic info.
        """
        if self._dataset_manager:
            return self._dataset_manager.list_dataframes()

        # Fallback: basic info without DatasetManager
        result = {}
        for i, (df_name, df) in enumerate(self.dataframes.items()):
            df_alias = f"{self.df_prefix}{i + 1}"
            result[df_name] = {
                'original_name': df_name,
                'alias': df_alias,
                'shape': df.shape,
                'columns': df.columns.tolist(),
                'memory_usage_mb': round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
                'null_count': int(df.isnull().sum().sum()),
            }
        return result

    def get_dataframe_summary(self, df_key: str) -> Dict[str, Any]:
        """
        Get detailed summary for a specific DataFrame.

        Delegates to DatasetManager if available.
        """
        if self._dataset_manager:
            return self._dataset_manager.get_dataframe_summary(df_key)

        # Fallback: resolve alias and return basic info
        resolved = df_key
        if df_key not in self.dataframes:
            # Try resolving as alias
            for i, (name, _) in enumerate(self.dataframes.items()):
                if f"{self.df_prefix}{i + 1}" == df_key:
                    resolved = name
                    break

        if resolved not in self.dataframes:
            available = list(self.dataframes.keys())
            raise ValueError(f"DataFrame '{df_key}' not found. Available: {available}")

        df = self.dataframes[resolved]
        return {
            'shape': df.shape,
            'columns': df.columns.tolist(),
            'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()},
            'memory_usage_bytes': df.memory_usage(deep=True).sum(),
            'null_counts': df.isnull().sum().to_dict(),
            'row_count': len(df),
            'column_count': len(df.columns),
        }

    # ─────────────────────────────────────────────────────────────
    # Environment Setup
    # ─────────────────────────────────────────────────────────────

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
            if self._dataset_manager:
                try:
                    summary = self._dataset_manager.get_dataframe_summary(df_key)
                    print(f"=== Quick EDA for {df_key} ===")
                    print(f"Shape: {summary.get('shape')}")
                    print(f"Columns: {summary.get('columns')}")
                    print(f"\nData Types:")
                    for col, dtype in summary.get('dtypes', {}).items():
                        print(f"  {col}: {dtype}")
                    if 'column_types' in summary:
                        print(f"\nColumn Categories:")
                        for col, cat in summary['column_types'].items():
                            print(f"  {col}: {cat}")
                    print(f"\nNull Counts:")
                    for col, count in summary.get('null_counts', {}).items():
                        if count > 0:
                            print(f"  {col}: {count}")
                    return f"EDA completed for {df_key}"
                except ValueError:
                    return f"DataFrame '{df_key}' not found."

            # Fallback without DatasetManager
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

    # ─────────────────────────────────────────────────────────────
    # Execution State
    # ─────────────────────────────────────────────────────────────

    def get_environment_info(self) -> Dict[str, Any]:
        """Override to include DataFrame information."""
        info = super().get_environment_info()
        info.update({
            'dataframes_count': len(self.dataframes),
            'dataframes': self.list_dataframes(),
            'df_prefix': self.df_prefix,
            'has_dataset_manager': self._dataset_manager is not None,
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

    # ─────────────────────────────────────────────────────────────
    # Execution (with data quality checks via DatasetManager)
    # ─────────────────────────────────────────────────────────────

    async def _execute(self, code: str, debug: bool = False, **kwargs) -> Any:
        """
        Execute Python code with DataFrame-specific enhancements.

        Overrides parent to check for NaNs in debug mode via DatasetManager.
        Also appends a preview of any new/modified DataFrames to the output,
        and includes the executed code for audit purposes.
        """
        # Snapshot current locals keys to identify new variables
        pre_keys = set(self.locals.keys())
        
        result = await super()._execute(code, debug=debug, **kwargs)

        # 1. Automatic Audit (Code + Data Preview)
        try:
            audit_parts = []
            
            # A. Executed Code Echo
            # Always informative to see what logic was applied, especially for filters.
            # We format it as a block.
            audit_parts.append(f"\n📝 [AUDIT] Executed Code:\n```python\n{code.strip()}\n```")
            
            # B. DataFrame Preview
            # Check for new or modified DataFrames to assist debugging
            current_keys = set(self.locals.keys())
            new_keys = current_keys - pre_keys
            
            for key in new_keys:
                if key.startswith('_'): 
                    continue
                    
                val = self.locals[key]
                if isinstance(val, pd.DataFrame) and not val.empty:
                    audit_parts.append(f"\n🔍 [AUDIT] Preview of '{key}' (first 3 rows):")
                    try:
                         # Use strict float formatting to avoid scientific notation if possible
                         preview = val.head(3).to_string(index=False) 
                    except Exception:
                         preview = str(val.head(3))
                    audit_parts.append(preview)
            
            if audit_parts:
                # Append to result
                debug_text = "\n".join(audit_parts)
                if isinstance(result, str):
                    result += debug_text
                    
        except Exception as e:
            self.logger.warning(f"Failed to generate DataFrame/Code preview: {e}")

        # 2. Debug Mode NaN Checks
        # If execution was successful and we are in debug mode
        if debug and isinstance(result, str) and not result.startswith("ToolError"):
            try:
                # Check for NaNs via DatasetManager or fallback
                nan_warnings = self._get_nan_warnings()

                if nan_warnings:
                    warnings_text = "\n\n⚠️  [DEBUG] Data Quality Warnings:\n" + "\n".join(nan_warnings)
                    result += warnings_text

            except Exception as e:
                self.logger.error(f"Error checking for NaNs: {e}")
                if debug:
                    result += f"\n\n⚠️  [DEBUG] Error checking data quality: {e}"

        return result

    def _get_nan_warnings(self) -> List[str]:
        """
        Get NaN warnings from DatasetManager or compute directly.

        Returns:
            List of warning messages describing where NaNs were found.
        """
        if self._dataset_manager:
            return self._dataset_manager.check_dataframes_for_nans()

        # Fallback: check directly on self.dataframes
        warnings = []
        for name, df in self.dataframes.items():
            try:
                if df.empty:
                    continue

                null_counts = df.isnull().sum()
                total_rows = len(df)
                cols_with_nulls = null_counts[null_counts > 0]

                if not cols_with_nulls.empty:
                    for col_name, count in cols_with_nulls.items():
                        percentage = (count / total_rows) * 100
                        warnings.append(
                            f"- DataFrame '{name}' (column '{col_name}'): "
                            f"Contains {count} NaNs ({percentage:.1f}% of {total_rows} rows)"
                        )
            except Exception:
                pass

        return warnings
