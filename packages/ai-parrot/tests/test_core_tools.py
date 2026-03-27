"""Tests verifying core tools are always available without ai-parrot-tools.

These tools live in packages/ai-parrot/src/parrot/tools/ (NOT in parrot_tools)
and must be importable regardless of whether ai-parrot-tools is installed.
"""
import pytest


class TestCoreToolsAlwaysAvailable:
    """These tools are exported in both old and new layouts."""

    def test_abstract_tool(self):
        from parrot.tools import AbstractTool
        assert AbstractTool is not None

    def test_abstract_toolkit(self):
        from parrot.tools import AbstractToolkit
        assert AbstractToolkit is not None

    def test_tool_result(self):
        from parrot.tools import ToolResult
        assert ToolResult is not None

    def test_toolkit_tool(self):
        from parrot.tools import ToolkitTool
        assert ToolkitTool is not None

    def test_tool_decorator(self):
        from parrot.tools import tool
        assert callable(tool)

    def test_tool_schema(self):
        from parrot.tools import tool_schema
        assert callable(tool_schema)

    def test_toolkit_registry(self):
        from parrot.tools import ToolkitRegistry
        assert ToolkitRegistry is not None

    def test_get_supported_toolkits(self):
        from parrot.tools import get_supported_toolkits
        assert callable(get_supported_toolkits)

    def test_vector_store_search_tool(self):
        from parrot.tools import VectorStoreSearchTool
        assert VectorStoreSearchTool is not None


class TestCoreToolsDirectImport:
    """Verify tools can be imported from their submodules directly."""

    def test_pythonrepl_direct(self):
        from parrot.tools.pythonrepl import PythonREPLTool
        assert PythonREPLTool is not None

    def test_openapitoolkit_direct(self):
        from parrot.tools.openapitoolkit import OpenAPIToolkit
        assert OpenAPIToolkit is not None

    def test_agent_direct(self):
        from parrot.tools.agent import AgentTool
        assert AgentTool is not None

    def test_multistoresearch_direct(self):
        from parrot.tools.multistoresearch import MultiStoreSearchTool
        assert MultiStoreSearchTool is not None

    def test_resttool_direct(self):
        from parrot.tools.resttool import RESTTool
        assert RESTTool is not None

    def test_json_tool_direct(self):
        from parrot.tools.json_tool import ToJsonTool
        assert ToJsonTool is not None

    def test_mcp_mixin_direct(self):
        from parrot.tools.mcp_mixin import MCPToolManagerMixin
        assert MCPToolManagerMixin is not None
