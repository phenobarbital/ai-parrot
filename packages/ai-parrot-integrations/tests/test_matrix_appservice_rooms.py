"""Tests for MatrixAppService room primitives — FEAT-463 TASK-2479."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.matrix.appservice import MatrixAppService
from parrot.integrations.matrix.events import ParrotEventType
from parrot.integrations.matrix.models import MatrixAppServiceConfig

pytestmark = pytest.mark.asyncio


@pytest.fixture
def svc():
    s = MatrixAppService(MatrixAppServiceConfig(as_token="a", hs_token="h"))
    s._appservice = MagicMock()
    s._appservice.intent = AsyncMock()
    s._appservice.intent.create_room.return_value = "!new:parrot.local"
    s._appservice.intent.send_state_event.return_value = "$state"
    s._registered_agents = {"analyst": "@parrot-analyst:parrot.local"}
    return s


async def test_create_room_as_bot_forwards_args(svc):
    rid = await svc.create_room_as_bot(
        name="general",
        alias_localpart="general",
        preset="public_chat",
        visibility="public",
        invitees=["@x:parrot.local"],
    )
    assert rid == "!new:parrot.local"
    kw = svc._appservice.intent.create_room.call_args.kwargs
    assert kw["alias_localpart"] == "general"
    assert str(kw["preset"].value) == "public_chat"
    assert kw["invitees"] == ["@x:parrot.local"]


async def test_set_room_state_as_bot(svc):
    assert (
        await svc.set_room_state_as_bot("!r:s", ParrotEventType.CHANNEL, {"name": "g"})
        == "$state"
    )


async def test_leave_as_agent(svc):
    intent = AsyncMock()
    svc._appservice.intent.user = MagicMock(return_value=intent)
    await svc.leave_as_agent("analyst", "!r:s")
    intent.leave_room.assert_awaited_once()


def _evt(etype, sender="@parrot-analyst:parrot.local", room="!t:s", content=None):
    e = MagicMock()
    e.type = etype
    e.sender = sender
    e.room_id = room
    e.content = content or {"task_id": "1"}
    return e


async def test_feedback_routed_with_room_and_sender(svc):
    cb = AsyncMock()
    svc.set_custom_event_callback(cb)
    await svc._handle_event(_evt(ParrotEventType.FEEDBACK))
    cb.assert_awaited_once_with(
        ParrotEventType.FEEDBACK, {"task_id": "1"}, "!t:s", "@parrot-analyst:parrot.local"
    )


async def test_legacy_two_arg_callback_adapted(svc):
    seen = []

    async def legacy(event_type, content):
        seen.append((event_type, content))

    svc.set_custom_event_callback(legacy)
    await svc._handle_event(_evt(ParrotEventType.TASK))
    assert seen == [(ParrotEventType.TASK, {"task_id": "1"})]
