"""
Tools infrastructure for building Agents.
"""
from parrot.plugins import setup_plugin_importer, dynamic_import_helper
from .abstract import AbstractTool, ToolResult
from .toolkit import AbstractToolkit, ToolkitTool
from .decorators import tool_schema, tool
from .vectorstoresearch import VectorStoreSearchTool
from .registry import ToolkitRegistry, get_supported_toolkits
from .dataset_manager import DatasetManager, DatasetInfo, DatasetEntry

setup_plugin_importer('parrot.tools', 'tools')

__all__ = (
    "AbstractTool",
    "ToolResult",
    "AbstractToolkit",
    "ToolkitTool",
    "tool_schema",
    "tool",
    "VectorStoreSearchTool",
    "ToolkitRegistry",
    "get_supported_toolkits",
    "DatasetManager",
    "DatasetInfo",
    "DatasetEntry",
    # Document Tools
    "ExcelTool",
    "DataFrameToExcelTool",
    "CSVExportTool",
    "DataFrameToCSVTool",
    # Security Toolkits
    "CloudPostureToolkit",
    "ContainerSecurityToolkit",
    "SecretsIaCToolkit",
    "ComplianceReportToolkit",
    # Finance Toolkits
    "CompositeScoreTool",
)

# Enable dynamic imports
def __getattr__(name):
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
    return dynamic_import_helper(__name__, name)

