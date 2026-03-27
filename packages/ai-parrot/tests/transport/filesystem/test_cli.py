"""Tests for CLI overlay — state rendering and snapshot."""

import pytest

from parrot.transport.filesystem.cli import CrewCLI
from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.transport import FilesystemTransport


class TestCrewCLI:
    @pytest.mark.asyncio
    async def test_get_state_empty(self, tmp_path):
        """Empty root returns empty agents and feed."""
        cli = CrewCLI(tmp_path)
        state = await cli.get_state()
        assert state["agents"] == []
        assert state["feed"] == []

    def test_render_text_empty(self, tmp_path):
        """Render empty state mentions 0 agentes."""
        cli = CrewCLI(tmp_path)
        text = cli.render_text({"agents": [], "feed": []})
        assert "0 agentes" in text

    def test_render_text_with_agents(self, tmp_path):
        """Render state with agents shows their names."""
        cli = CrewCLI(tmp_path)
        state = {
            "agents": [{"name": "AgentA", "status": "active", "role": "agent", "pid": 1234}],
            "feed": [],
        }
        text = cli.render_text(state)
        assert "AgentA" in text
        assert "1 agentes" in text

    def test_render_text_with_feed(self, tmp_path):
        """Render state with feed events."""
        cli = CrewCLI(tmp_path)
        state = {
            "agents": [],
            "feed": [
                {"ts": "2026-02-23T12:00:00+00:00", "event": "agent_joined", "agent_id": "a1"},
            ],
        }
        text = cli.render_text(state)
        assert "agent_joined" in text
        assert "a1" in text

    @pytest.mark.asyncio
    async def test_get_state_with_live_agent(self, tmp_path):
        """State includes a running transport's agent."""
        config = FilesystemTransportConfig(
            root_dir=tmp_path,
            use_inotify=False,
            poll_interval=0.05,
        )
        async with FilesystemTransport(agent_name="LiveAgent", config=config):
            cli = CrewCLI(tmp_path)
            state = await cli.get_state()
            names = [a["name"] for a in state["agents"]]
            assert "LiveAgent" in names
            # Feed should have at least the join event.
            events = [e["event"] for e in state["feed"]]
            assert "agent_joined" in events

    def test_render_text_multiple_agents(self, tmp_path):
        """Render multiple agents."""
        cli = CrewCLI(tmp_path)
        state = {
            "agents": [
                {"name": "AgentA", "status": "idle", "role": "agent", "pid": 100},
                {"name": "AgentB", "status": "busy", "role": "coordinator", "pid": 200},
            ],
            "feed": [],
        }
        text = cli.render_text(state)
        assert "AgentA" in text
        assert "AgentB" in text
        assert "2 agentes" in text
