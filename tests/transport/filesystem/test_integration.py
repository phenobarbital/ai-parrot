"""Integration tests for FilesystemTransport — end-to-end scenarios."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from parrot.autonomous.hooks.models import FilesystemHookConfig
from parrot.transport.filesystem.feed import ActivityFeed
from parrot.transport.filesystem.hook import FilesystemHook
from parrot.transport.filesystem.transport import FilesystemTransport

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestTwoAgentConversation:
    async def test_bidirectional_exchange(self, transport_a, transport_b):
        """A sends to B, B replies to A."""
        await transport_a.send("AgentB", "ping")

        # B receives the ping.
        async for msg in transport_b.messages():
            assert msg["content"] == "ping"
            assert msg["from_name"] == "AgentA"
            await transport_b.send("AgentA", "pong", reply_to=msg["id"])
            break

        # A receives the pong.
        async for msg in transport_a.messages():
            assert msg["content"] == "pong"
            assert msg["from_name"] == "AgentB"
            assert msg["reply_to"] is not None
            break

    async def test_multiple_messages_ordering(self, transport_a, transport_b):
        """Multiple messages arrive in order."""
        for i in range(5):
            await transport_a.send("AgentB", f"msg-{i}")

        # Small delay for filesystem writes.
        await asyncio.sleep(0.1)

        received = []
        async for msg in transport_b.messages():
            received.append(msg["content"])
            if len(received) == 5:
                break

        assert received == [f"msg-{i}" for i in range(5)]


class TestBroadcast:
    async def test_three_agents_channel(self, fs_config):
        """Three agents see a broadcast on a shared channel."""
        agents = []
        for name in ["A", "B", "C"]:
            t = FilesystemTransport(agent_name=f"Agent{name}", config=fs_config)
            await t.start()
            agents.append(t)
        try:
            await agents[0].broadcast("Hello everyone!", channel="crew")

            for agent in agents:
                msgs = []
                async for msg in agent.channel_messages("crew"):
                    msgs.append(msg)
                assert len(msgs) >= 1
                assert msgs[0]["content"] == "Hello everyone!"
        finally:
            for t in agents:
                await t.stop()

    async def test_multiple_broadcasts(self, transport_a, transport_b):
        """Multiple broadcasts on the same channel are all visible."""
        await transport_a.broadcast("first", channel="updates")
        await transport_a.broadcast("second", channel="updates")

        msgs = []
        async for msg in transport_b.channel_messages("updates"):
            msgs.append(msg["content"])

        assert "first" in msgs
        assert "second" in msgs


class TestReservationConflict:
    async def test_all_or_nothing(self, transport_a, transport_b):
        """Second reservation fails if any resource is already held."""
        ok1 = await transport_a.reserve(["file_a.csv", "file_b.csv"])
        assert ok1 is True

        # B tries to reserve overlapping resources — must fail.
        ok2 = await transport_b.reserve(["file_b.csv", "file_c.csv"])
        assert ok2 is False

    async def test_release_allows_reacquire(self, transport_a, transport_b):
        """After release, another agent can acquire the resource."""
        ok1 = await transport_a.reserve(["shared.csv"])
        assert ok1 is True

        await transport_a.release(["shared.csv"])

        ok2 = await transport_b.reserve(["shared.csv"])
        assert ok2 is True

    async def test_disjoint_reservations_succeed(self, transport_a, transport_b):
        """Non-overlapping reservations both succeed."""
        ok1 = await transport_a.reserve(["file_a.csv"])
        assert ok1 is True

        ok2 = await transport_b.reserve(["file_b.csv"])
        assert ok2 is True


class TestPresenceLifecycle:
    async def test_join_heartbeat_leave(self, fs_config):
        """Agent appears on join, disappears after stop."""
        t = FilesystemTransport(agent_name="LifecycleAgent", config=fs_config)
        await t.start()

        agents = await t.list_agents()
        assert any(a["name"] == "LifecycleAgent" for a in agents)

        await t.stop()

        # After stop, an observer should not see the old agent.
        t2 = FilesystemTransport(agent_name="Observer", config=fs_config)
        await t2.start()
        agents = await t2.list_agents()
        names = {a["name"] for a in agents}
        assert "LifecycleAgent" not in names
        await t2.stop()

    async def test_status_update(self, transport_a):
        """Status update is reflected in agent listing."""
        await transport_a.set_status("busy", "processing data")
        agents = await transport_a.list_agents()
        me = next(a for a in agents if a["name"] == "AgentA")
        assert me["status"] == "busy"

    async def test_whois(self, transport_a, transport_b):
        """whois returns info about a specific agent."""
        info = await transport_a.whois("AgentB")
        assert info is not None
        assert info["name"] == "AgentB"


class TestFeedCompleteness:
    async def test_all_events_captured(self, fs_config):
        """Feed captures agent_joined, broadcast, reservation_acquired, reservation_released, agent_left."""
        t = FilesystemTransport(agent_name="FeedAgent", config=fs_config)
        await t.start()
        await t.broadcast("hi", channel="general")
        await t.reserve(["test.csv"], reason="testing")
        await t.release(["test.csv"])
        await t.stop()

        feed = ActivityFeed(fs_config.root_dir / "feed.jsonl", fs_config)
        events = await feed.tail(50)
        event_types = {e["event"] for e in events}

        assert "agent_joined" in event_types
        assert "broadcast" in event_types
        assert "reservation_acquired" in event_types
        assert "reservation_released" in event_types
        assert "agent_left" in event_types

    async def test_feed_records_message_sent(self, transport_a, transport_b):
        """Sending a message emits a message_sent event."""
        await transport_a.send("AgentB", "hello")

        feed = ActivityFeed(
            transport_a._config.root_dir / "feed.jsonl",
            transport_a._config,
        )
        events = await feed.tail(50)
        event_types = {e["event"] for e in events}
        assert "message_sent" in event_types


class TestHookDispatch:
    async def test_hook_receives_messages(self, tmp_path):
        """FilesystemHook dispatches incoming messages as HookEvents."""
        config = FilesystemHookConfig(
            target_id="HookAgent",
            transport={
                "root_dir": str(tmp_path),
                "use_inotify": False,
                "poll_interval": 0.05,
            },
        )
        hook = FilesystemHook(config=config)
        callback = AsyncMock()
        hook.set_callback(callback)

        await hook.start()

        # Send a message from a separate transport.
        from parrot.transport.filesystem.config import FilesystemTransportConfig

        sender_cfg = FilesystemTransportConfig(
            root_dir=tmp_path, use_inotify=False
        )
        async with FilesystemTransport(
            agent_name="Sender", config=sender_cfg
        ) as sender:
            await sender.send("HookAgent", "integration test message")

        await asyncio.sleep(0.3)
        await hook.stop()

        assert callback.called
        event = callback.call_args[0][0]
        assert event.event_type == "filesystem.message"
        assert event.payload["content"] == "integration test message"
        assert event.payload["from_name"] == "Sender"

    async def test_hook_filters_by_prefix(self, tmp_path):
        """Hook with command_prefix only dispatches matching messages."""
        config = FilesystemHookConfig(
            target_id="PrefixAgent",
            command_prefix="/",
            transport={
                "root_dir": str(tmp_path),
                "use_inotify": False,
                "poll_interval": 0.05,
            },
        )
        hook = FilesystemHook(config=config)
        callback = AsyncMock()
        hook.set_callback(callback)

        await hook.start()

        from parrot.transport.filesystem.config import FilesystemTransportConfig

        sender_cfg = FilesystemTransportConfig(
            root_dir=tmp_path, use_inotify=False
        )
        async with FilesystemTransport(
            agent_name="Sender", config=sender_cfg
        ) as sender:
            await sender.send("PrefixAgent", "no prefix")
            await sender.send("PrefixAgent", "/help me")

        await asyncio.sleep(0.3)
        await hook.stop()

        assert callback.call_count == 1
        event = callback.call_args[0][0]
        assert event.payload["content"] == "help me"
