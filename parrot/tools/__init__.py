"""
Tools infrastructure for building Agents.
"""
from parrot.plugins import setup_plugin_importer, dynamic_import_helper
from .pythonrepl import PythonREPLTool
from .pythonpandas import PythonPandasTool
from .metadata import MetadataTool
from .abstract import AbstractTool, ToolResult
from .google.base import GoogleBaseTool, GoogleToolArgsSchema, GoogleAuthMode
from .math import MathTool
from .toolkit import AbstractToolkit, ToolkitTool
from .decorators import tool_schema, tool
from .ddgo import DuckDuckGoToolkit
from .file_reader import FileReaderTool
from .yfinance_tool import YFinanceTool

# setup_plugin_importer('parrot.tools', 'tools')

__all__ = (
    "PythonREPLTool",
    "PythonPandasTool",
    "AbstractTool",
    "ToolResult",
    "GoogleBaseTool",
    "GoogleToolArgsSchema",
    "GoogleAuthMode",
    "MathTool",
    "AbstractToolkit",
    "ToolkitTool",
    "tool_schema",
    "tool",
    "DuckDuckGoToolkit",
    "FileReaderTool",
    "YFinanceTool",
    "MetadataTool",
)

# Enable dynamic imports
def __getattr__(name):
    return dynamic_import_helper(__name__, name)
