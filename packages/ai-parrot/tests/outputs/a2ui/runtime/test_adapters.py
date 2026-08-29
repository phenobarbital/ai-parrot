"""Unit tests for `ToolManagerExecutor`/`ConversationMemorySurfaceStore` (TASK-2570)."""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.outputs.a2ui.runtime.adapters import (
    ConversationMemorySurfaceStore,
    ToolManagerExecutor,
)
from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext,
    FunctionCallRecord,
    SurfaceState,
)


def _fake_tool_manager(*, execute_tool_return=None, get_tool_return=None, schemas=None):
    """A `ToolManager` double: `execute_tool` is async, everything else is sync.

    `unittest.mock.AsyncMock()` makes EVERY child attribute an `AsyncMock` too
    (including sync methods like `get_tool`/`get_tool_schemas`), so a bare
    `AsyncMock()` silently turns those into coroutines. Only `execute_tool`
    is actually async on the real `ToolManager`.
    """
    tm = MagicMock()
    tm.execute_tool = AsyncMock(return_value=execute_tool_return)
    tm.get_tool = MagicMock(return_value=get_tool_return)
    tm.get_tool_schemas = MagicMock(return_value=schemas or [])
    return tm


@pytest.fixture
def a2ui_call_ctx():
    return A2UICallContext(
        agent_id="agent-1",
        user_id="u-1",
        session_id="s-1",
        transport="http",
        permission_context=object(),
    )


@pytest.fixture
def file_memory():
    from parrot.memory.file import FileConversationMemory

    tmp_dir = tempfile.mkdtemp(prefix="a2ui-surface-store-")
    yield FileConversationMemory(base_path=tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def memory_store(file_memory):
    return ConversationMemorySurfaceStore(file_memory, user_id="u-1")


class TestToolManagerExecutor:
    async def test_passes_permission_context(self, a2ui_call_ctx):
        tm = _fake_tool_manager()
        await ToolManagerExecutor(tm).call("get_weather", {"location": "Caracas"}, a2ui_call_ctx)
        _, kwargs = tm.execute_tool.call_args
        assert kwargs["permission_context"] is a2ui_call_ctx.permission_context

    async def test_normalizes_raw_return_to_tool_result(self, a2ui_call_ctx):
        tm = _fake_tool_manager(execute_tool_return="plain string")
        res = await ToolManagerExecutor(tm).call("t", {}, a2ui_call_ctx)
        assert res.success is True and res.result == "plain string"

    async def test_not_found_tool_result_passes_through(self, a2ui_call_ctx):
        """execute_tool RETURNS not_found, it does not raise."""
        from parrot.tools.abstract import ToolResult

        tm = _fake_tool_manager(
            execute_tool_return=ToolResult(success=False, status="not_found", result=None, error="missing")
        )
        res = await ToolManagerExecutor(tm).call("nope", {}, a2ui_call_ctx)
        assert res.status == "not_found"
        assert res.success is False

    async def test_tool_result_passthrough_unchanged(self, a2ui_call_ctx):
        from parrot.tools.abstract import ToolResult

        expected = ToolResult(success=True, status="success", result={"ok": 1})
        tm = _fake_tool_manager(execute_tool_return=expected)
        res = await ToolManagerExecutor(tm).call("t", {}, a2ui_call_ctx)
        assert res is expected

    async def test_tool_definition_path_logs_no_gap_warning(self, a2ui_call_ctx, caplog):
        """FEAT-474 closure: ToolManager.execute_tool() now enforces
        permission_context uniformly for the ToolDefinition (@tool) path, so
        the adapter no longer needs (or emits) a known-gap WARNING for it."""
        from parrot.tools.manager import ToolDefinition

        tm = _fake_tool_manager(
            execute_tool_return="raw",
            get_tool_return=ToolDefinition(name="legacy_tool", description="d", input_schema={}, function=lambda: None),
        )
        with caplog.at_level("WARNING"):
            await ToolManagerExecutor(tm).call("legacy_tool", {}, a2ui_call_ctx)
        assert not any(
            "does not enforce permission_context" in rec.message or "known G7 gap" in rec.message
            for rec in caplog.records
        )

    def test_list_functions_derives_from_tool_schemas(self):
        from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID

        tm = _fake_tool_manager(
            schemas=[
                {
                    "name": "get_weather",
                    "description": "d",
                    "parameters": {"type": "object", "properties": {}},
                    "_tool_instance": object(),
                }
            ]
        )
        functions = ToolManagerExecutor(tm).list_functions()
        assert len(functions) == 1
        assert functions[0].name == "get_weather"
        assert functions[0].catalog_id == DEFAULT_CATALOG_ID
        assert functions[0].allowed_callers == "rendererOrAgent"
        assert functions[0].requires_user_activation is False

    def test_list_functions_excludes_a2ui_hidden_tools(self):
        class _HiddenTool:
            a2ui_hidden = True

        tm = _fake_tool_manager(schemas=[{"name": "secret_tool", "parameters": {}, "_tool_instance": _HiddenTool()}])
        assert ToolManagerExecutor(tm).list_functions() == []


class TestConversationMemorySurfaceStore:
    async def test_surface_roundtrip(self, memory_store):
        st = SurfaceState(surface_id="s-1", catalog_id="c", data_model={"a": 1}, updated_at=datetime.now(UTC))
        await memory_store.put("sess-1", st)
        fetched = await memory_store.get("sess-1", "s-1")
        assert fetched is not None
        assert fetched.data_model == {"a": 1}

    async def test_get_missing_surface_returns_none(self, memory_store):
        assert await memory_store.get("sess-1", "unknown") is None

    async def test_pending_call_ttl_expiry(self, memory_store):
        """A record past created_at + ttl_seconds must not resolve."""
        expired = FunctionCallRecord(
            function_call_id="fc-expired",
            call="refreshChart",
            created_at=datetime.now(UTC) - timedelta(seconds=1000),
            ttl_seconds=900,
        )
        await memory_store.add("sess-1", expired)
        resolved = await memory_store.resolve("sess-1", "fc-expired", None, None)
        assert resolved is None

    async def test_live_pending_call_resolves(self, memory_store):
        record = FunctionCallRecord(
            function_call_id="fc-live",
            call="refreshChart",
            created_at=datetime.now(UTC),
            ttl_seconds=900,
        )
        await memory_store.add("sess-1", record)
        resolved = await memory_store.resolve("sess-1", "fc-live", {"done": True}, None)
        assert resolved is not None
        assert resolved.function_call_id == "fc-live"

        # Resolved once -> gone.
        assert await memory_store.resolve("sess-1", "fc-live", {}, None) is None

    async def test_unknown_function_call_id_resolves_to_none(self, memory_store):
        assert await memory_store.resolve("sess-1", "does-not-exist", None, None) is None

    async def test_delete_surface_keeps_pending_calls(self, memory_store):
        st = SurfaceState(surface_id="s-1", catalog_id="c", data_model={}, updated_at=datetime.now(UTC))
        await memory_store.put("sess-1", st)
        record = FunctionCallRecord(function_call_id="fc-1", call="refreshChart", created_at=datetime.now(UTC))
        await memory_store.add("sess-1", record)

        await memory_store.delete("sess-1", "s-1")

        assert await memory_store.get("sess-1", "s-1") is None
        resolved = await memory_store.resolve("sess-1", "fc-1", {}, None)
        assert resolved is not None
