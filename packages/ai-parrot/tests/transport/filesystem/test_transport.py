"""Tests for FilesystemTransport — main orchestrator."""

import pytest

from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.transport import FilesystemTransport


@pytest.fixture
def fs_config(tmp_path):
    return FilesystemTransportConfig(
        root_dir=tmp_path,
        presence_interval=0.1,
        poll_interval=0.05,
        use_inotify=False,
        stale_threshold=1.0,
        message_ttl=60.0,
        feed_retention=100,
    )


@pytest.fixture
async def transport_a(fs_config):
    t = FilesystemTransport(agent_name="AgentA", config=fs_config)
    await t.start()
    yield t
    await t.stop()


@pytest.fixture
async def transport_b(fs_config):
    t = FilesystemTransport(agent_name="AgentB", config=fs_config)
    await t.start()
    yield t
    await t.stop()


class TestFilesystemTransport:
    @pytest.mark.asyncio
    async def test_start_stop(self, fs_config):
        """Start registers presence, stop deregisters."""
        t = FilesystemTransport(agent_name="TestAgent", config=fs_config)
        await t.start()
        agents = await t.list_agents()
        assert any(a["name"] == "TestAgent" for a in agents)
        await t.stop()

    @pytest.mark.asyncio
    async def test_send_and_receive(self, transport_a, transport_b):
        """AgentA sends to AgentB, AgentB receives."""
        await transport_a.send("AgentB", "Hello from A")
        msgs = []
        async for msg in transport_b.messages():
            msgs.append(msg)
            break
        assert msgs[0]["content"] == "Hello from A"
        assert msgs[0]["from_name"] == "AgentA"

    @pytest.mark.asyncio
    async def test_discovery(self, transport_a, transport_b):
        """list_agents() returns both agents."""
        agents = await transport_a.list_agents()
        names = {a["name"] for a in agents}
        assert "AgentA" in names
        assert "AgentB" in names

    @pytest.mark.asyncio
    async def test_broadcast(self, transport_a):
        """Broadcast to channel, poll from channel."""
        await transport_a.broadcast("Hello channel!", channel="general")
        msgs = []
        async for msg in transport_a.channel_messages("general"):
            msgs.append(msg)
        assert len(msgs) >= 1
        assert msgs[-1]["content"] == "Hello channel!"

    @pytest.mark.asyncio
    async def test_send_unknown_agent_raises(self, transport_a):
        """send() raises ValueError for unknown agent."""
        with pytest.raises(ValueError, match="not found"):
            await transport_a.send("NonExistent", "hello")

    @pytest.mark.asyncio
    async def test_set_status(self, transport_a):
        """set_status updates registry entry."""
        await transport_a.set_status("busy", "Processing data...")
        info = await transport_a.whois("AgentA")
        assert info["status"] == "busy"
        assert info["message"] == "Processing data..."

    @pytest.mark.asyncio
    async def test_context_manager(self, fs_config):
        """Async context manager starts and stops the transport."""
        async with FilesystemTransport(agent_name="CtxAgent", config=fs_config) as t:
            agents = await t.list_agents()
            assert any(a["name"] == "CtxAgent" for a in agents)

    @pytest.mark.asyncio
    async def test_reserve_and_release(self, transport_a):
        """reserve() and release() delegate to ReservationManager."""
        ok = await transport_a.reserve(["resource.csv"], reason="testing")
        assert ok is True
        await transport_a.release(["resource.csv"])

    @pytest.mark.asyncio
    async def test_reserve_conflict(self, transport_a, transport_b):
        """Two transports compete for overlapping resources."""
        ok1 = await transport_a.reserve(["shared.csv"])
        assert ok1 is True
        ok2 = await transport_b.reserve(["shared.csv"])
        assert ok2 is False

    @pytest.mark.asyncio
    async def test_whois(self, transport_a):
        """whois resolves agent by name."""
        info = await transport_a.whois("AgentA")
        assert info is not None
        assert info["name"] == "AgentA"
        assert info["agent_id"] == transport_a.agent_id

    @pytest.mark.asyncio
    async def test_whois_not_found(self, transport_a):
        """whois returns None for unknown agent."""
        info = await transport_a.whois("Ghost")
        assert info is None

    @pytest.mark.asyncio
    async def test_agent_id_and_name_properties(self, transport_a):
        """Properties expose agent ID and name."""
        assert transport_a.agent_name == "AgentA"
        assert transport_a.agent_id.startswith("agenta-")

    @pytest.mark.asyncio
    async def test_bidirectional_messaging(self, transport_a, transport_b):
        """Two transports exchange messages in both directions."""
        await transport_a.send("AgentB", "ping")
        await transport_b.send("AgentA", "pong")

        # B receives ping
        async for msg in transport_b.messages():
            assert msg["content"] == "ping"
            break

        # A receives pong
        async for msg in transport_a.messages():
            assert msg["content"] == "pong"
            break

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self, fs_config):
        """Calling start() twice does not error."""
        t = FilesystemTransport(agent_name="DoubleStart", config=fs_config)
        await t.start()
        await t.start()  # Should be a no-op
        agents = await t.list_agents()
        # Should still only have one entry
        count = sum(1 for a in agents if a["name"] == "DoubleStart")
        assert count == 1
        await t.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, fs_config):
        """Calling stop() without start() does not error."""
        t = FilesystemTransport(agent_name="NeverStarted", config=fs_config)
        await t.stop()  # Should be a no-op
