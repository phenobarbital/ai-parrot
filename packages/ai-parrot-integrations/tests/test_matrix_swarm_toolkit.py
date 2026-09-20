"""Tests for AgentSwarmToolkit — FEAT-463 TASK-2483."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.matrix.crew import context as ctx
from parrot.integrations.matrix.crew.swarm_toolkit import AgentSwarmToolkit
from parrot.integrations.matrix.events import AgentAnswer


@pytest.fixture
def tk():
    tunnels = AsyncMock()
    tunnel = AsyncMock()
    tunnel.ask.return_value = AgentAnswer(answer="42", metadata={"status": "ok"})
    tunnels.get_or_create.return_value = tunnel
    tunnels.config = MagicMock(echo_summary_to_channel=True)

    registry = AsyncMock()
    registry.get.side_effect = lambda n: MagicMock(agent_name=n) if n in ("writer", "analyst") else None
    registry.all_agents.return_value = [MagicMock(agent_name="writer", display_name="W", status="ready", skills=[])]

    channels = MagicMock()
    channels.is_member.side_effect = lambda a, c: c == "general"
    channels.room_for_channel.return_value = "!gen:s"
    channels.list_channels.return_value = [{"name": "general", "visibility": "public"}]

    svc = AsyncMock()
    return AgentSwarmToolkit("analyst", tunnels, registry, channels, svc), tunnel, svc


def test_exposes_five_tools(tk):
    names = sorted(t.name for t in tk[0].get_tools())
    assert names == ["ask_agent", "list_agents", "list_channels", "post_to_channel", "send_feedback"]


@pytest.mark.asyncio
async def test_ask_agent_roundtrip(tk):
    t, tunnel, _ = tk
    out = await t.ask_agent("writer", "hi")
    assert out["answer"] == "42"
    assert tunnel.ask.await_args.kwargs["hops"] == 0


@pytest.mark.asyncio
async def test_ask_agent_propagates_hops(tk):
    t, tunnel, _ = tk
    token = ctx.current_hops.set(2)
    try:
        await t.ask_agent("writer", "hi")
    finally:
        ctx.current_hops.reset(token)
    assert tunnel.ask.await_args.kwargs["hops"] == 2


@pytest.mark.asyncio
async def test_unknown_and_self(tk):
    t, _, _ = tk
    assert (await t.ask_agent("ghost", "q"))["status"] == "unknown_agent"
    assert (await t.ask_agent("analyst", "q"))["status"] == "self_ask_rejected"


@pytest.mark.asyncio
async def test_post_to_channel_policy(tk):
    t, _, svc = tk
    await t.post_to_channel("general", "hello")
    svc.send_as_agent.assert_awaited_once()
    assert "forbidden" in str(await t.post_to_channel("finance", "x"))


@pytest.mark.asyncio
async def test_echo_default_on(tk):
    t, _, svc = tk
    tok = ctx.current_channel_room.set("!gen:s")
    tok2 = ctx.current_trigger_event.set("$trig")
    try:
        await t.ask_agent("writer", "q")
    finally:
        ctx.current_channel_room.reset(tok)
        ctx.current_trigger_event.reset(tok2)
    svc.send_reply_as_agent.assert_awaited_once()
