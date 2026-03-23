"""
Tools infrastructure for building Agents.

Resolution chain for tool imports:
1. Core tools (always available — defined directly in this module)
2. parrot_tools (ai-parrot-tools installed package)
3. plugins.tools (user/deploy-time plugin directory)
4. TOOL_REGISTRY (declarative registry from ai-parrot-tools)
5. Legacy dynamic_import_helper (backward-compat submodule resolution)
"""
import importlib
import sys
from typing import Optional

from parrot.plugins import setup_plugin_importer, dynamic_import_helper

# ---------------------------------------------------------------------------
# Core base classes (always available)
# ---------------------------------------------------------------------------
from .abstract import AbstractTool, ToolResult
from .toolkit import AbstractToolkit, ToolkitTool
from .decorators import tool_schema, tool
from .registry import ToolkitRegistry, get_supported_toolkits

# ---------------------------------------------------------------------------
# Core tools that stay in ai-parrot (no ai-parrot-tools needed)
# ---------------------------------------------------------------------------
from .vectorstoresearch import VectorStoreSearchTool
from .multistoresearch import MultiStoreSearchTool
from .pythonrepl import PythonREPLTool
from .openapitoolkit import OpenAPIToolkit
from .resttool import RESTTool
from .mcp_mixin import MCPToolManagerMixin
from .json_tool import ToJsonTool
from .agent import AgentTool

# ---------------------------------------------------------------------------
# Plugin importer setup (existing plugin system)
# ---------------------------------------------------------------------------
setup_plugin_importer('parrot.tools', 'tools')

# ---------------------------------------------------------------------------
# Resolution sources for external tools (ai-parrot-tools, plugins)
# ---------------------------------------------------------------------------
_TOOL_SOURCES = [
    "parrot_tools",       # ai-parrot-tools installed package
    "plugins.tools",      # user/deploy-time plugin directory
]


def _resolve_from_sources(name: str) -> Optional[object]:
    """Try to import `name` as a submodule from each source in order."""
    for source in _TOOL_SOURCES:
        try:
            return importlib.import_module(f"{source}.{name}")
        except ImportError:
            continue
    return None


def _resolve_from_registry(name: str) -> Optional[object]:
    """Fallback: resolve from TOOL_REGISTRY in parrot_tools."""
    try:
        from parrot_tools import TOOL_REGISTRY
    except ImportError:
        return None

    dotted_path = TOOL_REGISTRY.get(name)
    if not dotted_path:
        return None

    module_path, class_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


__all__ = (
    # Base classes
    "AbstractTool",
    "ToolResult",
    "AbstractToolkit",
    "ToolkitTool",
    "tool_schema",
    "tool",
    "ToolkitRegistry",
    "get_supported_toolkits",
    # Core tools
    "VectorStoreSearchTool",
    "MultiStoreSearchTool",
    "PythonREPLTool",
    "OpenAPIToolkit",
    "RESTTool",
    "MCPToolManagerMixin",
    "ToJsonTool",
    "AgentTool",
)


def __getattr__(name: str):
    """Resolve tool imports from external sources.

    Only fires for names NOT already defined above (core tools, base classes).
    Resolution order:
    1. parrot_tools package (ai-parrot-tools)
    2. plugins.tools directory
    3. TOOL_REGISTRY declarative lookup
    4. Legacy dynamic_import_helper (submodule convention)
    """
    # Skip dunder/private names
    if name.startswith("_"):
        raise AttributeError(name)

    # --- Legacy lazy imports (tools still in core, not yet migrated) ---
    if name in ('DatasetManager', 'DatasetInfo', 'DatasetEntry'):
        from .dataset_manager import DatasetManager, DatasetInfo, DatasetEntry
        return locals()[name]
    if name in ('ExcelTool', 'DataFrameToExcelTool'):
        from .excel import ExcelTool, DataFrameToExcelTool
        return locals()[name]
    if name in ('CSVExportTool', 'DataFrameToCSVTool'):
        from .csv_export import CSVExportTool, DataFrameToCSVTool
        return locals()[name]
    if name in (
        'CloudPostureToolkit',
        'ContainerSecurityToolkit',
        'SecretsIaCToolkit',
        'ComplianceReportToolkit',
    ):
        from .security import (
            CloudPostureToolkit,
            ContainerSecurityToolkit,
            SecretsIaCToolkit,
            ComplianceReportToolkit,
        )
        return locals()[name]
    if name == 'CompositeScoreTool':
        from .composite_score import CompositeScoreTool
        return CompositeScoreTool

    # --- External resolution (ai-parrot-tools package) ---
    result = _resolve_from_sources(name)
    if result is not None:
        # Cache in module dict to avoid repeated __getattr__ calls
        setattr(sys.modules[__name__], name, result)
        return result

    # --- Registry fallback (class-level resolution) ---
    result = _resolve_from_registry(name)
    if result is not None:
        setattr(sys.modules[__name__], name, result)
        return result

    # --- Legacy: dynamic_import_helper (submodule convention) ---
    try:
        return dynamic_import_helper(__name__, name)
    except AttributeError:
        pass

    raise ImportError(
        f"Tool '{name}' not found. "
        f"Install with: pip install ai-parrot-tools  or  "
        f"pip install ai-parrot-tools[{name}]"
    )
