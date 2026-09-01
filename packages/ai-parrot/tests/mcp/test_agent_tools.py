"""Unit tests for the `@mcp_tool` decorator (FEAT-477, TASK-2599) and for
`AgentMethodTool` / `build_exposure_set` reification (FEAT-477, TASK-2600).
"""

import gc
import weakref

import pytest
from parrot.mcp.adapter import MCPToolAdapter
from parrot.mcp.agent_tools import (
    MCP_TOOL_ATTR,
    AgentMethodTool,
    MCPToolDeclaration,
    build_exposure_set,
    mcp_tool,
)
from parrot.tools.abstract import AbstractTool
from pydantic import BaseModel


class Args(BaseModel):
    q: str


class Ret(BaseModel):
    ok: bool


class TestMcpToolDecorator:
    """Unit tests for `mcp_tool` and `MCPToolDeclaration`."""

    def test_marks_function_with_declaration(self):
        @mcp_tool(name="f", description="d", args_schema=Args, returns=Ret, scope="s")
        async def f(self, q: str): ...

        decl = getattr(f, MCP_TOOL_ATTR)
        assert isinstance(decl, MCPToolDeclaration)
        assert decl.name == "f" and decl.scope == "s"

    def test_rejects_sync_method(self):
        with pytest.raises(TypeError, match="async"):

            @mcp_tool(name="f", description="d", args_schema=Args, returns=Ret, scope="s")
            def f(self): ...

    @pytest.mark.parametrize("missing", ["name", "description", "args_schema", "returns", "scope"])
    def test_every_field_is_mandatory(self, missing):
        kwargs = {"name": "f", "description": "d", "args_schema": Args, "returns": Ret, "scope": "s"}
        kwargs.pop(missing)
        with pytest.raises(TypeError):
            mcp_tool(**kwargs)

    def test_rejects_non_basemodel_schema(self):
        with pytest.raises((TypeError, ValueError)):

            @mcp_tool(name="f", description="d", args_schema=dict, returns=Ret, scope="s")
            async def f(self): ...

    def test_annotation_defaults(self):
        @mcp_tool(name="f", description="d", args_schema=Args, returns=Ret, scope="s")
        async def f(self): ...

        decl = getattr(f, MCP_TOOL_ATTR)
        assert decl.read_only_hint is False and decl.idempotent_hint is False
        assert decl.requires_confirmation is False and decl.max_result_tokens is None

    def test_decorator_returns_function_unchanged(self):
        @mcp_tool(name="f", description="d", args_schema=Args, returns=Ret, scope="s")
        async def f(self, q: str) -> dict:
            return {"q": q}

        import asyncio

        result = asyncio.run(f(None, q="hi"))
        assert result == {"q": "hi"}

    def test_rejects_empty_scope(self):
        with pytest.raises(TypeError):

            @mcp_tool(name="f", description="d", args_schema=Args, returns=Ret, scope="")
            async def f(self): ...


class _FakeToolManager:
    """Minimal duck-typed stand-in for `ToolManager.list_tools()`."""

    def __init__(self, existing_tools: list[str] | None = None):
        self._existing = list(existing_tools or [])

    def list_tools(self) -> list[str]:
        return list(self._existing)


class _ExposedAgent:
    """A minimal agent with one `@mcp_tool` method and one ordinary tool."""

    def __init__(self):
        self.tool_manager = _FakeToolManager(existing_tools=["ordinary_tool"])

    @mcp_tool(name="exposed_method", description="d", args_schema=Args, returns=Ret, scope="s:read")
    async def exposed_method(self, q: str) -> dict:
        return {"echo": q}


class _DupAgent:
    """An agent whose two decorated methods declare the same MCP name."""

    def __init__(self):
        self.tool_manager = _FakeToolManager()

    @mcp_tool(name="dup", description="d", args_schema=Args, returns=Ret, scope="s")
    async def method_a(self, q: str): ...

    @mcp_tool(name="dup", description="d", args_schema=Args, returns=Ret, scope="s")
    async def method_b(self, q: str): ...


def make_agent() -> _ExposedAgent:
    """Factory for a fresh `_ExposedAgent` instance (GC test needs no lingering refs)."""
    return _ExposedAgent()


@pytest.fixture
def exposed_agent() -> _ExposedAgent:
    return _ExposedAgent()


@pytest.fixture
def agent_with_dup_names() -> _DupAgent:
    return _DupAgent()


class TestReification:
    """Reification tests for `AgentMethodTool` + `build_exposure_set` (TASK-2600)."""

    def test_reified_is_abstracttool_and_adapts(self, exposed_agent):
        tools = build_exposure_set(exposed_agent)
        assert len(tools) == 1
        tool = tools[0]
        assert isinstance(tool, AbstractTool)
        assert isinstance(tool, AgentMethodTool)
        defn = MCPToolAdapter(tool).to_mcp_tool_definition()
        assert defn["name"] == tool.name
        assert "inputSchema" in defn

    def test_reified_tool_not_in_tool_manager(self, exposed_agent):
        """OQ2 INVARIANT — merge blocker. Decorating exposes over MCP and nothing else."""
        before = set(exposed_agent.tool_manager.list_tools())
        tools = build_exposure_set(exposed_agent)
        after = set(exposed_agent.tool_manager.list_tools())
        assert after == before
        assert {t.name for t in tools}.isdisjoint(after)

    def test_annotations_map_to_routing_meta(self, exposed_agent):
        tool = build_exposure_set(exposed_agent)[0]
        assert "requires_confirmation" in tool.routing_meta
        assert "read_only_hint" in tool.routing_meta
        assert "idempotent_hint" in tool.routing_meta

    @pytest.mark.asyncio
    async def test_execute_calls_bound_method(self, exposed_agent):
        tool = build_exposure_set(exposed_agent)[0]
        result = await tool._execute(q="x")
        assert result == {"echo": "x"}

    def test_duplicate_name_fails_with_agent_in_message(self, agent_with_dup_names):
        with pytest.raises(ValueError, match=r"(?s)agent.*method"):
            build_exposure_set(agent_with_dup_names)

    def test_name_collision_with_existing_tool_fails(self):
        class _CollidingAgent:
            def __init__(self):
                self.tool_manager = _FakeToolManager(existing_tools=["taken"])

            @mcp_tool(name="taken", description="d", args_schema=Args, returns=Ret, scope="s")
            async def method(self, q: str): ...

        with pytest.raises(ValueError, match=r"(?s)agent.*taken"):
            build_exposure_set(_CollidingAgent())

    def test_agent_held_weakly(self):
        agent = make_agent()
        tool = build_exposure_set(agent)[0]
        ref = weakref.ref(agent)
        del agent
        gc.collect()
        assert ref() is None
        assert tool is not None

    @pytest.mark.asyncio
    async def test_execute_raises_clean_error_after_agent_gc(self):
        agent = make_agent()
        tool = build_exposure_set(agent)[0]
        del agent
        gc.collect()
        with pytest.raises(RuntimeError, match="garbage-collected"):
            await tool._execute(q="x")

    def test_no_declared_methods_returns_empty_exposure_set(self):
        class _PlainAgent:
            def __init__(self):
                self.tool_manager = _FakeToolManager()

        assert build_exposure_set(_PlainAgent()) == []
