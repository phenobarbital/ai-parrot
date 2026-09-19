"""Tests for ChannelManager — FEAT-463 TASK-2480."""

from unittest.mock import AsyncMock

import pytest

from parrot.integrations.matrix.crew.channels import ChannelManager
from parrot.integrations.matrix.crew.config import (
    ChannelConfig,
    CollaborativeConfig,
    MatrixCrewAgentEntry,
    MatrixCrewConfig,
    SpaceConfig,
)
from parrot.integrations.matrix.events import ParrotEventType

pytestmark = pytest.mark.asyncio


def _cfg(**over):
    agents = {
        n: MatrixCrewAgentEntry(chatbot_id=n, display_name=n, mxid_localpart=f"parrot-{n}")
        for n in ("analyst", "writer")
    }
    base = dict(
        homeserver_url="http://hs",
        server_name="parrot.local",
        as_token="a",
        hs_token="h",
        bot_mxid="@parrot:parrot.local",
        general_room_id="!gen:parrot.local",
        agents=agents,
        collaborative=CollaborativeConfig(),
        channels=[
            ChannelConfig(name="general", agents=["analyst", "writer"], answer_policy="swarm"),
            ChannelConfig(
                name="finance",
                visibility="private",
                agents=["analyst"],
                room_id="!fin:parrot.local",
            ),
        ],
    )
    base.update(over)
    return MatrixCrewConfig(**base)


@pytest.fixture
def svc():
    s = AsyncMock()
    s.resolve_alias.return_value = None
    s.create_room_as_bot.return_value = "!gen-new:parrot.local"
    s.get_room_state_as_bot.return_value = None
    return s


async def test_creates_missing_and_reuses_existing(svc):
    cm = ChannelManager(_cfg(), svc)
    rooms = await cm.ensure_channels()
    svc.create_room_as_bot.assert_awaited_once()
    kw = svc.create_room_as_bot.call_args.kwargs
    assert kw["alias_localpart"] == "general"
    assert kw["preset"] == "public_chat"
    assert kw["visibility"] == "public"
    assert rooms == {"general": "!gen-new:parrot.local", "finance": "!fin:parrot.local"}
    assert svc.ensure_agent_in_room.await_count == 3
    assert cm.channel_for_room("!fin:parrot.local").answer_policy == "mention"


async def test_alias_resolution_prevents_duplicate(svc):
    svc.resolve_alias.return_value = "!gen-old:parrot.local"
    cm = ChannelManager(_cfg(), svc)
    await cm.ensure_channels()
    svc.create_room_as_bot.assert_not_awaited()


async def test_reconcile_existing_state_warns(svc, caplog):
    svc.get_room_state_as_bot.return_value = {
        "name": "finance",
        "visibility": "public",
        "answer_policy": "swarm",
        "agents": [],
        "version": 1,
    }
    cm = ChannelManager(_cfg(), svc)
    with caplog.at_level("WARNING"):
        await cm.ensure_channels()
    assert any(c.args and c.args[1] == ParrotEventType.CHANNEL for c in svc.set_room_state_as_bot.await_args_list)
    assert "reconcil" in caplog.text.lower()


async def test_space_links_children(svc):
    svc.create_room_as_bot.side_effect = ["!space:parrot.local", "!gen-new:parrot.local"]
    cm = ChannelManager(_cfg(space=SpaceConfig(enabled=True)), svc)
    await cm.ensure_channels()
    types = [c.args[1] for c in svc.set_room_state_as_bot.await_args_list]
    assert types.count("m.space.child") == 2
    assert types.count("m.space.parent") == 2


async def test_no_space_by_default(svc):
    cm = ChannelManager(_cfg(), svc)
    await cm.ensure_channels()
    assert all(c.args[1] != "m.space.child" for c in svc.set_room_state_as_bot.await_args_list)
