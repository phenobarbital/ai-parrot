"""Tests for MatrixCrewTransport swarm dispatch & concurrent sessions — FEAT-463 TASK-2484."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.matrix.crew.config import (
    ChannelConfig,
    CollaborativeConfig,
    MatrixCrewAgentEntry,
    MatrixCrewConfig,
)
from parrot.integrations.matrix.crew.transport import MatrixCrewTransport

pytestmark = pytest.mark.asyncio


def _transport(policy="swarm", max_sessions=2, cooldown=0.0):
    cfg = MatrixCrewConfig(
        homeserver_url="http://hs",
        server_name="parrot.local",
        as_token="a",
        hs_token="h",
        bot_mxid="@parrot:parrot.local",
        general_room_id="!gen:parrot.local",
        agents={
            "analyst": MatrixCrewAgentEntry(
                chatbot_id="analyst", display_name="A", mxid_localpart="parrot-analyst"
            )
        },
        collaborative=CollaborativeConfig(max_concurrent_sessions=max_sessions, cooldown_seconds=cooldown),
        channels=[
            ChannelConfig(
                name="general", agents=["analyst"], answer_policy=policy, room_id="!gen:parrot.local"
            )
        ],
    )
    t = MatrixCrewTransport(cfg)
    t._appservice = AsyncMock()
    t._agent_mxids = {"@parrot-analyst:parrot.local"}
    t._channels = MagicMock()
    t._channels.channel_for_room.side_effect = (
        lambda r: cfg.channels[0] if r == "!gen:parrot.local" else None
    )
    t._registry.set_human_patterns(cfg.human_namespace_patterns)
    t._build_session = MagicMock(side_effect=lambda *a, **k: MagicMock(is_active=True, run=AsyncMock()))
    from parrot.integrations.matrix.crew.swarm import SwarmSessionManager

    t._swarm = SwarmSessionManager(cfg.collaborative, t)
    return t


async def test_swarm_policy_starts_session():
    t = _transport()
    await t.on_room_message("!gen:parrot.local", "@alice:parrot.local", "what is the Q2 trend?", "$e1")
    assert t._build_session.call_count == 1


@pytest.mark.parametrize("policy", ["mention", "silent"])
async def test_non_swarm_policies_ignore(policy):
    t = _transport(policy)
    await t.on_room_message("!gen:parrot.local", "@alice:parrot.local", "hello?", "$e1")
    t._build_session.assert_not_called()


async def test_concurrency_cap_and_busy_reply():
    t = _transport(max_sessions=2)
    for i in range(3):
        await t.on_room_message("!gen:parrot.local", "@alice:parrot.local", f"q{i}", f"$e{i}")
    assert t._build_session.call_count == 2
    t._appservice.send_reply_as_bot.assert_awaited_once()


async def test_cooldown():
    t = _transport(cooldown=60)
    await t.on_room_message("!gen:parrot.local", "@a:parrot.local", "q1", "$1")
    await t.on_room_message("!gen:parrot.local", "@a:parrot.local", "q2", "$2")
    assert t._build_session.call_count == 1


async def test_investigate_still_works():
    t = _transport("mention")
    await t.on_room_message("!gen:parrot.local", "@a:parrot.local", "!investigate why?", "$1")
    assert t._build_session.call_count == 1


async def test_bridged_user_is_human():
    t = _transport()
    await t.on_room_message("!gen:parrot.local", "@slack_U123:parrot.local", "from slack", "$1")
    assert t._build_session.call_count == 1
