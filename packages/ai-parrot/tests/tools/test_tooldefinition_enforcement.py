"""Unit tests for FEAT-474 — ToolManager ToolDefinition enforcement parity.

This module holds the shared unit-test surface for the feature (Modules
1-3): ToolDefinition model defaults, @tool decorator metadata, registration
metadata preservation, and execute_tool() enforcement parity. Tests are
added incrementally as each task lands; this task (TASK-2578) covers the
model + decorator foundation only.
"""
from parrot.tools.manager import ToolDefinition
from parrot.tools.decorators import tool


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
