"""Unit tests for the adaptiveCard/action invoke shim (FEAT-303, TASK-1754).

Reuses the ``FakeTurnContext`` / ``_make_agent`` test-double patterns from
``test_msagent_cards.py``, extended with an invoke-shaped activity. Uses
``monkeypatch.setitem`` (not ``patch.dict(sys.modules, ...)``) to stub
``parrot.utils.helpers`` / ``parrot.utils.types`` — see
``test_msagent_semantic_bridge.py`` for the rationale.
"""
from __future__ import annotations

from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msagentsdk.agent import ParrotM365Agent


def _make_parrot_utils_stub() -> ModuleType:
    stub = ModuleType("parrot.utils.helpers")
    stub.RequestContext = MagicMock(return_value=MagicMock())
    return stub


def _make_parrot_utils_types_stub() -> ModuleType:
    stub = ModuleType("parrot.utils.types")
    stub.SafeDict = dict
    return stub


def _stub_parrot_utils(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "parrot.utils.types", _make_parrot_utils_types_stub())
    monkeypatch.setitem(sys.modules, "parrot.utils.helpers", _make_parrot_utils_stub())


class FakeInvokeTurnContext:
    """Minimal TurnContext double for an ``invoke`` activity."""

    def __init__(self, name: str, value: Any, user_id: str = "user-123") -> None:
        self.activity = MagicMock()
        self.activity.type = "invoke"
        self.activity.name = name
        self.activity.value = value
        self.activity.text = None
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


def _make_agent() -> ParrotM365Agent:
    parrot_agent = MagicMock()
    parrot_agent.ask = AsyncMock()
    return ParrotM365Agent(parrot_agent=parrot_agent)


class TestAdaptiveCardActionShim:
    @pytest.mark.asyncio
    async def test_invoke_acked_and_prompt_routed(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        response = MagicMock()
        response.structured_output = None
        response.data = None
        response.content = "ok"
        agent.parrot_agent.ask.return_value = response

        ctx = FakeInvokeTurnContext(
            name="adaptiveCard/action",
            value={
                "action": {
                    "data": {
                        "feat303_prompt": "Show details for order 42",
                        "msteams": {"type": "messageBack", "text": "fallback text"},
                    }
                }
            },
        )

        with monkeypatch.context() as m:
            called = {}

            async def _fake_send_invoke_response(context, status_code=200):
                called["status_code"] = status_code

            m.setattr(agent, "_send_invoke_response", _fake_send_invoke_response)
            await agent.on_turn(ctx)

        assert called["status_code"] == 200
        agent.parrot_agent.ask.assert_awaited_once()
        _, kwargs = agent.parrot_agent.ask.call_args
        assert kwargs["question"] == "Show details for order 42"

    @pytest.mark.asyncio
    async def test_msteams_text_fallback_used(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        response = MagicMock()
        response.structured_output = None
        response.data = None
        response.content = "ok"
        agent.parrot_agent.ask.return_value = response

        ctx = FakeInvokeTurnContext(
            name="adaptiveCard/action",
            value={
                "action": {
                    "data": {
                        "msteams": {"type": "messageBack", "text": "Open item 7"},
                    }
                }
            },
        )

        async def _fake_send_invoke_response(context, status_code=200):
            pass

        monkeypatch.setattr(agent, "_send_invoke_response", _fake_send_invoke_response)
        await agent.on_turn(ctx)

        agent.parrot_agent.ask.assert_awaited_once()
        _, kwargs = agent.parrot_agent.ask.call_args
        assert kwargs["question"] == "Open item 7"

    @pytest.mark.asyncio
    async def test_missing_prompt_warns_and_returns(self, monkeypatch):
        agent = _make_agent()

        ctx = FakeInvokeTurnContext(
            name="adaptiveCard/action",
            value={"action": {"data": {}}},
        )

        async def _fake_send_invoke_response(context, status_code=200):
            pass

        monkeypatch.setattr(agent, "_send_invoke_response", _fake_send_invoke_response)
        await agent.on_turn(ctx)

        agent.parrot_agent.ask.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_invoke_still_ignored(self, monkeypatch):
        agent = _make_agent()

        ctx = FakeInvokeTurnContext(name="config/fetch", value={})

        await agent.on_turn(ctx)

        agent.parrot_agent.ask.assert_not_awaited()
        assert ctx.sent == []
