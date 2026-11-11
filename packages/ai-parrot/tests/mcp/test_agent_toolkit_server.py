"""FEAT-877 — an ``agent-*`` section served through create_toolkit_mcp_server."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

import parrot.mcp.agent_toolkit as agent_toolkit_module
from parrot.bots.agent import Agent
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.registry import agent_registry
from parrot.registry.registry import BotConfig

AGENT = "feat877-stub"


class ServedAgent(Agent):
    """A class used solely to verify the local MCP server factory integration."""

    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next ``months`` months."""
        return {"months": months}


class ServedStub:
    """The lazily-created agent implementation used by the server integration test."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def forecast(self, months: int) -> dict:
        self.calls.append(("forecast", {"months": months}))
        return {"months": months}

    async def shutdown(self, **kwargs) -> None:
        self.calls.append(("shutdown", {}))

    async def cleanup(self) -> None:
        self.calls.append(("cleanup", {}))


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Register the served class and isolate the server config and lazy instance."""
    config = BotConfig(name=AGENT, class_name="ServedAgent", module=ServedAgent.__module__, mcp_local=True)
    agent_registry.register(AGENT, ServedAgent, replace=True, bot_config=config)
    monkeypatch.setattr(agent_toolkit_module, "discover_agents", lambda registry=None: agent_registry)
    stub = ServedStub()
    get_instance = AsyncMock(return_value=stub)
    monkeypatch.setattr(agent_registry, "get_instance", get_instance)
    config_path = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "toolkits": {
                    "agent-feat877-stub": {
                        "class": "parrot.mcp.agent_toolkit.AgentToolkit",
                        "kwargs": {"agent": AGENT},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    yield tmp_path, stub, get_instance
    agent_registry.unregister(AGENT)


@pytest.mark.asyncio
async def test_mcp_local_serves_agent_section(served) -> None:
    """The unchanged factory lists tools eagerly and constructs the agent only upon execution."""
    root, stub, get_instance = served

    server = create_toolkit_mcp_server("agent-feat877-stub", root=root)

    assert set(server.tools) == {"forecast"}
    assert get_instance.await_count == 0
    result = await server.tools["forecast"].execute({"months": 2})
    assert result["isError"] is False
    assert stub.calls == [("forecast", {"months": 2})]
    get_instance.assert_awaited_once_with(AGENT)
    await server.stop()
    assert ("shutdown", {}) in stub.calls
    assert ("cleanup", {}) in stub.calls
