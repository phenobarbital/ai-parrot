"""Tests for ChannelManager — broadcast channels via JSONL files."""

import asyncio

import pytest

from parrot.transport.filesystem.channel import ChannelManager
from parrot.transport.filesystem.config import FilesystemTransportConfig


@pytest.fixture
def channels(tmp_path):
    config = FilesystemTransportConfig(root_dir=tmp_path)
    return ChannelManager(tmp_path / "channels", config)


class TestChannelManager:
    @pytest.mark.asyncio
    async def test_publish_and_poll(self, channels):
        """Publish a message and poll it back."""
        await channels.publish("general", "a1", "AgentA", "Hello!", {})
        msgs = []
        async for msg in channels.poll("general", since_offset=0):
            msgs.append(msg)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hello!"
        assert msgs[0]["from_agent"] == "a1"
        assert msgs[0]["from_name"] == "AgentA"
        assert "ts" in msgs[0]
        assert msgs[0]["offset"] == 0

    @pytest.mark.asyncio
    async def test_poll_with_offset(self, channels):
        """Poll skips messages before the given offset."""
        await channels.publish("general", "a1", "A", "msg1", {})
        await channels.publish("general", "a1", "A", "msg2", {})
        msgs = []
        async for msg in channels.poll("general", since_offset=1):
            msgs.append(msg)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "msg2"
        assert msgs[0]["offset"] == 1

    @pytest.mark.asyncio
    async def test_list_channels(self, channels):
        """list_channels returns all channel names."""
        await channels.publish("general", "a1", "A", "hi", {})
        await channels.publish("crew", "a1", "A", "hi", {})
        result = await channels.list_channels()
        assert set(result) == {"general", "crew"}

    @pytest.mark.asyncio
    async def test_poll_nonexistent_channel(self, channels):
        """Polling a non-existent channel yields nothing."""
        msgs = []
        async for msg in channels.poll("nonexistent"):
            msgs.append(msg)
        assert msgs == []

    @pytest.mark.asyncio
    async def test_list_channels_empty(self, channels):
        """list_channels on empty dir returns empty list."""
        result = await channels.list_channels()
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_messages_order(self, channels):
        """Multiple messages are returned in publish order."""
        for i in range(5):
            await channels.publish("ordered", "a1", "A", f"msg-{i}", {})
        msgs = []
        async for msg in channels.poll("ordered"):
            msgs.append(msg["content"])
        assert msgs == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]

    @pytest.mark.asyncio
    async def test_publish_with_payload(self, channels):
        """Payload data is preserved."""
        await channels.publish("general", "a1", "A", "data", {"key": "val"})
        msgs = []
        async for msg in channels.poll("general"):
            msgs.append(msg)
        assert msgs[0]["payload"] == {"key": "val"}

    @pytest.mark.asyncio
    async def test_invalid_channel_name(self, channels):
        """Invalid channel names raise ValueError."""
        with pytest.raises(ValueError, match="Invalid channel name"):
            await channels.publish("../etc", "a1", "A", "bad", {})

    @pytest.mark.asyncio
    async def test_concurrent_publishes(self, channels):
        """Concurrent publishes don't corrupt the channel file."""
        async def writer(start: int) -> None:
            for i in range(5):
                await channels.publish("conc", "a1", "A", f"v-{start + i}", {})

        await asyncio.gather(writer(0), writer(100), writer(200))
        msgs = []
        async for msg in channels.poll("conc"):
            msgs.append(msg)
        assert len(msgs) == 15
