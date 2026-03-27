"""Tests for ActivityFeed — append-only JSONL event log."""

import asyncio

import pytest

from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.feed import ActivityFeed


@pytest.fixture
def feed(tmp_path):
    config = FilesystemTransportConfig(root_dir=tmp_path, feed_retention=10)
    return ActivityFeed(tmp_path / "feed.jsonl", config)


class TestActivityFeed:
    @pytest.mark.asyncio
    async def test_emit_and_tail(self, feed):
        """Events are written and read correctly."""
        await feed.emit("test", {"key": "value"})
        entries = await feed.tail(5)
        assert len(entries) == 1
        assert entries[0]["event"] == "test"
        assert entries[0]["key"] == "value"
        assert "ts" in entries[0]

    @pytest.mark.asyncio
    async def test_tail_empty(self, tmp_path):
        """Tail on non-existent feed returns empty list."""
        config = FilesystemTransportConfig(root_dir=tmp_path)
        feed = ActivityFeed(tmp_path / "nonexistent.jsonl", config)
        entries = await feed.tail(10)
        assert entries == []

    @pytest.mark.asyncio
    async def test_rotation(self, feed):
        """Feed rotates at feed_retention limit, keeping most recent."""
        for i in range(15):
            await feed.emit("test", {"i": i})
        entries = await feed.tail(20)
        assert len(entries) <= 10
        assert entries[-1]["i"] == 14  # Most recent preserved

    @pytest.mark.asyncio
    async def test_tail_returns_last_n(self, feed):
        """tail(n) returns only the last n entries."""
        for i in range(5):
            await feed.emit("evt", {"i": i})
        entries = await feed.tail(3)
        assert len(entries) == 3
        assert entries[0]["i"] == 2
        assert entries[-1]["i"] == 4

    @pytest.mark.asyncio
    async def test_multiple_events(self, feed):
        """Multiple events are appended in order."""
        await feed.emit("join", {"agent": "a"})
        await feed.emit("message", {"from": "a", "to": "b"})
        await feed.emit("leave", {"agent": "a"})
        entries = await feed.tail(10)
        assert len(entries) == 3
        assert [e["event"] for e in entries] == ["join", "message", "leave"]

    @pytest.mark.asyncio
    async def test_rotation_preserves_recent(self, feed):
        """After rotation, the oldest entries are discarded."""
        for i in range(15):
            await feed.emit("test", {"i": i})
        entries = await feed.tail(20)
        # retention=10, so should keep last 10 (i=5..14)
        assert len(entries) == 10
        assert entries[0]["i"] == 5

    @pytest.mark.asyncio
    async def test_concurrent_emits(self, tmp_path):
        """Concurrent emit() calls don't corrupt the feed."""
        config = FilesystemTransportConfig(root_dir=tmp_path, feed_retention=100)
        feed = ActivityFeed(tmp_path / "concurrent.jsonl", config)

        async def writer(start: int) -> None:
            for i in range(5):
                await feed.emit("concurrent", {"val": start + i})

        await asyncio.gather(writer(0), writer(100), writer(200))
        entries = await feed.tail(50)
        # All 15 events should be written (though order may vary)
        assert len(entries) == 15

    @pytest.mark.asyncio
    async def test_emit_creates_parent_dir(self, tmp_path):
        """emit() creates the parent directory if needed."""
        config = FilesystemTransportConfig(root_dir=tmp_path, feed_retention=100)
        feed = ActivityFeed(tmp_path / "subdir" / "feed.jsonl", config)
        await feed.emit("test", {"ok": True})
        entries = await feed.tail(5)
        assert len(entries) == 1
