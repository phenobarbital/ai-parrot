"""Unit tests for :class:`AbstractToolkit` lifecycle hooks.

Covers TASK-747 from FEAT-107 (Jira OAuth 2.0 3LO):

    - ``AbstractToolkit._pre_execute`` is invoked before every bound method.
    - ``AbstractToolkit._post_execute`` is invoked after and can transform
      the result.
    - Exceptions raised in ``_pre_execute`` propagate to the caller.
    - ``_pre_execute`` / ``_post_execute`` are NOT exposed as tools by
      :meth:`AbstractToolkit.get_tools`.
"""
from __future__ import annotations

import pytest

from parrot.tools.toolkit import AbstractToolkit


class SpyToolkit(AbstractToolkit):
    """Toolkit that records every hook invocation for inspection."""

    def __init__(self) -> None:
        super().__init__()
        self.pre_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, object]] = []

    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        self.pre_calls.append((tool_name, kwargs))

    async def _post_execute(self, tool_name: str, result, **kwargs):
        self.post_calls.append((tool_name, result))
        return result

    async def greet(self, name: str) -> str:
        """Say hello to *name*."""
        return f"Hello, {name}"


class RaisingToolkit(AbstractToolkit):
    """Toolkit whose ``_pre_execute`` always fails."""

    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        raise PermissionError("Not authorized")

    async def do_something(self) -> str:
        """Do a thing."""
        return "done"


class TransformToolkit(AbstractToolkit):
    """Toolkit that decorates every return value from its tools."""

    async def _post_execute(self, tool_name: str, result, **kwargs):
        return f"[transformed] {result}"

    async def compute(self) -> str:
        """Compute a value."""
        return "raw"


def _find_tool(toolkit: AbstractToolkit, name: str):
    for tool in toolkit.get_tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"Tool {name!r} not registered on {toolkit}")


class TestLifecycleHooks:
    @pytest.mark.asyncio
    async def test_pre_execute_called_before_tool(self):
        tk = SpyToolkit()
        tool = _find_tool(tk, "greet")
        await tool._execute(name="World")
        assert len(tk.pre_calls) == 1
        assert tk.pre_calls[0][0] == "greet"
        # _permission_context=None is always injected by ToolkitTool._execute
        # (FEAT-107: _current_pctx forwarding). Strip it before comparing.
        kwargs_without_pctx = {
            k: v for k, v in tk.pre_calls[0][1].items()
            if k != "_permission_context"
        }
        assert kwargs_without_pctx == {"name": "World"}
        assert tk.pre_calls[0][1].get("_permission_context") is None

    @pytest.mark.asyncio
    async def test_post_execute_called_after_tool(self):
        tk = SpyToolkit()
        tool = _find_tool(tk, "greet")
        result = await tool._execute(name="World")
        assert result == "Hello, World"
        assert len(tk.post_calls) == 1
        assert tk.post_calls[0] == ("greet", "Hello, World")

    @pytest.mark.asyncio
    async def test_pre_execute_exception_propagates(self):
        tk = RaisingToolkit()
        tool = _find_tool(tk, "do_something")
        with pytest.raises(PermissionError, match="Not authorized"):
            await tool._execute()

    @pytest.mark.asyncio
    async def test_post_execute_transforms_result(self):
        tk = TransformToolkit()
        tool = _find_tool(tk, "compute")
        result = await tool._execute()
        assert result == "[transformed] raw"

    def test_hooks_not_exposed_as_tools(self):
        tk = SpyToolkit()
        tool_names = [t.name for t in tk.get_tools()]
        assert "_pre_execute" not in tool_names
        assert "_post_execute" not in tool_names

    @pytest.mark.asyncio
    async def test_base_hooks_are_noops(self):
        class BareToolkit(AbstractToolkit):
            async def echo(self, value: str) -> str:
                """Echo *value* back."""
                return value

        tk = BareToolkit()
        tool = _find_tool(tk, "echo")
        # Base class hooks should not raise and must not interfere with result.
        result = await tool._execute(value="ping")
        assert result == "ping"


class TestPermissionContextForwarding:
    """Verify _permission_context is available inside _pre_execute when routed through ToolManager."""

    @pytest.mark.asyncio
    async def test_permission_context_forwarded_to_pre_execute(self) -> None:
        """Full chain: execute_tool → execute → _execute → _pre_execute gets pctx."""
        from parrot.tools.manager import ToolManager
        from parrot.auth.permission import PermissionContext, UserSession

        received: dict = {}

        class ObservingToolkit(AbstractToolkit):
            async def _pre_execute(self, tool_name: str, **kwargs) -> None:
                received["pctx"] = kwargs.get("_permission_context")

            async def observe(self) -> str:
                """Return a fixed string."""
                return "ok"

        session = UserSession(user_id="u-test", tenant_id="t-test", roles=frozenset())
        ctx = PermissionContext(session=session)

        tk = ObservingToolkit()
        manager = ToolManager()
        manager.register_toolkit(tk)

        await manager.execute_tool("observe", {}, permission_context=ctx)

        assert received.get("pctx") is ctx, (
            "_permission_context was not forwarded to _pre_execute; "
            f"received: {received.get('pctx')!r}"
        )

    @pytest.mark.asyncio
    async def test_permission_context_none_when_not_provided(self) -> None:
        """_permission_context kwarg is None (not missing) in _pre_execute when not set."""
        received: dict = {}

        class NullContextToolkit(AbstractToolkit):
            async def _pre_execute(self, tool_name: str, **kwargs) -> None:
                received["pctx"] = kwargs.get("_permission_context", "MISSING")

            async def act(self) -> str:
                """Do something."""
                return "done"

        tk = NullContextToolkit()
        from parrot.tools.manager import ToolManager
        manager = ToolManager()
        manager.register_toolkit(tk)

        await manager.execute_tool("act", {})  # no permission_context

        # Should be None (not the "MISSING" sentinel) because _current_pctx is always set
        assert received["pctx"] is None
