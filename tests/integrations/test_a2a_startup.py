"""
Integration tests for IntegrationBotManager._start_a2a_bot() (TASK-1709).

Uses a real ``aiohttp.web.Application`` (and a live ``TestServer``/dedicated
``TCPSite`` where needed) rather than mocking ``A2AServer`` itself, since
``A2AServer``/``A2ASecurityMiddleware`` are provided by the core/optional
``ai-parrot-server`` package and are cheap to exercise directly.
"""
import socket

import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web, ClientSession
from aiohttp.test_utils import TestClient, TestServer

from parrot.integrations.manager import IntegrationBotManager
from parrot.integrations.a2a.models import A2AAgentConfig


class _DummyAgent:
    def __init__(self, name: str = "TestAgent"):
        self.name = name
        self.description = "A test agent"
        self.role = None
        self.goal = None
        self.tools = []


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def manager_with_app():
    app = web.Application()
    bot_manager = MagicMock()
    bot_manager.get_app.return_value = app
    manager = IntegrationBotManager(bot_manager)
    return manager, app


class TestA2ABotSharedApp:
    @pytest.mark.asyncio
    async def test_start_a2a_bot_shared_app(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = A2AAgentConfig(name="TestA2A", chatbot_id="test_agent", tags=["test"])
        await manager._start_a2a_bot("TestA2A", cfg)

        assert "TestA2A" in manager.a2a_bots

    @pytest.mark.asyncio
    async def test_agent_card_endpoint(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = A2AAgentConfig(name="TestA2A", chatbot_id="test_agent")
        await manager._start_a2a_bot("TestA2A", cfg)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/.well-known/agent.json")
            assert resp.status == 200
            data = await resp.json()
            assert data["name"] == "TestAgent"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_aborts_when_agent_not_found(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=None)

        cfg = A2AAgentConfig(name="Missing", chatbot_id="missing_agent")
        await manager._start_a2a_bot("Missing", cfg)

        assert "Missing" not in manager.a2a_bots


class TestA2ABotBasePathCollision:
    @pytest.mark.asyncio
    async def test_multiple_agents_get_distinct_base_paths(self, manager_with_app):
        manager, app = manager_with_app
        agents = {"a1": _DummyAgent("Agent1"), "a2": _DummyAgent("Agent2")}

        async def get_bot(chatbot_id, system_prompt_override=None):
            return agents.get(chatbot_id)

        manager._get_agent = AsyncMock(side_effect=get_bot)

        await manager._start_a2a_bot("First", A2AAgentConfig(name="First", chatbot_id="a1"))
        await manager._start_a2a_bot("Second", A2AAgentConfig(name="Second", chatbot_id="a2"))

        assert len(manager.a2a_bots) == 2
        assert app["a2a_base_paths"] == {"/a2a", "/a2a/second"}


class TestA2ABotDedicatedPort:
    @pytest.mark.asyncio
    async def test_dedicated_port(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())
        port = _free_port()

        cfg = A2AAgentConfig(name="PortAgent", chatbot_id="test_agent", port=port)
        await manager._start_a2a_bot("PortAgent", cfg)

        assert "PortAgent" in manager.a2a_bots
        assert len(manager._a2a_runners) == 1

        try:
            async with ClientSession() as session:
                async with session.get(
                    f"http://127.0.0.1:{port}/.well-known/agent.json"
                ) as resp:
                    assert resp.status == 200
        finally:
            await manager.shutdown()


class TestA2ABotSecurity:
    @pytest.mark.asyncio
    async def test_security_middleware_wired_when_jwt_secret_set(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = A2AAgentConfig(name="SecureAgent", chatbot_id="test_agent", jwt_secret="s3cret")
        await manager._start_a2a_bot("SecureAgent", cfg)

        assert len(app.middlewares) == 1

    @pytest.mark.asyncio
    async def test_no_security_middleware_without_security_fields(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = A2AAgentConfig(name="OpenAgent", chatbot_id="test_agent")
        await manager._start_a2a_bot("OpenAgent", cfg)

        assert len(app.middlewares) == 0

    @pytest.mark.asyncio
    async def test_dedicated_port_rejects_unauthenticated_request(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())
        port = _free_port()

        cfg = A2AAgentConfig(
            name="SecurePort", chatbot_id="test_agent", port=port, jwt_secret="s3cret"
        )
        await manager._start_a2a_bot("SecurePort", cfg)

        try:
            async with ClientSession() as session:
                async with session.post(
                    f"http://127.0.0.1:{port}/a2a/rpc", json={}
                ) as resp:
                    assert resp.status == 401
        finally:
            await manager.shutdown()


class TestA2ASecurityScoping:
    """The security middleware must guard ONLY its own agent's routes.

    aiohttp middlewares are app-global, so an unscoped ``A2ASecurityMiddleware``
    on the shared app would 401 every other integration's routes the moment one
    A2A agent enables auth. These tests pin the scoping fix.
    """

    @pytest.mark.asyncio
    async def test_security_does_not_gate_other_routes(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        async def telegram_webhook(request):
            return web.json_response({"ok": True})

        app.router.add_post("/telegram/webhook", telegram_webhook)

        cfg = A2AAgentConfig(
            name="SecureAgent", chatbot_id="test_agent", jwt_secret="s3cret"
        )
        await manager._start_a2a_bot("SecureAgent", cfg)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            # Unrelated integration route must NOT be gated by A2A auth.
            resp = await client.post("/telegram/webhook", json={})
            assert resp.status == 200
            # The A2A agent's own route IS gated (no credentials → 401).
            resp = await client.post("/a2a/rpc", json={})
            assert resp.status == 401
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_security_does_not_gate_directory_or_other_a2a_agents(
        self, manager_with_app
    ):
        manager, app = manager_with_app
        agents = {"a1": _DummyAgent("Agent1"), "a2": _DummyAgent("Agent2")}

        async def get_bot(chatbot_id, system_prompt_override=None):
            return agents.get(chatbot_id)

        manager._get_agent = AsyncMock(side_effect=get_bot)

        # First agent secured on /a2a; second agent open on /a2a/second.
        await manager._start_a2a_bot(
            "First", A2AAgentConfig(name="First", chatbot_id="a1", jwt_secret="s3cret")
        )
        await manager._start_a2a_bot(
            "Second", A2AAgentConfig(name="Second", chatbot_id="a2")
        )

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            # Public directory listing must never be gated.
            resp = await client.get("/a2a/directory")
            assert resp.status == 200
            # The second (open) agent's routes must not be caught by the
            # first agent's scoped middleware.
            resp = await client.post("/a2a/second/rpc", json={})
            assert resp.status != 401
        finally:
            await client.close()


class TestA2ABotGracefulDegradation:
    @pytest.mark.asyncio
    async def test_missing_ai_parrot_server_is_handled_gracefully(
        self, manager_with_app, monkeypatch
    ):
        import builtins

        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "parrot.a2a.server":
                raise ImportError("simulated missing ai-parrot-server")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        cfg = A2AAgentConfig(name="NoServer", chatbot_id="test_agent")
        await manager._start_a2a_bot("NoServer", cfg)

        assert manager.a2a_bots == {}
