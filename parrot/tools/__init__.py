"""
Tools infrastructure for building Agents.
"""
from parrot.plugins import setup_plugin_importer, dynamic_import_helper
from .abstract import AbstractTool, ToolResult
from .toolkit import AbstractToolkit, ToolkitTool
from .decorators import tool_schema, tool
from .vectorstoresearch import VectorStoreSearchTool

setup_plugin_importer('parrot.tools', 'tools')

__all__ = (
    "AbstractTool",
    "ToolResult",
    "AbstractToolkit",
    "ToolkitTool",
    "tool_schema",
    "tool",
    "VectorStoreSearchTool",
)

# Enable dynamic imports
def __getattr__(name):
    return dynamic_import_helper(__name__, name)

