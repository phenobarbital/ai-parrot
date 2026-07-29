"""Unit tests for the Semantic UI Model bridge seam (FEAT-303, TASK-1753).

Reuses the ``FakeTurnContext`` / ``_make_agent`` test-double patterns from
``test_msagent_cards.py``. Uses ``monkeypatch.setitem`` (not
``patch.dict(sys.modules, ...)``) to stub ``parrot.utils.helpers`` /
``parrot.utils.types`` — ``patch.dict`` snapshots and restores the *entire*
``sys.modules`` dict on exit, which would evict heavy real imports (e.g.
``numpy``, pulled in transitively by ``parrot.auth.permission``) performed
during the ``with`` block, breaking subsequent tests with "cannot load
module more than once per process". ``monkeypatch.setitem`` only touches
the specific keys it sets.
"""
from __future__ import annotations

from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msagentsdk.agent import ParrotM365Agent
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
from parrot.integrations.msagentsdk.semantic import (
    SemanticUIResult,
    StatusPayload,
)


def _make_parrot_utils_stub() -> ModuleType:
    """Return a minimal stub for parrot.utils.helpers that avoids Cython."""
    stub = ModuleType("parrot.utils.helpers")
    stub.RequestContext = MagicMock(return_value=MagicMock())
    return stub


def _make_parrot_utils_types_stub() -> ModuleType:
    stub = ModuleType("parrot.utils.types")
    stub.SafeDict = dict
    return stub


def _stub_parrot_utils(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub parrot.utils.{helpers,types} in sys.modules for this test only."""
    import sys

    monkeypatch.setitem(sys.modules, "parrot.utils.types", _make_parrot_utils_types_stub())
    monkeypatch.setitem(sys.modules, "parrot.utils.helpers", _make_parrot_utils_stub())


class FakeTurnContext:
    """Minimal TurnContext double — captures send_activity calls."""

    def __init__(self, text: str = "hello", user_id: str = "user-123") -> None:
        self.activity = MagicMock()
        self.activity.text = text
        self.activity.conversation = MagicMock()
        self.activity.conversation.id = "session-001"
        from_prop = MagicMock()
        from_prop.aad_object_id = user_id
        from_prop.aadObjectId = None
        from_prop.id = user_id
        from_prop.email = None
        from_prop.name = "Test User"
        self.activity.from_property = from_prop

        self._sent: list[Any] = []

    async def send_activity(self, activity: Any) -> None:
        self._sent.append(activity)

    @property
    def sent(self) -> list[Any]:
        return self._sent


def _make_agent(**kwargs) -> ParrotM365Agent:
    """Build a ParrotM365Agent with a fake parrot_agent."""
    parrot_agent = MagicMock()
    parrot_agent.ask = AsyncMock()
    return ParrotM365Agent(parrot_agent=parrot_agent, **kwargs)


def _semantic_result() -> SemanticUIResult:
    return SemanticUIResult(
        title="Status",
        payload=StatusPayload(result_type="status", level="success", message="ok"),
    )


class TestCardSeam:
    @pytest.mark.asyncio
    async def test_handle_message_sends_card(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        result = _semantic_result()
        response = MagicMock()
        response.structured_output = result
        response.data = None
        response.content = "fallback content"
        agent.parrot_agent.ask.return_value = response

        ctx = FakeTurnContext(text="show status")
        await agent._handle_message(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        assert activity.attachments[0].content_type == (
            "application/vnd.microsoft.card.adaptive"
        )
        assert not getattr(activity, "text", None)

    @pytest.mark.asyncio
    async def test_handle_message_data_fallback_carrier(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        result = _semantic_result()
        response = MagicMock()
        response.structured_output = None
        response.data = result
        response.content = "fallback content"
        agent.parrot_agent.ask.return_value = response

        ctx = FakeTurnContext(text="show status")
        await agent._handle_message(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        assert activity.attachments[0].content_type == (
            "application/vnd.microsoft.card.adaptive"
        )

    @pytest.mark.asyncio
    async def test_handle_message_plain_text_wrapped_in_card(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        response = MagicMock()
        response.structured_output = None
        response.data = None
        response.output = None
        response.content = "hello world"
        agent.parrot_agent.ask.return_value = response

        ctx = FakeTurnContext(text="hi")
        await agent._handle_message(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        assert not getattr(activity, "text", None)
        assert activity.attachments
        att = activity.attachments[0]
        ct = att.content_type if hasattr(att, "content_type") else att["contentType"]
        assert ct == "application/vnd.microsoft.card.adaptive"
        content = att.content if hasattr(att, "content") else att["content"]
        assert content["body"][0]["type"] == "TextBlock"
        assert content["body"][0]["text"] == "hello world"

    @pytest.mark.asyncio
    async def test_handle_message_table_data_in_card(self, monkeypatch):
        """When response carries tabular data, the card includes a table."""
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        response = MagicMock()
        response.structured_output = None
        response.data = [
            {"warehouse": "WH-A", "city": "Boston"},
            {"warehouse": "WH-B", "city": "Miami"},
        ]
        response.output = "explanation text"
        response.content = "explanation text"
        response.response = None
        agent.parrot_agent.ask.return_value = response

        ctx = FakeTurnContext(text="list warehouses")
        await agent._handle_message(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        att = activity.attachments[0]
        content = att.content if hasattr(att, "content") else att["content"]
        body = content["body"]
        # First element: explanation TextBlock
        assert body[0]["type"] == "TextBlock"
        assert body[0]["text"] == "explanation text"
        # Second element: AC 1.4 ColumnSet header row
        assert body[1]["type"] == "ColumnSet"
        header_cols = body[1]["columns"]
        header_texts = [col["items"][0]["text"] for col in header_cols]
        assert header_texts == ["warehouse", "city"]
        # Header + 2 data ColumnSets
        column_sets = [b for b in body if b.get("type") == "ColumnSet"]
        assert len(column_sets) >= 3

    @pytest.mark.asyncio
    async def test_handle_message_plain_text_no_card_when_disabled(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent(enable_semantic_cards=False)
        response = MagicMock()
        response.structured_output = None
        response.data = None
        response.content = "hello world"
        agent.parrot_agent.ask.return_value = response

        ctx = FakeTurnContext(text="hi")
        await agent._handle_message(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        assert activity.text == "hello world"
        assert not getattr(activity, "attachments", None)

    @pytest.mark.asyncio
    async def test_render_error_falls_back_to_text(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        result = _semantic_result()
        response = MagicMock()
        response.structured_output = result
        response.data = None
        response.content = "raw content"
        agent.parrot_agent.ask.return_value = response

        def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        import parrot.integrations.msagentsdk.agent as agent_mod

        monkeypatch.setattr(agent_mod.cards, "render_card", _raise)

        ctx = FakeTurnContext(text="show status")
        await agent._handle_message(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        # Falls back to _send_text(render_text(result)) — plain text, no attachments.
        assert not getattr(activity, "attachments", None)

    @pytest.mark.asyncio
    async def test_semantic_cards_disabled(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent(enable_semantic_cards=False)
        result = _semantic_result()
        response = MagicMock()
        response.structured_output = result
        response.data = None
        response.content = "plain fallback"
        agent.parrot_agent.ask.return_value = response

        ctx = FakeTurnContext(text="show status")
        await agent._handle_message(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        assert activity.text == "plain fallback"
        assert not getattr(activity, "attachments", None)


class TestConfig:
    def test_new_config_fields_defaults(self):
        cfg = MSAgentSDKConfig(name="x", chatbot_id="y")
        assert cfg.enable_semantic_cards is True
        assert cfg.max_table_rows == 50
        assert cfg.max_card_bytes == 25_000


def test_lazy_exports():
    import parrot.integrations.msagentsdk as m

    for name in (
        "SemanticUIResult",
        "UIAction",
        "UIField",
        "UIMetric",
        "TablePayload",
        "MetricsPayload",
        "DetailPayload",
        "StatusPayload",
        "render_card",
        "render_text",
        "build_card_attachment",
        "CardRenderError",
    ):
        assert name in m.__all__
        assert getattr(m, name) is not None
