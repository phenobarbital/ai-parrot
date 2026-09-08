"""Unit tests for routing `LiveToolAdapter.execute_tool()` through
`AbstractTool.execute()` instead of the private `_execute()` (TASK-1956).
"""

from types import SimpleNamespace

import pytest

from parrot.clients.google.live import LiveToolAdapter
from parrot.tools import AbstractTool, ToolResult


class VoiceTool(AbstractTool):
    name = "voice_tool"
    description = "Returns a bulky result plus voice/display fields."

    async def _execute(self, **kwargs):
        return ToolResult(
            result=[{"a": i, "b": None} for i in range(500)],
            voice_text="Here are your five hundred rows.",
            display_data={"chart": "bar", "series": [1, 2, 3]},
        )


class ForbiddenTool(AbstractTool):
    """A tool whose `execute()` denies before `_execute()` ever runs —
    the shape `AbstractTool.execute()` produces for a real Layer-2
    permission denial (abstract.py:559-569), without needing a full
    PermissionContext/resolver wiring in this unit test."""

    name = "forbidden_tool"
    description = "Always denied."
    _executed = False

    async def _execute(self, **kwargs):
        type(self)._executed = True
        return {"should": "never reach here"}

    async def execute(self, *args, **kwargs) -> ToolResult:
        return ToolResult(
            success=False,
            status="forbidden",
            result=None,
            error="Permission denied: 'forbidden_tool' requires {'x'}",
        )


class ErroringTool(AbstractTool):
    name = "erroring_live_tool"
    description = "Always raises inside _execute()."

    async def _execute(self, **kwargs):
        raise RuntimeError("kaboom")


def plain_callable(**kwargs):
    return "ok"


def _call(tool_name: str, args: dict | None = None):
    return SimpleNamespace(name=tool_name, id="call-1", args=args or {})


@pytest.fixture
def live_client():
    return LiveToolAdapter(
        tool_manager=None,
        tools=[VoiceTool(), ForbiddenTool(), ErroringTool(), plain_callable],
    )


class TestLiveRouting:
    async def test_live_voice_fields_never_compressed(self, live_client):
        resp, display = await live_client.execute_tool(_call("voice_tool"))
        assert resp.response["output"] == "Here are your five hundred rows."
        assert display == {"chart": "bar", "series": [1, 2, 3]}

    async def test_goes_through_execute_not_private(self, live_client, monkeypatch):
        seen = []
        orig = AbstractTool.execute

        async def spy(self, *a, **k):
            seen.append(self.name)
            return await orig(self, *a, **k)

        monkeypatch.setattr(AbstractTool, "execute", spy)
        await live_client.execute_tool(_call("voice_tool"))
        assert seen == ["voice_tool"]

    async def test_forbidden_returns_error_response(self, live_client):
        ForbiddenTool._executed = False
        resp, display = await live_client.execute_tool(_call("forbidden_tool"))
        assert "error" in resp.response
        assert display is None
        assert ForbiddenTool._executed is False  # _execute() never ran

    async def test_error_status_returns_error_response(self, live_client):
        resp, display = await live_client.execute_tool(_call("erroring_live_tool"))
        assert "error" in resp.response
        assert display is None

    async def test_plain_callable_branch_unchanged(self, live_client):
        resp, display = await live_client.execute_tool(_call("plain_callable"))
        assert resp.response == {"output": "ok"}
        assert display is None

    async def test_return_contract_is_tuple(self, live_client):
        out = await live_client.execute_tool(_call("voice_tool"))
        assert isinstance(out, tuple) and len(out) == 2

    async def test_unknown_tool_returns_error(self, live_client):
        # Pre-existing behavior (unrelated to this task): the "not found"
        # branch returns a bare FunctionResponse, not a 2-tuple, unlike
        # every other branch. Not touched here — out of TASK-1956's scope.
        resp = await live_client.execute_tool(_call("no_such_tool"))
        assert "error" in resp.response

    async def test_no_private_execute_call_left(self):
        import inspect
        from parrot.clients.google import live as live_module

        src = inspect.getsource(live_module.LiveToolAdapter.execute_tool)
        # A prose comment may mention the OLD `_execute()` call for context;
        # what must not exist is the actual call expression.
        assert "tool._execute(" not in src
