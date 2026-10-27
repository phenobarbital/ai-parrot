"""FEAT-757 integration: materialize a slug-backed turn into a linked widget."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from parrot.memory import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import ToolInvocation
from parrot.outputs.a2ui.linked import has_data_sources
from parrot.tools.manager import ToolManager
from parrot_tools.materialize_widget import MaterializeWidgetTool
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.ui_surfaces import PublishSurfaceTool

SLUG = "epson_field_activity"
FORBIDDEN_SLUG = "payroll_confidential"


@pytest.fixture
def fake_core_qs(patched_qs, monkeypatch):
    """Patch the executor's QuerySource seam with deterministic frames."""
    state: dict[str, list[dict[str, object]]] = {"qs": [], "mq": []}
    frame = pd.DataFrame(
        {
            "day": pd.date_range("2026-01-01", periods=12, freq="D"),
            "visits": list(range(12)),
            "program": ["epson"] * 12,
        }
    )

    class FakeQS:
        def __init__(self, **kwargs):
            state["qs"].append(kwargs)

        async def query(self, output_format=None):
            return frame, None

        async def close(self):
            return None

    class FakeMultiQS:
        def __init__(self, **kwargs):
            state["mq"].append(kwargs)

        async def query(self):
            return {"result": frame}, {}

        async def close(self):
            return None

    monkeypatch.setattr("parrot.tools.dataset_manager.sources.query_slug._get_qs", lambda: FakeQS)
    monkeypatch.setattr("parrot.tools.dataset_manager.sources.query_slug._get_multiqs", lambda: FakeMultiQS)
    return state


class _Memory:
    """ConversationMemory double: one history for ("u1", "s1")."""

    def __init__(self, history: ConversationHistory) -> None:
        self._history = history

    async def get_history(self, user_id, session_id, chatbot_id=None):
        if (user_id, session_id) == (self._history.user_id, self._history.session_id):
            return self._history
        return None


async def test_materialize_then_refresh_roundtrip(fake_core_qs):
    """A slug-backed turn materializes through the real toolkit and pins as a linked widget."""
    store = MagicMock()
    store.save = AsyncMock(return_value="surface-1")
    service = MagicMock()
    service.validate_for_persistence = AsyncMock()
    service.ensure_snapshot = AsyncMock(side_effect=lambda envelope, **kwargs: envelope)

    tool_manager = ToolManager()
    tool_manager.register_toolkit(QuerysourceToolkit(dsn="postgres://fake"))
    tool_manager.register_tool(
        PublishSurfaceTool(surface_store=store, linked_service=service, user_id="u1", agent_id="agent")
    )
    turn = ConversationTurn(
        turn_id="t1",
        user_id="u1",
        user_message="visits by day",
        assistant_response="…",
        tool_invocations=[ToolInvocation(tool_name="qs_execute_slug", input={"slug": SLUG, "limit": 100})],
    )
    history = ConversationHistory(session_id="s1", user_id="u1", turns=[turn])
    bot = SimpleNamespace(conversation_memory=_Memory(history), memory_key_id="agent", tool_manager=tool_manager)
    tool = MaterializeWidgetTool(bot=bot, user_id="u1")
    tool_manager.register_tool(tool)

    on_screen = {
        "surfaceId": "structured_chart-1",
        "components": [
            {
                "id": "root",
                "component": "Chart",
                "type": "bar",
                "x": "day",
                "y": ["visits"],
                "data": {"path": "/rows"},
            }
        ],
        "dataModel": {"rows": [{"day": "2026-01-01", "visits": 1}]},
    }
    result = await tool.execute(turn_id="t1", session_id="s1", envelope=on_screen, pin=True)
    payload = result.result

    assert payload["status"] == "materialized"
    assert payload["pinned"] is True
    assert payload["surface_id"] == "surface-1"
    assert payload["refreshable"] is True
    assert has_data_sources(payload["a2ui_envelope"])
    service.validate_for_persistence.assert_awaited_once()
    store.save.assert_awaited_once()
    record = store.save.call_args.args[0]
    source = record.envelope["metadata"]["extensions"]["parrot_data_sources"][SLUG]
    assert source["target"] == f"/{SLUG}/rows"


async def test_materialize_forbidden_slug_build_failed_no_save(fake_core_qs, monkeypatch):
    """AC6: a slug that fails during build_linked_surface returns build_failed and store.save is never called."""
    store = MagicMock()
    store.save = AsyncMock(return_value="surface-1")
    service = MagicMock()
    service.validate_for_persistence = AsyncMock()
    service.ensure_snapshot = AsyncMock(side_effect=lambda envelope, **kwargs: envelope)

    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    original_describe = toolkit.describe_slug

    async def _fail_on_forbidden(slug, **kwargs):
        if slug == FORBIDDEN_SLUG:
            raise RuntimeError(f"slug '{slug}' is not allowed")
        return await original_describe(slug, **kwargs)

    monkeypatch.setattr(toolkit, "describe_slug", _fail_on_forbidden)

    tool_manager = ToolManager()
    tool_manager.register_toolkit(toolkit)
    tool_manager.register_tool(
        PublishSurfaceTool(surface_store=store, linked_service=service, user_id="u1", agent_id="agent")
    )
    turn = ConversationTurn(
        turn_id="t1",
        user_id="u1",
        user_message="payroll data",
        assistant_response="…",
        tool_invocations=[
            ToolInvocation(tool_name="qs_execute_slug", input={"slug": FORBIDDEN_SLUG, "limit": 100})
        ],
    )
    history = ConversationHistory(session_id="s1", user_id="u1", turns=[turn])
    bot = SimpleNamespace(conversation_memory=_Memory(history), memory_key_id="agent", tool_manager=tool_manager)
    tool = MaterializeWidgetTool(bot=bot, user_id="u1")
    tool_manager.register_tool(tool)

    on_screen = {
        "surfaceId": "structured_chart-1",
        "components": [
            {"id": "root", "component": "Chart", "type": "bar", "x": "day", "y": ["visits"], "data": {"path": "/rows"}}
        ],
        "dataModel": {"rows": [{"day": "2026-01-01", "visits": 1}]},
    }
    result = await tool.execute(turn_id="t1", session_id="s1", envelope=on_screen, pin=True)
    payload = result.result

    assert payload["status"] == "not_materializable"
    assert payload["reason"] == "build_failed"
    store.save.assert_not_awaited()
