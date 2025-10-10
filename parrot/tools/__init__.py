"""
Tools infrastructure for building Agents.
"""
from parrot.plugins import setup_plugin_importer, dynamic_import_helper
from .pythonrepl import PythonREPLTool
from .pythonpandas import PythonPandasTool
from .abstract import AbstractTool, ToolResult
from .math import MathTool
from .toolkit import AbstractToolkit, ToolkitTool
from .decorators import tool_schema, tool
from .querytoolkit import QueryToolkit
from .qsource import QSourceTool
from .ddgo import DuckDuckGoToolkit
from .databasequery import DatabaseQueryTool

setup_plugin_importer('parrot.tools', 'tools')


__all__ = (
    "PythonREPLTool",
    "PythonPandasTool",
    "AbstractTool",
    "ToolResult",
    "MathTool",
    "QSourceTool",
    "DatabaseQueryTool",
    "AbstractToolkit",
    "ToolkitTool",
    "tool_schema",
    "tool",
    "DuckDuckGoToolkit",
    "QueryToolkit",
)

# Enable dynamic imports
def __getattr__(name):
    return dynamic_import_helper(__name__, name)
