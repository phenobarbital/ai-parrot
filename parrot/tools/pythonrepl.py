"""
PythonREPLTool migrated to use AbstractTool framework.
"""
import ast
import sys
import asyncio
from typing import Optional, Dict, Any, Union
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import numexpr as ne
import seaborn as sns
from pydantic import BaseModel, Field
from datamodel.parsers.json import json_decoder, json_encoder  # noqa  pylint: disable=E0611
from navconfig import BASE_DIR
from .base import AbstractTool


def sanitize_input(query: str) -> str:
    """
    Sanitize input to the python REPL.
    Remove whitespace, backtick & python (if llm mistakes python console as terminal)

    Args:
        query: The query to sanitize

    Returns:
        The sanitized query
    """
    query = query.strip()

    # Handle code blocks
    if query.startswith("```python"):
        query = query[9:]
    elif query.startswith("```"):
        query = query[3:]

    if query.endswith("```"):
        query = query[:-3]

    # Clean up any remaining leading/trailing whitespace
    query = query.strip()

    # Handle common formatting issues
    lines = query.split('\n')
    # Remove empty lines at start and end
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return '\n'.join(lines)


class PythonREPLArgs(BaseModel):
    """Arguments schema for PythonREPLTool."""
    code: str = Field(
        description="Python code to execute in the REPL environment"
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode for code execution"
    )


class PythonREPLTool(AbstractTool):
    """
    Python REPL Tool with pre-loaded data science libraries and enhanced capabilities.

    Features:
    - Pre-loaded libraries: pandas (pd), numpy (np), matplotlib.pyplot (plt), seaborn (sns), numexpr (ne)
    - Helper functions from parrot.bots.tools under `parrot_tools`
    - An `execution_results` dict for capturing intermediate results
    - A `report_directory` Path for saving outputs
    - Extended JSON encoder/decoder based on orjson (`extended_json`)
    - Async execution support
    - Error handling and sanitization
    """

    name = "PythonREPLTool"
    description = "Execute Python code with pre-loaded data science libraries (pandas, numpy, matplotlib, seaborn)"
    args_schema = PythonREPLArgs

    # Class variable to track if environment has been bootstrapped
    _bootstrapped = False

    def __init__(
        self,
        locals_dict: Optional[Dict] = None,
        globals_dict: Optional[Dict] = None,
        report_dir: Optional[Path] = None,
        plt_style: str = 'seaborn-v0_8-whitegrid',
        palette: str = 'Set2',
        setup_code: Optional[str] = None,
        sanitize_input_enabled: bool = True,
        **kwargs
    ):
        """
        Initialize the Python REPL tool.

        Args:
            locals_dict: Local variables for the REPL
            globals_dict: Global variables for the REPL
            report_dir: Directory for saving reports
            plt_style: Matplotlib style
            palette: Seaborn color palette
            setup_code: Custom setup code to run
            sanitize_input_enabled: Whether to sanitize input
            **kwargs: Additional arguments for AbstractTool
        """
        # Check Python version
        if sys.version_info < (3, 9):
            raise ValueError(
                "This tool requires Python 3.9 or higher "
                f"(you have Python version: {sys.version})"
            )

        # Set default output directory for reports
        if not report_dir:
            report_dir = BASE_DIR.joinpath('static', 'reports')

        # Initialize parent class
        super().__init__(output_dir=report_dir, **kwargs)

        # Configuration
        self.sanitize_input_enabled = sanitize_input_enabled
        self.plt_style = plt_style
        self.palette = palette
        self.setup_code = setup_code or self._get_default_setup_code()

        # Initialize execution environment
        self.locals = locals_dict or {}
        self.globals = globals_dict or {}

        # Setup the environment
        self._setup_environment()

        # Bootstrap the environment if not already done
        self._bootstrap()

    def _default_output_dir(self) -> Path:
        """Get the default output directory for Python REPL outputs."""
        return self.static_dir / "reports" / "python_repl"

    def _setup_environment(self) -> None:
        """Set up the Python environment with libraries and tools."""
        # Ensure output directory exists
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

        # Update locals with essential libraries and tools
        self.locals.update({
            # Core data science libraries
            'pd': pd,
            'np': np,
            'plt': plt,
            'sns': sns,
            'ne': ne,

            # JSON utilities
            'json_encoder': json_encoder,
            'json_decoder': json_decoder,
            'extended_json': {
                'dumps': json_encoder,
                'loads': json_decoder,
            },

            # Directory and results management
            'report_directory': self.output_dir,
            'execution_results': {},

            # Helper functions (uncomment when available)
            # 'quick_eda': parrot_tools.quick_eda,
            # 'generate_eda_report': parrot_tools.generate_eda_report,
            # 'list_available_dataframes': parrot_tools.list_available_dataframes,
            # 'parrot_tools': parrot_tools,
        })

        # Mirror locals into globals so user code can see everything
        self.globals.update(self.locals)

        self.logger.info(f"Python REPL environment setup complete. Output dir: {self.output_dir}")

    def _get_default_setup_code(self) -> str:
        """Get the default setup code."""
        return f"""
# Python REPL Environment Setup
import warnings
warnings.filterwarnings('ignore')

# Ensure essential libraries are imported
try:
    # Uncomment when parrot.bots.tools is available
    # from parrot.bots.tools import (
    #     quick_eda,
    #     generate_eda_report,
    #     list_available_dataframes,
    #     create_plot,
    #     generate_pdf_from_html
    # )
    pass
except ImportError as e:
    print(f"Note: Some parrot tools not available: {{e}}")

print(f"🐍 Python REPL Environment Ready!")
print(f"📊 Pandas version: {{pd.__version__}}")
print(f"🔢 NumPy version: {{np.__version__}}")
print(f"📈 Matplotlib version: {{plt.matplotlib.__version__}}")
print(f"🎨 Seaborn version: {{sns.__version__}}")
print(f"📁 Report directory: {{report_directory}}")
print("Use 'execution_results' dict to store intermediate results.")
"""

    def _bootstrap(self) -> None:
        """Bootstrap the REPL environment."""
        if PythonREPLTool._bootstrapped:
            return

        self.logger.info("Running REPL bootstrap code...")
        try:
            result = self._execute_code(self.setup_code)
            if result.strip():
                self.logger.info(f"Bootstrap output: {result}")
        except Exception as e:
            self.logger.error("Error during REPL bootstrap", exc_info=e)

        try:
            plt.style.use(self.plt_style)
            sns.set_palette(self.palette)
            self.logger.debug(f"Set matplotlib style: {self.plt_style}, palette: {self.palette}")
        except Exception as e:
            self.logger.error("Error setting plot style", exc_info=e)

        PythonREPLTool._bootstrapped = True

    def _serialize_execution_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Serialize execution results to make them JSON-compatible.

        Args:
            results: Dictionary of execution results

        Returns:
            JSON-serializable dictionary
        """
        serializable = {}

        for key, value in results.items():
            # Ensure key is a string
            str_key = str(key)

            try:
                # Try to serialize different types of objects
                if isinstance(value, pd.DataFrame):
                    serializable[str_key] = {
                        "_type": "pandas.DataFrame",
                        "data": value.to_dict(orient='records'),
                        "columns": list(value.columns),
                        "index": list(value.index),
                        "shape": value.shape,
                        "dtypes": {col: str(dtype) for col, dtype in value.dtypes.items()}
                    }
                elif isinstance(value, pd.Series):
                    serializable[str_key] = {
                        "_type": "pandas.Series",
                        "data": value.to_dict(),
                        "name": value.name,
                        "dtype": str(value.dtype),
                        "shape": value.shape
                    }
                elif isinstance(value, np.ndarray):
                    serializable[str_key] = {
                        "_type": "numpy.ndarray",
                        "data": value.tolist(),
                        "shape": value.shape,
                        "dtype": str(value.dtype)
                    }
                elif hasattr(value, '__dict__') and not callable(value):
                    # For custom objects, try to serialize their __dict__
                    serializable[str_key] = {
                        "_type": f"{value.__class__.__module__}.{value.__class__.__name__}",
                        "data": str(value),  # fallback to string representation
                        "attributes": {k: str(v) for k, v in value.__dict__.items() if not k.startswith('_')}
                    }
                elif callable(value):
                    # For functions or callable objects
                    serializable[str_key] = {
                        "_type": "callable",
                        "name": getattr(value, '__name__', str(value)),
                        "data": str(value)
                    }
                else:
                    # Try direct serialization for basic types
                    # Test if it's JSON serializable
                    json_encoder(value)
                    serializable[str_key] = value

            except Exception as e:
                # If all else fails, store as string representation
                self.logger.warning(f"Could not serialize execution result '{str_key}': {e}")
                serializable[str_key] = {
                    "_type": "string_representation",
                    "data": str(value),
                    "original_type": str(type(value)),
                    "serialization_error": str(e)
                }

        return serializable

    def _execute_code(self, query: str, debug: bool = False) -> str:
        """Execute Python code and return the result."""
        try:
            if self.sanitize_input_enabled:
                query = sanitize_input(query)

            if debug:
                print(f"DEBUG: Executing code:\n{repr(query)}\n" + "="*50)

            if not query.strip():
                return ""

            # Parse the query
            try:
                tree = ast.parse(query)
            except SyntaxError as e:
                if debug:
                    print(f"DEBUG: SyntaxError details: {e}")
                    print(f"DEBUG: Query lines: {query.split(chr(10))}")
                return f"SyntaxError: {str(e)}"

            # If empty, return
            if not tree.body:
                return ""

            # Execute all but the last statement
            if len(tree.body) > 1:
                try:
                    module = ast.Module(tree.body[:-1], type_ignores=[])
                    exec(ast.unparse(module), self.globals, self.locals)
                except Exception as e:
                    return f"ExecutionError: {type(e).__name__}: {str(e)}"

            # Handle the last statement
            last_statement = tree.body[-1]
            module_end = ast.Module([last_statement], type_ignores=[])
            module_end_str = ast.unparse(module_end)

            io_buffer = StringIO()
            # Check if it's an expression that can be evaluated
            is_expression = isinstance(last_statement, ast.Expr)

            if is_expression:
                try:
                    # Try to evaluate as expression first
                    with redirect_stdout(io_buffer):
                        ret = eval(module_end_str, self.globals, self.locals)
                        output = io_buffer.getvalue()
                        if ret is None:
                            return output
                        else:
                            return output + str(ret) if output else str(ret)
                except Exception:
                    # Fall back to execution
                    pass

            try:
                # Try to evaluate as expression first
                with redirect_stdout(io_buffer):
                    ret = eval(module_end_str, self.globals, self.locals)
                    if ret is None:
                        return io_buffer.getvalue()
                    else:
                        output = io_buffer.getvalue()
                        return output + str(ret) if output else str(ret)
            except Exception:
                # Fall back to execution
                try:
                    with redirect_stdout(io_buffer):
                        exec(module_end_str, self.globals, self.locals)
                    return io_buffer.getvalue()
                except Exception as e:
                    return f"ExecutionError: {type(e).__name__}: {str(e)}"

            return ""

        except Exception as e:
            return f"{type(e).__name__}: {str(e)}"

    async def _execute(self, code: str, debug: bool = False, **kwargs) -> Dict[str, Any]:
        """
        Execute Python code asynchronously (AbstractTool interface).

        Args:
            code: Python code to execute
            debug: Enable debug mode
            **kwargs: Additional arguments

        Returns:
            Dictionary with execution results
        """
        try:
            self.logger.info(f"Executing Python code: {code[:100]}...")

            # Execute the code in a thread to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._execute_code,
                code,
                debug
            )

            # Prepare the response
            response = {
                "output": result,
                "code_executed": code,
                "debug_mode": debug,
                "execution_successful": not result.startswith(("SyntaxError:", "ExecutionError:", "Error:")),
            }

            # Add information about available variables
            if debug:
                response["available_variables"] = {
                    "locals_count": len(self.locals),
                    "globals_count": len(self.globals),
                    "execution_results_keys": list(self.locals.get('execution_results', {}).keys())
                }

            return response

        except Exception as e:
            self.logger.error(f"Error executing Python code: {e}")
            return {
                "output": f"ToolError: {type(e).__name__}: {str(e)}",
                "code_executed": code,
                "debug_mode": debug,
                "execution_successful": False,
                "error_details": str(e)
            }

    def execute_sync(self, code: str, debug: bool = False) -> str:
        """
        Execute Python code synchronously.

        Args:
            code: Python code to execute
            debug: Enable debug mode

        Returns:
            Execution result as string
        """
        return self._execute_code(code, debug)

    def get_environment_info(self) -> Dict[str, Any]:
        """Get information about the current REPL environment."""
        return {
            "python_version": sys.version,
            "pandas_version": pd.__version__,
            "numpy_version": np.__version__,
            "matplotlib_version": plt.matplotlib.__version__,
            "seaborn_version": sns.__version__,
            "output_directory": str(self.output_dir),
            "locals_count": len(self.locals),
            "globals_count": len(self.globals),
            "execution_results_keys": list(self.locals.get('execution_results', {}).keys()),
            "bootstrapped": self._bootstrapped,
            "plot_style": self.plt_style,
            "color_palette": self.palette
        }

    def reset_environment(self) -> None:
        """Reset the REPL environment to its initial state."""
        self.logger.info("Resetting Python REPL environment...")

        # Clear execution results
        if 'execution_results' in self.locals:
            self.locals['execution_results'].clear()

        # Re-setup the environment
        self._setup_environment()

        # Re-bootstrap
        PythonREPLTool._bootstrapped = False
        self._bootstrap()

        self.logger.info("Python REPL environment reset complete")

    def save_execution_results(self, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Save current execution results to a JSON file.

        Args:
            filename: Optional filename for the output file

        Returns:
            Dictionary with file information
        """
        if not filename:
            filename = self.generate_filename("execution_results", ".json")

        file_path = self.output_dir / filename
        file_path = self.validate_output_path(file_path)

        # Get execution results
        execution_results = self.locals.get('execution_results', {})

        # Serialize execution results safely
        serializable_results = self._serialize_execution_results(execution_results)

        # Save to file
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(json_encoder(serializable_results))

            file_url = self.to_static_url(file_path)

            return {
                "filename": filename,
                "file_path": str(file_path),
                "file_url": file_url,
                "results_count": len(execution_results),
                "serializable_count": len(serializable_results),
                "saved_at": self.generate_filename("", "", include_timestamp=True)
            }

        except Exception as e:
            raise ValueError(f"Error saving execution results: {e}")

    def load_execution_results(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Load execution results from a JSON file.

        Args:
            file_path: Path to the JSON file

        Returns:
            Dictionary with loading information
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise ValueError(f"File not found: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                serialized_results = json_decoder(f.read())

            # Deserialize the results
            results = self._deserialize_execution_results(serialized_results)

            # Update execution results
            self.locals['execution_results'].update(results)

            return {
                "file_path": str(file_path),
                "results_loaded": len(results),
                "total_results": len(self.locals['execution_results']),
                "loaded_at": self.generate_filename("", "", include_timestamp=True)
            }

        except Exception as e:
            raise ValueError(f"Error loading execution results: {e}")

    def _deserialize_execution_results(self, serialized_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deserialize execution results from JSON-compatible format.

        Args:
            serialized_results: Dictionary of serialized results

        Returns:
            Dictionary with deserialized objects where possible
        """
        results = {}

        for key, value in serialized_results.items():
            try:
                if isinstance(value, dict) and "_type" in value:
                    obj_type = value["_type"]

                    if obj_type == "pandas.DataFrame":
                        # Reconstruct DataFrame
                        df = pd.DataFrame(value["data"])
                        if "columns" in value:
                            df.columns = value["columns"]
                        results[key] = df

                    elif obj_type == "pandas.Series":
                        # Reconstruct Series
                        series = pd.Series(value["data"])
                        if "name" in value:
                            series.name = value["name"]
                        results[key] = series

                    elif obj_type == "numpy.ndarray":
                        # Reconstruct numpy array
                        arr = np.array(value["data"])
                        if "shape" in value:
                            arr = arr.reshape(value["shape"])
                        results[key] = arr

                    elif obj_type in ["string_representation", "callable"]:
                        # Keep as metadata dict for non-reconstructible objects
                        results[key] = value

                    else:
                        # For other custom types, keep the serialized representation
                        results[key] = value
                else:
                    # Direct value
                    results[key] = value

            except Exception as e:
                self.logger.warning(f"Could not deserialize execution result '{key}': {e}")
                # Keep the serialized version
                results[key] = value

        return results

    def __call__(self, code: str, debug: bool = False) -> str:
        """Make the tool callable for backward compatibility."""
        return self.execute_sync(code, debug)


# Enhanced tool registry registration
def register_python_repl_tool(registry, **kwargs):
    """Register the PythonREPLTool in a tool registry."""
    registry.register(PythonREPLTool, **kwargs)
