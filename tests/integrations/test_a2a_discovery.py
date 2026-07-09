"""
Tests for the in-process A2A discovery registry and the ``/a2a/directory``
endpoint (TASK-1709 — spec §2 "New Public Interfaces").
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.integrations.manager import IntegrationBotManager, handle_a2a_directory
from parrot.integrations.a2a.models import A2AAgentConfig


class _DummyAgent:
    def __init__(self, name: str = "TestAgent"):
        self.name = name
        self.description = None
        self.role = None
        self.goal = None
        self.tools = []


@pytest.fixture
def manager_with_app():
    app = web.Application()
    bot_manager = MagicMock()
    bot_manager.get_app.return_value = app
    manager = IntegrationBotManager(bot_manager)
    return manager, app


class TestDiscoveryRegistryInitialization:
    @pytest.mark.asyncio
    async def test_registry_initialized_on_first_bot(self, manager_with_app):
        manager, app = manager_with_app
        assert "a2a_discovery_registry" not in app

        manager._get_agent = AsyncMock(return_value=_DummyAgent())
        await manager._start_a2a_bot(
            "First", A2AAgentConfig(name="First", chatbot_id="a")
        )

        assert "a2a_discovery_registry" in app
        assert "First" in app["a2a_discovery_registry"]

    @pytest.mark.asyncio
    async def test_directory_route_registered_once(self, manager_with_app):
        manager, app = manager_with_app
        agents = {"a": _DummyAgent("Agent1"), "b": _DummyAgent("Agent2")}

        async def get_bot(chatbot_id, system_prompt_override=None):
            return agents.get(chatbot_id)

        manager._get_agent = AsyncMock(side_effect=get_bot)

        await manager._start_a2a_bot("First", A2AAgentConfig(name="First", chatbot_id="a"))
        await manager._start_a2a_bot("Second", A2AAgentConfig(name="Second", chatbot_id="b"))

        # add_get() registers both a GET and a HEAD route on the SAME
        # resource — count distinct resources, not routes, to verify the
        # directory endpoint was only mounted once.
        directory_resources = {
            route.resource
            for route in app.router.routes()
            if route.resource is not None and route.resource.canonical == "/a2a/directory"
        }
        assert len(directory_resources) == 1


class TestDiscoveryRegistryMultipleAgents:
    @pytest.mark.asyncio
    async def test_multiple_agents_registered(self, manager_with_app):
        manager, app = manager_with_app
        agents = {"a": _DummyAgent("Agent1"), "b": _DummyAgent("Agent2")}

        async def get_bot(chatbot_id, system_prompt_override=None):
            return agents.get(chatbot_id)

        manager._get_agent = AsyncMock(side_effect=get_bot)

        await manager._start_a2a_bot("First", A2AAgentConfig(name="First", chatbot_id="a"))
        await manager._start_a2a_bot("Second", A2AAgentConfig(name="Second", chatbot_id="b"))

        registry = app["a2a_discovery_registry"]
        assert set(registry.keys()) == {"First", "Second"}


class TestDirectoryEndpoint:
    @pytest.mark.asyncio
    async def test_directory_returns_json_array_of_cards(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())
        await manager._start_a2a_bot(
            "First", A2AAgentConfig(name="First", chatbot_id="a", tags=["x"])
        )

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/a2a/directory")
            assert resp.status == 200
            cards = await resp.json()
            assert isinstance(cards, list)
            assert len(cards) == 1
            assert cards[0]["name"] == "TestAgent"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_directory_lists_a2a_agents_only(self, manager_with_app):
        """/a2a/directory must never include telegram/slack/etc. bots."""
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())
        await manager._start_a2a_bot(
            "A2ABot", A2AAgentConfig(name="A2ABot", chatbot_id="a")
        )
        # Simulate a non-A2A bot dict being populated — it must never appear
        # in the discovery registry regardless.
        manager.slack_bots["SlackBot"] = MagicMock()

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/a2a/directory")
            cards = await resp.json()
            names = [c["name"] for c in cards]
            assert "SlackBot" not in names
            assert len(cards) == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_array(self):
        """No A2A bots ever started — /a2a/directory still returns []."""
        app = web.Application()
        app.router.add_get("/a2a/directory", handle_a2a_directory)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/a2a/directory")
            assert resp.status == 200
            cards = await resp.json()
            assert cards == []
        finally:
            await client.close()
