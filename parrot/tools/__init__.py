"""
Tools infrastructure for building Agents.
"""
from .pythonrepl import PythonREPLTool
from .abstract import AbstractTool, ToolResult
from .math import MathTool
from .toolkit import AbstractToolkit, ToolkitTool
from .decorators import tool_schema, tool
from .querytoolkit import QueryToolkit
from .qsource import QuerySourceTool
from .ddgo import DuckDuckGoToolkit


__all__ = (
    "PythonREPLTool",
    "AbstractTool",
    "ToolResult",
    "MathTool",
    "QuerySourceTool",
    "AbstractToolkit",
    "ToolkitTool",
    "tool_schema",
    "tool",
    "DuckDuckGoToolkit",
    "QueryToolkit",
)
