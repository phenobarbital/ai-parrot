"""Tests for MatrixCrewAgentWrapper.handle_task — FEAT-463 TASK-2482."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.matrix.crew.config import MatrixCrewAgentEntry
from parrot.integrations.matrix.crew.crew_wrapper import MatrixCrewAgentWrapper
from parrot.integrations.matrix.events import ParrotEventType, TaskEventContent

pytestmark = pytest.mark.asyncio


@pytest.fixture
def wrapper():
    svc = AsyncMock()
    reg = AsyncMock()
    w = MatrixCrewAgentWrapper(
        "writer",
        MatrixCrewAgentEntry(chatbot_id="writer", display_name="W", mxid_localpart="parrot-writer"),
        svc,
        reg,
        MagicMock(),
        "parrot.local",
        streaming=False,
    )
    return w, svc, reg


def _task(**kw):
    return TaskEventContent(
        task_id="t1",
        content="Summarise Q2",
        target_agent="writer",
        correlation_id="c1",
        hops=1,
        **kw,
    )


async def test_emits_result_with_correlation(wrapper):
    w, svc, reg = wrapper
    bot = MagicMock()
    bot.ask = AsyncMock(return_value='{"answer": "ok", "confidence": 0.7, "sources": []}')
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(_task(), "!tun:s")
    args = svc.send_custom_event_as_agent.call_args.args
    assert args[0] == "writer"
    assert args[2] == ParrotEventType.RESULT
    assert args[3]["success"] is True
    assert args[3]["metadata"]["correlation_id"] == "c1"
    assert reg.update_status.await_args_list[-1].args[1] == "ready"


async def test_schema_in_prompt(wrapper):
    w, svc, _ = wrapper
    bot = MagicMock()
    bot.ask = AsyncMock(return_value="{}")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(_task(expected_schema={"type": "object", "required": ["total"]}), "!tun:s")
    assert '"required"' in bot.ask.call_args.args[0]


async def test_bot_error_yields_failed_result(wrapper):
    w, svc, _ = wrapper
    bot = MagicMock()
    bot.ask = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(_task(), "!tun:s")
    assert svc.send_custom_event_as_agent.call_args.args[3]["success"] is False


async def test_correlation_falls_back_to_task_id(wrapper):
    w, svc, _ = wrapper
    bot = MagicMock()
    bot.ask = AsyncMock(return_value="x")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(TaskEventContent(task_id="legacy", content="q", target_agent="writer"), "!r:s")
    assert svc.send_custom_event_as_agent.call_args.args[3]["metadata"]["correlation_id"] == "legacy"


async def test_handles_aimessage_response(wrapper):
    """AbstractBot.ask() returns an AIMessage, not a plain str — handle_task
    must extract .to_text the same way session.py's _call_agent_with_timeout
    does, not pass the object itself as ResultEventContent.content."""
    w, svc, _ = wrapper
    ai_message = MagicMock()
    ai_message.to_text = '{"answer": "ok", "confidence": 0.9, "sources": []}'
    bot = MagicMock()
    bot.ask = AsyncMock(return_value=ai_message)
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(_task(), "!tun:s")
    result = svc.send_custom_event_as_agent.call_args.args[3]
    assert result["success"] is True
    assert result["content"] == ai_message.to_text
