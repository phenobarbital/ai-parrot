"""Unit tests for the `@mcp_tool` decorator (FEAT-477, TASK-2599)."""
import pytest
from parrot.mcp.agent_tools import MCP_TOOL_ATTR, MCPToolDeclaration, mcp_tool
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

    @pytest.mark.parametrize(
        "missing", ["name", "description", "args_schema", "returns", "scope"]
    )
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
