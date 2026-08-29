"""Unit tests for FEAT-474 — ToolManager ToolDefinition enforcement parity.

This module holds the shared unit-test surface for the feature (Modules
1-3): ToolDefinition model defaults, @tool decorator metadata, registration
metadata preservation, and execute_tool() enforcement parity. Tests are
added incrementally as each task lands; this task (TASK-2578) covers the
model + decorator foundation only.
"""
import logging

from parrot.tools.decorators import tool
from parrot.tools.manager import ToolDefinition, ToolManager


class TestToolDefinitionModel:
    """ToolDefinition dataclass defaults and slot behaviour (FEAT-474 G3)."""

    def test_legacy_keyword_construction(self):
        td = ToolDefinition(name="t", description="d", input_schema={}, function=lambda: 1)
        assert td.routing_meta == {}
        assert td.required_permissions == set()

    def test_legacy_positional_construction(self):
        td = ToolDefinition("t", "d", {}, lambda: 1)
        assert td.required_permissions == set()

    def test_slots_no_dict(self):
        td = ToolDefinition("t", "d", {}, lambda: 1)
        assert not hasattr(td, "__dict__")

    def test_defaults_not_shared_between_instances(self):
        a = ToolDefinition("a", "d", {}, lambda: 1)
        b = ToolDefinition("b", "d", {}, lambda: 1)
        a.routing_meta["k"] = "v"
        assert b.routing_meta == {}


class TestToolDecoratorRequiredPermissions:
    """@tool decorator required_permissions support (FEAT-474 G3)."""

    def test_required_permissions_stored(self):
        @tool(required_permissions={"reports:read"})
        def f(x: int) -> str:
            """Doc."""
            return str(x)
        assert f._tool_metadata["required_permissions"] == {"reports:read"}

    def test_default_empty(self):
        @tool
        def g(x: int) -> str:
            """Doc."""
            return str(x)
        assert g._tool_metadata["required_permissions"] == set()

    def test_routing_meta_still_built(self):
        @tool(requires_confirmation=True, confirm_window_seconds=30)
        def h(x: int) -> str:
            """Doc."""
            return str(x)
        assert h._tool_metadata["routing_meta"]["requires_confirmation"] is True


class TestRegistrationMetadata:
    """Registration preserves routing_meta/required_permissions (FEAT-474 G2/G5)."""

    def test_manager_preserves_routing_meta(self):
        tm = ToolManager()

        @tool(requires_confirmation=True, required_permissions={"p"})
        def f(x: int) -> str:
            """Doc."""
            return str(x)
        tm.register_tool(f)
        td = tm.get_tool("f")
        assert td.routing_meta["requires_confirmation"] is True
        assert td.required_permissions == {"p"}

    def test_inert_grant_warning(self, caplog):
        tm = ToolManager()
        td = ToolDefinition(
            "g", "d", {}, lambda: 1,
            routing_meta={"requires_grant": True},
        )
        with caplog.at_level(logging.WARNING):
            tm.register_tool(td)
        assert any("grant" in r.message.lower() for r in caplog.records)

    def test_no_warning_for_confirmation_only(self, caplog):
        tm = ToolManager()
        td = ToolDefinition(
            "h", "d", {}, lambda: 1,
            routing_meta={"requires_confirmation": True},
        )
        with caplog.at_level(logging.WARNING):
            tm.register_tool(td)
        assert not any("grant" in r.message.lower() for r in caplog.records)

    def test_interfaces_tools_preserves_routing_meta(self):
        """`ToolInterface._initialize_tools()`'s @tool conversion site (the
        2nd construction site, interfaces/tools.py:77) preserves routing_meta
        and required_permissions identically to the manager.py path."""
        from parrot.interfaces.tools import ToolInterface

        class _Harness(ToolInterface):
            def __init__(self) -> None:
                self.logger = logging.getLogger("test.harness")
                self.tool_manager = ToolManager(logger=self.logger)

            def _capture_knowledge_toolkit(self, instance) -> None:
                pass

        @tool(requires_confirmation=True, required_permissions={"p"})
        def i(x: int) -> str:
            """Doc."""
            return str(x)

        harness = _Harness()
        harness._initialize_tools([i])
        td = harness.tool_manager.get_tool("i")
        assert td.routing_meta["requires_confirmation"] is True
        assert td.required_permissions == {"p"}
