"""Tests for MatrixCollaborativeSession trigger reply-to & tunnel cross-pollination — FEAT-463 TASK-2485."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.matrix.crew.config import CollaborativeConfig
from parrot.integrations.matrix.crew.session import MatrixCollaborativeSession
from parrot.integrations.matrix.events import AgentAnswer

pytestmark = pytest.mark.asyncio


def _session(tunnels, **kw):
    svc = AsyncMock()
    svc.send_as_agent.return_value = "$r"
    svc.send_reply_as_agent.return_value = "$echo"
    svc.send_reply_as_bot.return_value = "$b"
    registry = AsyncMock()
    registry.all_agents.return_value = [MagicMock(agent_name=n, display_name=n, mxid=f"@{n}:s") for n in ("a", "b")]
    wrappers = {n: MagicMock(_config=MagicMock(chatbot_id=n)) for n in ("a", "b")}
    s = MatrixCollaborativeSession(
        "s1",
        "!gen:s",
        "Q?",
        CollaborativeConfig(max_rounds=1),
        svc,
        registry,
        wrappers,
        "s",
        trigger_event_id="$trig",
        tunnels=tunnels,
        **kw,
    )
    return s, svc


async def test_cross_pollination_uses_tunnel():
    tunnel = AsyncMock()
    tunnel.ask.return_value = AgentAnswer(answer="evidence", metadata={"status": "ok"})
    tunnels = AsyncMock()
    tunnels.get_or_create.return_value = tunnel
    tunnels.config = MagicMock(echo_summary_to_channel=True)
    s, svc = _session(tunnels)
    bot = MagicMock()
    bot.ask = AsyncMock(return_value="finding")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await s.run()
    assert tunnel.ask.await_count == 2  # a→b and b→a
    assert svc.send_reply_as_agent.await_count >= 2  # echo lines
    assert svc.send_reply_as_bot.await_args.args[2] == "$trig"  # final reply-to trigger


async def test_no_echo_when_disabled():
    tunnel = AsyncMock()
    tunnel.ask.return_value = AgentAnswer(answer="x")
    tunnels = AsyncMock()
    tunnels.get_or_create.return_value = tunnel
    tunnels.config = MagicMock(echo_summary_to_channel=False)
    s, svc = _session(tunnels)
    bot = MagicMock()
    bot.ask = AsyncMock(return_value="f")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await s.run()
    assert not any("🔒" in c.args[2] for c in svc.send_reply_as_agent.await_args_list)


async def test_legacy_path_without_tunnels():
    s, svc = _session(None)
    bot = MagicMock()
    bot.ask = AsyncMock(return_value="f")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await s.run()
    assert s.phase.value == "completed"


async def test_two_sessions_isolated():
    s1, _ = _session(None)
    s2, _ = _session(None)
    bot = MagicMock()
    bot.ask = AsyncMock(side_effect=["r1", "r1", "s", "r2", "r2", "s"])
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        st1 = await s1.run()
        st2 = await s2.run()
    assert st1.agent_results != st2.agent_results
