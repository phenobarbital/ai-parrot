import ast
import sys
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import numexpr as ne
import seaborn as sns
from datamodel.parsers.json import json_decoder, json_encoder  # noqa  pylint: disable=E0611
from navconfig import BASE_DIR
from navconfig.logging import logging
# import parrot.bots.tools as parrot_tools


def sanitize_input(query: str) -> str:
    """Sanitize input to the python REPL.
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


class PythonREPLTool:
    """
    Standalone Python REPL Tool with:
    - Pre-loaded data science libraries: pandas (pd), numpy (np), matplotlib.pyplot (plt), seaborn (sns)
    - Helper functions from parrot.bots.tools under `parrot_tools`
    - An `execution_results` dict for capturing intermediate results
    - A `report_directory` Path for saving outputs
    - An extended JSON encoder/decoder based on orjson (`extended_json`)
    """

    _bootstrapped = False

    def __init__(
        self,
        locals_dict: Optional[Dict] = None,
        globals_dict: Optional[Dict] = None,
        report_dir: Optional[Path] = None,
        plt_style: str = 'seaborn-v0_8-whitegrid',
        palette: str = 'Set2',
        setup_code: Optional[str] = None,
        sanitize_input: bool = True
    ):
        """Initialize the Python REPL tool.

        Args:
            locals_dict: Local variables for the REPL
            globals_dict: Global variables for the REPL
            report_dir: Directory for saving reports
            plt_style: Matplotlib style
            palette: Seaborn color palette
            setup_code: Custom setup code to run
            sanitize_input: Whether to sanitize input
        """
        if sys.version_info < (3, 9):
            raise ValueError(
                "This tool requires Python 3.9 or higher "
                f"(you have Python version: {sys.version})"
            )

        self.sanitize_input = sanitize_input
        self.logger = logging.getLogger(__name__)

        # Initialize locals with essential libraries and tools
        self.locals = locals_dict or {}
        self._setup_environment(report_dir)

        # Set up globals
        self.globals = globals_dict or {}
        # Mirror locals into globals so user code can see everything
        self.globals.update(self.locals)

        # Setup code
        self.setup_code = setup_code or self._get_default_setup_code()

        # Bootstrap the environment
        self._bootstrap(plt_style, palette)

    def _setup_environment(self, report_dir: Optional[Path]) -> None:
        """Set up the Python environment with libraries and tools."""
        # Set the report directory
        report_dir = report_dir or BASE_DIR.joinpath('static', 'reports')
        if not report_dir.exists():
            report_dir.mkdir(parents=True, exist_ok=True)

        # Update locals with essential libraries and tools
        self.locals.update({
            'pd': pd,
            'np': np,
            'plt': plt,
            'sns': sns,
            'ne': ne,
            'json_encoder': json_encoder,
            'json_decoder': json_decoder,
            'extended_json': {
                'dumps': json_encoder,
                'loads': json_decoder,
            },
            # 'quick_eda': parrot_tools.quick_eda,
            # 'generate_eda_report': parrot_tools.generate_eda_report,
            # 'list_available_dataframes': parrot_tools.list_available_dataframes,
            # 'parrot_tools': parrot_tools,
            'report_directory': report_dir,
            'execution_results': {}
        })

    def _get_default_setup_code(self) -> str:
        """Get the default setup code."""
        return """
# Ensure essential libraries are imported
from parrot.bots.tools import (
    quick_eda,
    generate_eda_report,
    list_available_dataframes,
    create_plot,
    generate_pdf_from_html
)

print(f"Pandas version: {pd.__version__}")
"""

    def _bootstrap(self, plt_style: str, palette: str) -> None:
        """Bootstrap the REPL environment."""
        if PythonREPLTool._bootstrapped:
            return

        self.logger.info("Running REPL bootstrap code...")
        try:
            self.execute(self.setup_code)
        except Exception as e:
            self.logger.error("Error during REPL bootstrap", exc_info=e)

        try:
            plt.style.use(plt_style)
            sns.set_palette(palette)
            self.logger.debug(
                f"Pandas version: {pd.__version__}"
            )
        except Exception as e:
            self.logger.error(
                "Error setting plot style",
                exc_info=e
            )

        PythonREPLTool._bootstrapped = True

    def execute(self, query: str, debug: bool = False) -> str:
        """Execute Python code and return the result."""
        try:
            if self.sanitize_input:
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

    async def execute_async(self, query: str) -> str:
        """Execute Python code asynchronously."""
        try:
            loop = asyncio.get_event_loop()
            _new = False
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _new = True
        try:
            return await loop.run_in_executor(
                None,
                self.execute,
                query
            )
        finally:
            if _new:
                loop.close()

    def get_tool_schema(self) -> Dict[str, Any]:
        """Get the tool schema for LLM registration."""
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute"
                }
            },
            "required": ["code"]
        }

    def __call__(self, code: str) -> str:
        """Make the tool callable."""
        return self.execute(code)
