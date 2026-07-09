"""Unit tests for A2A Mesh & Router v1.0.0 compatibility (FEAT-272 / TASK-1718).

Covers:
    - `RegisteredAgent.protocol_version` field.
    - `AgentCard.url` (property, TASK-1713) works transparently when
      building a `RegisteredAgent` from a v1.0.0 card.
    - `A2AProxyRouter.get_agent_card()` builds without a `url` kwarg
      (previously broken by the TASK-1713 `AgentCard` restructuring).
    - `A2AProxyRouter._get_request_version()` / `_apply_version_header()`.
"""
from unittest.mock import MagicMock

import pytest
from aiohttp import web

from parrot.a2a.models import AgentCard, AgentInterface, RegisteredAgent
from parrot.a2a.mesh import A2AMeshDiscovery
from parrot.a2a.router import A2AProxyRouter


class TestMeshV1Compat:
    def test_registered_agent_v1_card(self):
        card = AgentCard(
            name="Test", description="T", version="1.0", skills=[],
            supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                               protocol_version="1.0")
            ],
        )
        agent = RegisteredAgent(url=card.url, card=card)
        assert agent.url == "https://a.com/a2a"

    def test_registered_agent_protocol_version_default(self):
        card = AgentCard(
            name="Test", description="T", version="1.0", skills=[],
            supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                               protocol_version="1.0")
            ],
        )
        agent = RegisteredAgent(url=card.url, card=card)
        assert agent.protocol_version == "0.3"

    def test_registered_agent_protocol_version_explicit(self):
        card = AgentCard(
            name="Test", description="T", version="1.0", skills=[],
            supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                               protocol_version="1.0")
            ],
        )
        agent = RegisteredAgent(url=card.url, card=card, protocol_version="1.0")
        assert agent.protocol_version == "1.0"

    def test_mesh_discovery_instantiates(self):
        # Smoke test: A2AMeshDiscovery still imports/instantiates cleanly
        # after the RegisteredAgent field addition.
        mesh = A2AMeshDiscovery()
        assert mesh is not None


@pytest.fixture
def mesh_stub():
    mesh = MagicMock()
    mesh.list_healthy = MagicMock(return_value=[])
    return mesh


class TestRouterV1Compat:
    def test_get_agent_card_builds_without_url_kwarg(self, mesh_stub):
        """Regression test: AgentCard(url=None, ...) broke after TASK-1713
        restructured AgentCard to use `supported_interfaces`. Verifies the
        router's get_agent_card() was updated to construct the card
        correctly (supported_interfaces=[]) and that `card.url` still works
        via the property setter once the router is "mounted" for a request.
        """
        router = A2AProxyRouter(mesh_stub, name="TestRouter")
        card = router.get_agent_card()
        assert card.url is None
        assert card.supported_interfaces == []

        card.url = "https://gateway.example.com"
        assert card.url == "https://gateway.example.com"
        assert len(card.supported_interfaces) == 1

    def test_get_request_version(self, mesh_stub):
        router = A2AProxyRouter(mesh_stub, name="TestRouter")

        req_v1 = MagicMock()
        req_v1.headers = {"A2A-Version": "1.0"}
        assert router._get_request_version(req_v1) == "1.0"

        req_v03 = MagicMock()
        req_v03.headers = {}
        assert router._get_request_version(req_v03) == "0.3"

        req_unknown = MagicMock()
        req_unknown.headers = {"A2A-Version": "99.9"}
        assert router._get_request_version(req_unknown) == "0.3"

    def test_apply_version_header_forwards_to_client_session(self, mesh_stub):
        router = A2AProxyRouter(mesh_stub, name="TestRouter")
        client = MagicMock()
        client._session = MagicMock()
        client._session.headers = {}

        router._apply_version_header(client, "1.0")
        assert client._session.headers["A2A-Version"] == "1.0"

    def test_apply_version_header_noop_when_absent(self, mesh_stub):
        router = A2AProxyRouter(mesh_stub, name="TestRouter")
        client = MagicMock()
        client._session = MagicMock()
        client._session.headers = {}

        router._apply_version_header(client, None)
        assert "A2A-Version" not in client._session.headers


class TestRouterDiscoveryHandler:
    async def test_handle_discovery_v1_format(self, mesh_stub):
        router = A2AProxyRouter(mesh_stub, name="TestRouter")
        app = web.Application()
        router.setup(app)

        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/.well-known/agent.json", headers={"A2A-Version": "1.0"}
            )
            data = await resp.json()
            assert "supportedInterfaces" in data

    async def test_handle_discovery_v03_format(self, mesh_stub):
        router = A2AProxyRouter(mesh_stub, name="TestRouter")
        app = web.Application()
        router.setup(app)

        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/.well-known/agent.json")
            data = await resp.json()
            assert "url" in data
            assert "supportedInterfaces" not in data
