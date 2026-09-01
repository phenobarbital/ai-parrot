"""Unit tests for agent metadata MCP resources (FEAT-477, TASK-2603)."""
import json

import pytest
from parrot.mcp.agent_resources import register_agent_resources
from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer


def _read_json(response: dict) -> dict:
    """Unwrap the MCP `resources/read` envelope back into its JSON payload."""
    return json.loads(response["contents"][0]["text"])


class _FakeKB:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description


class _FakeToolManager:
    def __init__(self, tool_names: list[str]):
        self._tool_names = list(tool_names)

    def list_tools(self) -> list[str]:
        return list(self._tool_names)


class _FinanceAgent:
    """A fake agent carrying both allowlisted and hard-excluded fields."""

    def __init__(self):
        self.name = "finance"
        self.role = "Financial Analyst"
        self.goal = "Forecast quarterly revenue"
        self.capabilities = ["forecasting", "reporting"]
        self.description = "Finance analysis agent"
        # OQ8 hard exclusion — must never reach any resource payload.
        self.backstory = "SECRET_BACKSTORY_TEXT"
        self.rationale = "SECRET_RATIONALE_TEXT"
        self.tool_manager = _FakeToolManager(["restricted_tool", "public_tool"])
        self.knowledge_bases = [
            _FakeKB("finance-kb", "Finance knowledge base"),
            _FakeKB("market-kb", "Market data knowledge base"),
        ]


def _deny_restricted(agent_name: str, tool_name: str) -> bool:
    return tool_name != "restricted_tool"


@pytest.fixture
def agent() -> _FinanceAgent:
    return _FinanceAgent()


@pytest.fixture
def server(agent) -> StreamableHttpMCPServer:
    srv = StreamableHttpMCPServer(MCPServerConfig(name="test-agent-mcp"))
    register_agent_resources(
        srv,
        "finance",
        agent,
        exposure_names=["forecast"],
        policy_filter=_deny_restricted,
    )
    return srv


class TestAgentResources:
    async def test_three_resources_advertised(self, server):
        listed = await server.handle_resources_list({})
        assert len(listed["resources"]) == 3

    async def test_identity_card_fields(self, server):
        card = _read_json(
            await server.handle_resources_read({"uri": "agent://finance/identity"})
        )
        assert {"name", "role", "goal", "capabilities", "description"} <= set(card)
        assert card["name"] == "finance"
        assert card["role"] == "Financial Analyst"

    async def test_resources_exclude_system_prompt(self, server, agent):
        """OQ8 INVARIANT — merge blocker."""
        listed = await server.handle_resources_list({})
        blob = json.dumps(listed)
        for banned in ("backstory", "rationale", "system_prompt"):
            assert banned not in blob
        for uri in [r["uri"] for r in listed["resources"]]:
            body = json.dumps(await server.handle_resources_read({"uri": uri}))
            assert agent.backstory not in body
            assert agent.rationale not in body

    async def test_tool_catalog_is_policy_filtered(self, server):
        cat = _read_json(
            await server.handle_resources_read({"uri": "agent://finance/tools"})
        )
        assert "restricted_tool" not in cat["tools"]
        assert "public_tool" in cat["tools"]
        assert "forecast" in cat["tools"]

    async def test_tool_catalog_unfiltered_when_no_policy(self, agent):
        srv = StreamableHttpMCPServer(MCPServerConfig(name="test-agent-mcp-2"))
        register_agent_resources(srv, "finance", agent, exposure_names=["forecast"])
        cat = _read_json(
            await srv.handle_resources_read({"uri": "agent://finance/tools"})
        )
        assert "restricted_tool" in cat["tools"]

    async def test_kb_descriptors_from_knowledge_bases(self, server, agent):
        kbs = _read_json(
            await server.handle_resources_read({"uri": "agent://finance/kbs"})
        )
        assert len(kbs["knowledge_bases"]) == len(agent.knowledge_bases)
        assert {"finance-kb", "market-kb"} == {
            kb["name"] for kb in kbs["knowledge_bases"]
        }

    async def test_reregistration_overwrites_stale_agent_closures(self, server):
        """A rebuild (OQ5) must serve the new agent, not the old one."""
        new_agent = _FinanceAgent()
        new_agent.name = "finance"
        new_agent.role = "Reloaded Analyst"
        register_agent_resources(server, "finance", new_agent, exposure_names=["forecast"])
        card = _read_json(
            await server.handle_resources_read({"uri": "agent://finance/identity"})
        )
        assert card["role"] == "Reloaded Analyst"
