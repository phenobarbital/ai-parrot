"""Unit tests for AgentRegistry."""

import os

import pytest

from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.registry import AgentRegistry


@pytest.fixture
def registry(tmp_path):
    """Create an AgentRegistry with a temp directory."""
    config = FilesystemTransportConfig(root_dir=tmp_path)
    return AgentRegistry(tmp_path / "registry", config)


class TestAgentRegistry:
    """Tests for AgentRegistry join/leave/heartbeat/resolve/gc."""

    @pytest.mark.asyncio
    async def test_join_creates_file(self, registry, tmp_path):
        """join() creates a JSON file in the registry directory."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        assert (tmp_path / "registry" / "a1.json").exists()

    @pytest.mark.asyncio
    async def test_join_data_fields(self, registry):
        """join() stores all required fields."""
        await registry.join("a1", "AgentA", os.getpid(), "myhost", "/work", "agent")
        data = await registry._read("a1")
        assert data["agent_id"] == "a1"
        assert data["name"] == "AgentA"
        assert data["pid"] == os.getpid()
        assert data["hostname"] == "myhost"
        assert data["cwd"] == "/work"
        assert data["role"] == "agent"
        assert data["status"] == "idle"
        assert "joined_at" in data
        assert "last_seen" in data

    @pytest.mark.asyncio
    async def test_leave_removes_file(self, registry, tmp_path):
        """leave() removes the registry file."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        await registry.leave("a1")
        assert not (tmp_path / "registry" / "a1.json").exists()

    @pytest.mark.asyncio
    async def test_leave_nonexistent_no_error(self, registry):
        """leave() on a nonexistent agent does not raise."""
        await registry.leave("nonexistent")

    @pytest.mark.asyncio
    async def test_heartbeat_updates_last_seen(self, registry):
        """heartbeat() updates the last_seen timestamp."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        data_before = await registry._read("a1")
        import time
        time.sleep(0.01)
        await registry.heartbeat("a1")
        data_after = await registry._read("a1")
        assert data_after["last_seen"] > data_before["last_seen"]

    @pytest.mark.asyncio
    async def test_heartbeat_updates_status(self, registry):
        """heartbeat() can update status and message."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        await registry.heartbeat("a1", status="busy", message="working on task")
        data = await registry._read("a1")
        assert data["status"] == "busy"
        assert data["message"] == "working on task"

    @pytest.mark.asyncio
    async def test_list_active_returns_live(self, registry):
        """list_active() returns agents with live PIDs."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        agents = await registry.list_active()
        assert len(agents) == 1
        assert agents[0]["name"] == "AgentA"

    @pytest.mark.asyncio
    async def test_pid_detection_dead(self, registry):
        """list_active() filters out agents with dead PIDs."""
        await registry.join("a1", "AgentA", 999999999, "host", "/cwd", "agent")
        agents = await registry.list_active()
        assert len(agents) == 0

    @pytest.mark.asyncio
    async def test_list_active_multiple(self, registry):
        """list_active() returns multiple live agents."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        await registry.join("a2", "AgentB", os.getpid(), "host", "/cwd", "agent")
        agents = await registry.list_active()
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_gc_stale(self, registry):
        """gc_stale() removes entries with dead PIDs."""
        await registry.join("a1", "AgentA", 999999999, "host", "/cwd", "agent")
        removed = await registry.gc_stale()
        assert "a1" in removed

    @pytest.mark.asyncio
    async def test_gc_stale_keeps_live(self, registry):
        """gc_stale() keeps agents with live PIDs."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        removed = await registry.gc_stale()
        assert len(removed) == 0
        agents = await registry.list_active()
        assert len(agents) == 1

    @pytest.mark.asyncio
    async def test_resolve_by_id(self, registry):
        """resolve() finds by exact agent_id."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        result = await registry.resolve("a1")
        assert result is not None
        assert result["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_resolve_by_name_case_insensitive(self, registry):
        """resolve() finds by name case-insensitively."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        result = await registry.resolve("agenta")
        assert result is not None
        assert result["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_resolve_not_found(self, registry):
        """resolve() returns None for unknown agent."""
        result = await registry.resolve("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_scope_to_cwd_filtering(self, tmp_path):
        """scope_to_cwd=True filters agents by cwd."""
        config = FilesystemTransportConfig(root_dir=tmp_path, scope_to_cwd=True)
        registry = AgentRegistry(tmp_path / "registry", config)
        cwd = os.getcwd()
        await registry.join("a1", "AgentA", os.getpid(), "host", cwd, "agent")
        await registry.join("a2", "AgentB", os.getpid(), "host", "/other/dir", "agent")
        agents = await registry.list_active()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_write_then_rename_atomicity(self, registry, tmp_path):
        """Write-then-rename: no .tmp files left after write."""
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        reg_dir = tmp_path / "registry"
        tmp_files = [f for f in reg_dir.iterdir() if f.name.startswith(".tmp")]
        assert len(tmp_files) == 0

    @pytest.mark.asyncio
    async def test_list_active_empty_dir(self, registry):
        """list_active() on empty/nonexistent dir returns empty list."""
        agents = await registry.list_active()
        assert agents == []
