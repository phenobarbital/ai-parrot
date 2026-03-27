"""Tests for InboxManager — point-to-point message delivery."""

import asyncio

import pytest

from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.inbox import InboxManager


@pytest.fixture
def fs_config(tmp_path):
    return FilesystemTransportConfig(
        root_dir=tmp_path, poll_interval=0.05, use_inotify=False, message_ttl=60.0
    )


@pytest.fixture
def inbox(tmp_path, fs_config):
    mgr = InboxManager(tmp_path / "inbox", "agent-b", fs_config)
    mgr.setup()
    return mgr


class TestInboxManager:
    @pytest.mark.asyncio
    async def test_delivery_is_atomic(self, inbox):
        """Large message reads complete, no partial reads."""
        big_content = "x" * 100_000
        await inbox.deliver("agent-a", "AgentA", "agent-b", big_content, "msg", {}, None)
        msgs = []
        async for msg in inbox.poll():
            msgs.append(msg)
            break
        assert len(msgs) == 1
        assert msgs[0]["content"] == big_content

    @pytest.mark.asyncio
    async def test_exactly_once(self, inbox):
        """Message not processed twice."""
        await inbox.deliver("a", "A", "agent-b", "hello", "msg", {}, None)
        first = []
        async for msg in inbox.poll():
            first.append(msg)
            break
        assert len(first) == 1

        # Second poll should find nothing.
        second = []

        async def check():
            async for msg in inbox.poll():
                second.append(msg)
                break

        try:
            await asyncio.wait_for(check(), timeout=0.2)
        except asyncio.TimeoutError:
            pass
        assert len(second) == 0

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, tmp_path, fs_config):
        """Expired messages are filtered out."""
        fs_config.message_ttl = 0.001  # Expire almost immediately
        inbox = InboxManager(tmp_path / "inbox", "agent-b", fs_config)
        inbox.setup()
        await inbox.deliver("a", "A", "agent-b", "expired", "msg", {}, None)
        await asyncio.sleep(0.1)  # Let it expire
        msgs = []

        async def check():
            async for msg in inbox.poll():
                msgs.append(msg)
                break

        try:
            await asyncio.wait_for(check(), timeout=0.3)
        except asyncio.TimeoutError:
            pass
        assert len(msgs) == 0

    @pytest.mark.asyncio
    async def test_poll_order(self, inbox, tmp_path):
        """Messages are polled in chronological order (by mtime)."""
        import time

        # Deliver three messages with distinct mtimes.
        await inbox.deliver("a", "A", "agent-b", "first", "msg", {}, None)
        time.sleep(0.05)
        await inbox.deliver("a", "A", "agent-b", "second", "msg", {}, None)
        time.sleep(0.05)
        await inbox.deliver("a", "A", "agent-b", "third", "msg", {}, None)

        msgs = []
        count = 0
        async for msg in inbox.poll():
            msgs.append(msg["content"])
            count += 1
            if count >= 3:
                break

        assert msgs == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_deliver_creates_recipient_dir(self, tmp_path, fs_config):
        """Delivering to a new agent creates their inbox directory."""
        inbox = InboxManager(tmp_path / "inbox", "agent-a", fs_config)
        inbox.setup()
        await inbox.deliver("agent-a", "AgentA", "new-agent", "hi", "msg", {}, None)
        assert (tmp_path / "inbox" / "new-agent").is_dir()

    @pytest.mark.asyncio
    async def test_message_format(self, inbox):
        """Delivered messages have the expected JSON structure."""
        msg_id = await inbox.deliver(
            "agent-a", "AgentA", "agent-b", "test", "command", {"key": "val"}, "reply-123"
        )
        assert msg_id.startswith("msg-")

        msgs = []
        async for msg in inbox.poll():
            msgs.append(msg)
            break

        m = msgs[0]
        assert m["id"] == msg_id
        assert m["from"] == "agent-a"
        assert m["from_name"] == "AgentA"
        assert m["to"] == "agent-b"
        assert m["type"] == "command"
        assert m["content"] == "test"
        assert m["payload"] == {"key": "val"}
        assert m["reply_to"] == "reply-123"
        assert "timestamp" in m
        assert "expires_at" in m

    @pytest.mark.asyncio
    async def test_keep_processed_false(self, tmp_path, fs_config):
        """When keep_processed=False, messages are deleted instead of moved."""
        fs_config.keep_processed = False
        inbox = InboxManager(tmp_path / "inbox", "agent-b", fs_config)
        inbox.setup()
        await inbox.deliver("a", "A", "agent-b", "ephemeral", "msg", {}, None)

        async for msg in inbox.poll():
            break

        # .processed/ should be empty (message deleted, not moved).
        processed = list((tmp_path / "inbox" / "agent-b" / ".processed").iterdir())
        assert len(processed) == 0

    @pytest.mark.asyncio
    async def test_setup_creates_dirs(self, tmp_path, fs_config):
        """setup() creates inbox and .processed directories."""
        inbox = InboxManager(tmp_path / "inbox", "test-agent", fs_config)
        inbox.setup()
        assert (tmp_path / "inbox" / "test-agent").is_dir()
        assert (tmp_path / "inbox" / "test-agent" / ".processed").is_dir()
