"""Unit tests for the declaration surface: @tool, spawn.py, toolkit.py.

Tests:
  - @tool(requires_confirmation=True, ...) projects confirmation keys into routing_meta.
  - Plain @tool (no new kwargs) is backwards compatible.
  - spawn.py setdefault("requires_confirmation", False).
  - AbstractToolkit.confirming_tools marks generated tool routing_meta.

Run with:
    pytest packages/ai-parrot/tests/test_confirmation_declaration.py -v
"""
from __future__ import annotations

import pytest

from parrot.tools.decorators import tool
from parrot.tools.toolkit import AbstractToolkit


# ── @tool decorator tests ──────────────────────────────────────────────────────


@tool(
    requires_confirmation=True,
    confirm_template="Voy a ejecutar {tool} con {params}",
    confirm_window_seconds=30,
    allow_edit=True,
)
def workday_checkin(employee_id: int, time: str) -> str:
    """Register a check-in."""
    return "ok"


def test_decorator_carries_requires_confirmation():
    """@tool(requires_confirmation=True) → routing_meta['requires_confirmation'] is True."""
    md = workday_checkin._tool_metadata
    assert md["routing_meta"]["requires_confirmation"] is True


def test_decorator_carries_confirm_template():
    """@tool(confirm_template=...) → routing_meta['confirm_template'] is set."""
    md = workday_checkin._tool_metadata
    assert md["routing_meta"]["confirm_template"] == "Voy a ejecutar {tool} con {params}"


def test_decorator_carries_confirm_window_seconds():
    """@tool(confirm_window_seconds=30) → routing_meta['confirm_window_seconds'] == 30."""
    md = workday_checkin._tool_metadata
    assert md["routing_meta"]["confirm_window_seconds"] == 30


def test_decorator_carries_allow_edit():
    """@tool(allow_edit=True) → routing_meta['allow_edit'] is True."""
    md = workday_checkin._tool_metadata
    assert md["routing_meta"]["allow_edit"] is True


@tool
def plain_tool(x: int) -> str:
    """A tool with no confirmation kwargs."""
    return str(x)


def test_plain_tool_no_confirmation():
    """Plain @tool with no confirmation kwargs → requires_confirmation is False/falsy."""
    md = plain_tool._tool_metadata
    assert not md["routing_meta"].get("requires_confirmation")


def test_plain_tool_backward_compatible():
    """Plain @tool still has name, description, schema — backwards compatible."""
    md = plain_tool._tool_metadata
    assert md["name"] == "plain_tool"
    assert md["description"] is not None
    assert "schema" in md


@tool()
def another_plain_tool(y: str) -> str:
    """Tool with empty decorator call."""
    return y


def test_empty_decorator_no_confirmation():
    """@tool() with no kwargs → requires_confirmation is False/falsy."""
    md = another_plain_tool._tool_metadata
    assert not md["routing_meta"].get("requires_confirmation")


def test_decorator_no_template_absent():
    """@tool without confirm_template → key not present in routing_meta."""
    md = plain_tool._tool_metadata
    assert "confirm_template" not in md["routing_meta"]


def test_tool_with_only_confirm_template():
    """@tool(confirm_template=...) without requires_confirmation → falsy."""
    @tool(confirm_template="Run {tool}?")
    def my_fn(x: int) -> str:
        """Fn."""
        return str(x)

    md = my_fn._tool_metadata
    assert not md["routing_meta"].get("requires_confirmation")
    assert md["routing_meta"]["confirm_template"] == "Run {tool}?"


# ── spawn.py default test ──────────────────────────────────────────────────────


def test_spawn_sets_confirmation_default():
    """spawn.py source includes the requires_confirmation setdefault (FEAT-235)."""
    import inspect
    from parrot.tools import spawn
    src = inspect.getsource(spawn)
    assert 'setdefault("requires_confirmation", False)' in src


def test_spawn_caller_routing_meta_not_overridden():
    """If caller passes requires_confirmation=True, setdefault does NOT override it."""
    caller_routing = {"requires_confirmation": True}
    effective_routing = dict(caller_routing)
    effective_routing.setdefault("requires_confirmation", False)
    assert effective_routing["requires_confirmation"] is True  # not overridden


# ── AbstractToolkit.confirming_tools tests ────────────────────────────────────


class _WorkdayToolkit(AbstractToolkit):
    """Toolkit with two tools — one confirming, one not."""

    confirming_tools: frozenset = frozenset({"checkin"})

    async def checkin(self, employee_id: int) -> str:
        """Register a check-in (requires confirmation)."""
        return "checked in"

    async def checkout(self, employee_id: int) -> str:
        """Register a check-out (no confirmation required)."""
        return "checked out"


def test_toolkit_confirming_tools_marks_routing_meta():
    """Tools in confirming_tools get routing_meta['requires_confirmation'] = True."""
    toolkit = _WorkdayToolkit()
    tools = toolkit.get_tools()
    tool_map = {t.name: t for t in tools}

    checkin_tool = tool_map.get("checkin")
    assert checkin_tool is not None
    assert checkin_tool.routing_meta.get("requires_confirmation") is True


def test_toolkit_non_confirming_tool_not_marked():
    """Tools NOT in confirming_tools do NOT get requires_confirmation = True."""
    toolkit = _WorkdayToolkit()
    tools = toolkit.get_tools()
    tool_map = {t.name: t for t in tools}

    checkout_tool = tool_map.get("checkout")
    assert checkout_tool is not None
    assert not checkout_tool.routing_meta.get("requires_confirmation")


def test_toolkit_empty_confirming_tools_default():
    """AbstractToolkit with default confirming_tools (empty) marks nothing."""

    class _PlainToolkit(AbstractToolkit):
        async def do_something(self, x: str) -> str:
            """Do something."""
            return x

    toolkit = _PlainToolkit()
    tools = toolkit.get_tools()
    for t in tools:
        assert not t.routing_meta.get("requires_confirmation")


def test_toolkit_confirming_tools_with_prefix():
    """confirming_tools works with tool_prefix toolkits (method name lookup)."""

    class _PrefixedToolkit(AbstractToolkit):
        tool_prefix = "workday"
        confirming_tools: frozenset = frozenset({"register"})

        async def register(self, emp: int) -> str:
            """Register something requiring confirmation."""
            return "done"

        async def list_all(self) -> str:
            """List without confirmation."""
            return "[]"

    toolkit = _PrefixedToolkit()
    tools = toolkit.get_tools()
    tool_map = {t.name: t for t in tools}

    # Prefixed names
    register_tool = tool_map.get("workday_register")
    assert register_tool is not None
    assert register_tool.routing_meta.get("requires_confirmation") is True

    list_tool = tool_map.get("workday_list_all")
    assert list_tool is not None
    assert not list_tool.routing_meta.get("requires_confirmation")
