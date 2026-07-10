"""Unit tests for A2A v1.0 mesh & router compatibility (FEAT-272 TASK-1718)."""
from parrot.a2a.models import AgentCard, AgentInterface, RegisteredAgent
from parrot.a2a.router import A2AProxyRouter


def _v1_card():
    return AgentCard(
        name="Test", description="T", version="1.0", skills=[],
        supported_interfaces=[
            AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                           protocol_version="1.0")
        ],
    )


class TestRegisteredAgentV1:
    def test_registered_agent_v1_card_url(self):
        card = _v1_card()
        agent = RegisteredAgent(url=card.url, card=card)
        assert agent.url == "https://a.com/a2a"

    def test_registered_agent_protocol_version_default(self):
        card = _v1_card()
        agent = RegisteredAgent(url=card.url, card=card)
        assert agent.protocol_version == "0.3"

    def test_registered_agent_protocol_version_v1(self):
        card = _v1_card()
        agent = RegisteredAgent(url=card.url, card=card, protocol_version="1.0")
        assert agent.protocol_version == "1.0"


class TestRouterAggregatedCard:
    def _router(self):
        # A2AProxyRouter needs a mesh; build a minimal stub.
        class _Mesh:
            def list_healthy(self):
                return []
        router = A2AProxyRouter.__new__(A2AProxyRouter)
        return router

    def test_request_version_helper(self):
        import types
        req = types.SimpleNamespace(headers={"A2A-Version": "1.0"})
        assert A2AProxyRouter._request_version(req) == "1.0"
        req2 = types.SimpleNamespace(headers={})
        assert A2AProxyRouter._request_version(req2) == "0.3"
