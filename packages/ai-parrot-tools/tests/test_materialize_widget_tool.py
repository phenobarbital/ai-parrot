"""Unit tests for the LLM-free materialize_widget orchestration tool."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from parrot.auth.permission import build_principal_context
from parrot.memory import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import ToolInvocation
from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor
from parrot.tools.abstract import ToolResult
from parrot.tools.manager import ToolManager
from parrot_tools.materialize_widget import MaterializeWidgetTool


class FakeMemory:
    """Return the fixture history only for its owning user and session."""

    def __init__(self, history: ConversationHistory) -> None:
        self.history = history
        self.calls: list[tuple[str, str, str | None]] = []

    async def get_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: str | None = None,
    ) -> ConversationHistory | None:
        """Resolve the history for the exact owner key."""
        self.calls.append((user_id, session_id, chatbot_id))
        if (user_id, session_id) == (self.history.user_id, self.history.session_id):
            return self.history
        return None


class FakeTool:
    """Record sibling-tool calls and return a configured ToolResult."""

    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Record and return one deterministic result."""
        self.calls.append(kwargs)
        return self.result


def _turn(*invocations: ToolInvocation) -> ConversationTurn:
    """Build the owned conversation turn used by the tests."""
    return ConversationTurn(
        turn_id="t1",
        user_id="u1",
        user_message="worked hours by month",
        assistant_response="Here is the chart.",
        chatbot_id="agent",
        tool_invocations=list(invocations),
    )


def _history(turn: ConversationTurn | None = None) -> ConversationHistory:
    """Build an owned history containing one turn by default."""
    return ConversationHistory(session_id="s1", user_id="u1", chatbot_id="agent", turns=[turn or _turn(_origin())])


def _origin() -> ToolInvocation:
    """Build a completed QuerySource invocation."""
    return ToolInvocation(
        tool_name="qs_execute_slug",
        input={"slug": "flex_hours_query_pbi", "tenant": "flex", "limit": 500},
    )


def _source_envelope() -> dict[str, Any]:
    """Build the baked envelope supplied by the chat renderer."""
    return {
        "surfaceId": "chat-chart",
        "components": [
            {
                "id": "root",
                "component": "Chart",
                "type": "bar",
                "title": "Worked hours",
                "data": {"path": "/rows"},
            }
        ],
        "dataModel": {"rows": [{"month": "Jan", "hours": 12}]},
    }


def _linked_envelope() -> dict[str, Any]:
    """Build the refreshable envelope returned by the QuerySource sibling."""
    return {
        "surfaceId": "linked-hours",
        "components": [{"id": "root", "component": "Chart", "data": {"path": "/hours/rows"}}],
        "metadata": {
            "extensions": {
                "parrot_data_sources": {
                    "hours": {"slug": "flex_hours_query_pbi", "tenant": "flex"},
                }
            }
        },
    }


def _success(result: dict[str, Any]) -> ToolResult:
    """Wrap a successful fake sibling response."""
    return ToolResult(result=result)


def _failure(error: str) -> ToolResult:
    """Wrap a failed fake sibling response."""
    return ToolResult(success=False, status="error", result=None, error=error)


def _bot(
    *,
    turn: ConversationTurn | None = None,
    builder: FakeTool | None = None,
    publisher: FakeTool | None = None,
) -> SimpleNamespace:
    """Build a bot double with memory and opt-in sibling tools."""
    tools = {
        name: tool
        for name, tool in {
            "qs_build_linked_surface": builder,
            "publish_surface": publisher,
        }.items()
        if tool is not None
    }

    async def fail_if_asked(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("materialize_widget must not call the LLM")

    return SimpleNamespace(
        conversation_memory=FakeMemory(_history(turn)),
        memory_key_id="agent",
        tool_manager=SimpleNamespace(get_tool=tools.get),
        ask=fail_if_asked,
    )


@pytest.mark.asyncio
async def test_tool_materialized_happy_path() -> None:
    builder = FakeTool(_success({"a2ui_envelope": _linked_envelope(), "artifacts": [{"type": "linked"}]}))
    tool = MaterializeWidgetTool(bot=_bot(builder=builder), user_id="u1", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=_source_envelope())

    assert result.success is True
    assert result.result["status"] == "materialized"
    assert result.result["refreshable"] is True
    assert result.result["a2ui_envelope"] == _linked_envelope()
    assert builder.calls == [
        {
            "slug": "flex_hours_query_pbi",
            "component": {
                "id": "root",
                "component": "Chart",
                "type": "bar",
                "title": "Worked hours",
            },
            "request": {"limit": 500},
            "tenant": "flex",
            "snapshot": False,
            "_permission_context": None,
        }
    ]


@pytest.mark.asyncio
async def test_tool_turn_not_found_other_user() -> None:
    tool = MaterializeWidgetTool(bot=_bot(), user_id="u2", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=_source_envelope())

    assert result.result["status"] == "not_materializable"
    assert result.result["reason"] == "turn_not_found"


@pytest.mark.asyncio
async def test_tool_missing_session_id() -> None:
    tool = MaterializeWidgetTool(bot=_bot(), user_id="u1")

    result = await tool.execute(turn_id="t1", envelope=_source_envelope())

    assert result.result["status"] == "not_materializable"
    assert result.result["reason"] == "turn_not_found"


@pytest.mark.asyncio
async def test_tool_no_envelope() -> None:
    tool = MaterializeWidgetTool(bot=_bot(), user_id="u1", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=None)

    assert result.result["status"] == "not_materializable"
    assert result.result["reason"] == "no_envelope"


@pytest.mark.asyncio
async def test_tool_no_querysource_toolkit() -> None:
    tool = MaterializeWidgetTool(bot=_bot(), user_id="u1", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=_source_envelope())

    assert result.result["status"] == "not_materializable"
    assert result.result["reason"] == "no_querysource_toolkit"


@pytest.mark.asyncio
async def test_tool_snapshot_only_no_origin() -> None:
    builder = FakeTool(_success({"a2ui_envelope": _linked_envelope()}))
    turn = _turn(ToolInvocation(tool_name="python_pandas", input={"code": "frame.plot()"}))
    tool = MaterializeWidgetTool(bot=_bot(turn=turn, builder=builder), user_id="u1", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=_source_envelope())

    assert result.result["status"] == "snapshot_only"
    assert result.result["reason"] == "no_slug_origin"
    assert builder.calls == []


@pytest.mark.asyncio
async def test_tool_already_linked() -> None:
    turn = _turn(_origin(), ToolInvocation(tool_name="qs_build_linked_surface", input={}))
    tool = MaterializeWidgetTool(bot=_bot(turn=turn), user_id="u1", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=_linked_envelope())

    assert result.result["status"] == "already_linked"
    assert result.result["refreshable"] is True
    assert result.result["a2ui_envelope"] == _linked_envelope()


@pytest.mark.asyncio
async def test_tool_pin_uses_publish_surface() -> None:
    builder = FakeTool(_success({"a2ui_envelope": _linked_envelope(), "artifacts": []}))
    publisher = FakeTool(_success({"surface_id": "surface-1", "kind": "widget", "refreshable": True}))
    tool = MaterializeWidgetTool(
        bot=_bot(builder=builder, publisher=publisher),
        user_id="u1",
        session_id="s1",
    )

    result = await tool.execute(turn_id="t1", envelope=_source_envelope(), pin=True)

    assert result.result["surface_id"] == "surface-1"
    assert result.result["pinned"] is True
    assert len(publisher.calls) == 1
    assert publisher.calls[0] == {
        "kind": "widget",
        "title": "worked hours by month",
        "envelope": _linked_envelope(),
        "_permission_context": None,
    }


@pytest.mark.asyncio
async def test_tool_pin_without_publish_tool() -> None:
    builder = FakeTool(_success({"a2ui_envelope": _linked_envelope(), "artifacts": []}))
    tool = MaterializeWidgetTool(bot=_bot(builder=builder), user_id="u1", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=_source_envelope(), pin=True)

    assert result.result["status"] == "materialized"
    assert result.result["pinned"] is False
    assert result.result["reason"] == "no_publish_surface"
    assert result.result["a2ui_envelope"] == _linked_envelope()


@pytest.mark.asyncio
async def test_tool_pin_failure_reported() -> None:
    builder = FakeTool(_success({"a2ui_envelope": _linked_envelope(), "artifacts": []}))
    publisher = FakeTool(_failure("surface store rejected the envelope"))
    tool = MaterializeWidgetTool(
        bot=_bot(builder=builder, publisher=publisher),
        user_id="u1",
        session_id="s1",
    )

    result = await tool.execute(turn_id="t1", envelope=_source_envelope(), pin=True)

    assert result.result["status"] == "materialized"
    assert result.result["pinned"] is False
    assert result.result["reason"] == "pin_failed"
    assert result.result["message"] == "surface store rejected the envelope"
    assert result.result["a2ui_envelope"] == _linked_envelope()


@pytest.mark.asyncio
async def test_tool_builder_failure_is_reported() -> None:
    builder = FakeTool(_failure("slug is forbidden"))
    tool = MaterializeWidgetTool(bot=_bot(builder=builder), user_id="u1", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=_source_envelope())

    assert result.result["status"] == "not_materializable"
    assert result.result["reason"] == "build_failed"
    assert result.result["message"] == "slug is forbidden"


@pytest.mark.asyncio
async def test_tool_identity_from_permission_context() -> None:
    pctx = build_principal_context("u1", channel="a2ui")
    builder = FakeTool(_success({"a2ui_envelope": _linked_envelope(), "artifacts": []}))
    bot = _bot(builder=builder)
    tool = MaterializeWidgetTool(bot=bot, user_id="u2", session_id="s1")

    result = await tool.execute(turn_id="t1", envelope=_source_envelope(), _permission_context=pctx)

    assert result.result["status"] == "materialized"
    assert bot.conversation_memory.calls == [("u1", "s1", "agent")]
    assert builder.calls[0]["_permission_context"] is pctx


@pytest.mark.asyncio
async def test_tool_keeps_caller_identity_across_interleaved_calls() -> None:
    """A concurrent call by another principal must not change the context forwarded to sibling tools."""
    import asyncio

    class SlowTool(FakeTool):
        async def execute(self, **kwargs: Any) -> ToolResult:
            await asyncio.sleep(0.05)
            return await super().execute(**kwargs)

    pctx_a = build_principal_context("u1", channel="a2ui")
    pctx_b = build_principal_context("u2", channel="a2ui")
    builder = SlowTool(_success({"a2ui_envelope": _linked_envelope(), "artifacts": []}))
    publisher = FakeTool(_success({"surface_id": "surface-1"}))
    tool = MaterializeWidgetTool(bot=_bot(builder=builder, publisher=publisher), session_id="s1")

    async def other_user() -> Any:
        await asyncio.sleep(0.01)
        return await tool.execute(turn_id="t1", envelope=_source_envelope(), _permission_context=pctx_b)

    result_a, result_b = await asyncio.gather(
        tool.execute(turn_id="t1", envelope=_source_envelope(), pin=True, _permission_context=pctx_a),
        other_user(),
    )

    assert result_a.result["status"] == "materialized"
    assert result_b.result["reason"] == "turn_not_found"
    assert builder.calls[0]["_permission_context"] is pctx_a
    assert publisher.calls[0]["_permission_context"] is pctx_a


def test_tool_is_renderer_callable() -> None:
    manager = ToolManager()
    manager.register_tool(MaterializeWidgetTool())

    functions = ToolManagerExecutor(manager).list_functions()

    assert "materialize_widget" in {function.name for function in functions}
