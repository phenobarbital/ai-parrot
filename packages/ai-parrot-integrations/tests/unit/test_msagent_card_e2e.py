"""End-to-end integration tests for the Semantic UI Model card turn (FEAT-303,
TASK-1755).

Drives ``ParrotM365Agent.on_turn()`` (not the private helpers directly) with
fake ``TurnContext`` doubles to exercise the full round-trip: an initial
message produces a card, and a simulated click (either a ``messageBack``
message activity or an ``adaptiveCard/action`` invoke) re-enters the agent
and triggers a second ``ask()`` call with the filled prompt.

Uses ``monkeypatch.setitem`` (not ``patch.dict(sys.modules, ...)``) to stub
``parrot.utils.helpers`` / ``parrot.utils.types`` — see
``test_msagent_semantic_bridge.py`` for the rationale (``patch.dict`` would
evict real heavy imports like ``numpy`` performed inside the ``with`` block).
"""
from __future__ import annotations

from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msagentsdk.agent import ParrotM365Agent
from parrot.integrations.msagentsdk.semantic import (
    SemanticUIResult,
    TablePayload,
    UIAction,
)


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


class FakeTurnContext:
    """Minimal TurnContext double supporting both message and invoke turns."""

    def __init__(
        self,
        *,
        activity_type: str = "message",
        text: str | None = "hello",
        name: str | None = None,
        value: Any = None,
        user_id: str = "user-123",
    ) -> None:
        self.activity = MagicMock()
        self.activity.type = activity_type
        self.activity.text = text
        self.activity.name = name
        self.activity.value = value
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


def _table_result_with_actions() -> SemanticUIResult:
    return SemanticUIResult(
        title="Orders",
        payload=TablePayload(
            result_type="table",
            columns=["id", "total"],
            rows=[["1", "$10"], ["2", "$20"]],
        ),
        actions=[
            UIAction(
                title="Details",
                prompt_template="Show details for order {id}",
                params={"id": "1"},
            ),
            UIAction(title="Open dashboard", url="https://example.com/dashboard"),
        ],
    )


def _response_for(result) -> MagicMock:
    response = MagicMock()
    response.structured_output = result
    response.data = None
    response.content = str(result)
    return response


class TestCardTurnEndToEnd:
    @pytest.mark.asyncio
    async def test_card_turn_then_messageback_click(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        result = _table_result_with_actions()
        agent.parrot_agent.ask.return_value = _response_for(result)

        ctx = FakeTurnContext(activity_type="message", text="show my orders")
        await agent.on_turn(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        card = activity.attachments[0].content
        assert card["type"] == "AdaptiveCard"

        submit_action = next(
            a for a in card["actions"] if a["type"] == "Action.Submit"
        )
        openurl_action = next(
            a for a in card["actions"] if a["type"] == "Action.OpenUrl"
        )
        assert openurl_action["url"] == "https://example.com/dashboard"
        prompt = submit_action["data"]["msteams"]["text"]
        assert prompt == "Show details for order 1"

        # Simulate the click: a fresh messageBack message activity.
        agent.parrot_agent.ask.reset_mock()
        agent.parrot_agent.ask.return_value = _response_for(None)
        click_ctx = FakeTurnContext(activity_type="message", text=prompt)
        await agent.on_turn(click_ctx)

        agent.parrot_agent.ask.assert_awaited_once()
        _, kwargs = agent.parrot_agent.ask.call_args
        assert kwargs["question"] == prompt

    @pytest.mark.asyncio
    async def test_card_turn_then_invoke_click(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        result = _table_result_with_actions()
        agent.parrot_agent.ask.return_value = _response_for(result)

        ctx = FakeTurnContext(activity_type="message", text="show my orders")
        await agent.on_turn(ctx)

        card = ctx.sent[0].attachments[0].content
        submit_action = next(
            a for a in card["actions"] if a["type"] == "Action.Submit"
        )
        action_data = submit_action["data"]

        # Simulate the click via an adaptiveCard/action invoke instead.
        agent.parrot_agent.ask.reset_mock()
        agent.parrot_agent.ask.return_value = _response_for(None)

        invoke_ctx = FakeTurnContext(
            activity_type="invoke",
            text=None,
            name="adaptiveCard/action",
            value={"action": {"data": action_data}},
        )

        async def _fake_send_invoke_response(context, status_code=200):
            invoke_ctx.sent.append({"invokeResponse": status_code})

        monkeypatch.setattr(
            agent, "_send_invoke_response", _fake_send_invoke_response
        )
        await agent.on_turn(invoke_ctx)

        assert {"invokeResponse": 200} in invoke_ctx.sent
        agent.parrot_agent.ask.assert_awaited_once()
        _, kwargs = agent.parrot_agent.ask.call_args
        assert kwargs["question"] == action_data["feat303_prompt"]

    @pytest.mark.asyncio
    async def test_plain_bot_unaffected(self, monkeypatch):
        _stub_parrot_utils(monkeypatch)
        agent = _make_agent()
        agent._cards_enabled = False
        agent.parrot_agent.ask.return_value = _response_for(None)

        ctx = FakeTurnContext(activity_type="message", text="hello there")
        await agent.on_turn(ctx)

        assert len(ctx.sent) == 1
        activity = ctx.sent[0]
        assert not getattr(activity, "attachments", None)
