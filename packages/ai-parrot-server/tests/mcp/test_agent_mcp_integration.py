"""Integration tests closing the loop across FEAT-477's modules (TASK-2610).

Per spec §5 "Deferred evidence": the API-key path is the first vertical
slice — no navigator-auth dependency, demonstrated end-to-end here at
merge time. The OAuth path is tested with the introspection and PRM legs
**mocked**; a live conformance run against a real navigator-auth deployment
is a post-release gate, not a merge blocker.
"""

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from parrot.a2a.server import A2AServer
from parrot.mcp.agent_mount import AgentMCPMount
from parrot.mcp.agent_tools import mcp_tool
from parrot.mcp.config import AgentMCPMountConfig, AuthMethod, MCPServerConfig
from parrot.mcp.oauth_server import APIKeyStore, ExternalOAuthValidator
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer
from pydantic import BaseModel


class Args(BaseModel):
    q: str


class Ret(BaseModel):
    ok: bool


class _FakeToolManager:
    def __init__(self, tools: dict | None = None):
        self._tools = tools or {}

    def list_tools(self) -> list[str]:
        return list(self._tools)

    def get_tool(self, name: str):
        return self._tools.get(name)


class _FinanceAgent:
    name = "finance"

    def __init__(self):
        self.tool_manager = _FakeToolManager({})

    @mcp_tool(name="forecast", description="d", args_schema=Args, returns=Ret, scope="finance:read")
    async def forecast(self, q: str) -> dict:
        return {"forecast": q}


class _HRAgent:
    name = "hr"

    def __init__(self):
        self.tool_manager = _FakeToolManager({})

    @mcp_tool(name="roster", description="d", args_schema=Args, returns=Ret, scope="hr:read")
    async def roster(self, q: str) -> dict:
        return {"roster": q}


class _FakeBotManager:
    def __init__(self, bots: dict):
        self._bots = bots

    def get_bots(self) -> dict:
        return dict(self._bots)


async def _allow_all(pctx, resource: str, required_permissions) -> bool:
    """Permissive PBAC resolver: allow every call for any authenticated principal."""
    return True


_INIT_REQ = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
_LIST_REQ = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _call_req(name: str, arguments: dict, req_id: int = 3) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


class TestAgentMCPIntegration:
    async def test_api_key_end_to_end(self):
        """Claude Code path: API key -> initialize -> tools/list -> tools/call
        -> audited result. No navigator-auth dependency.
        """
        api_key_store = APIKeyStore()
        record = api_key_store.issue_key(user_id="dev-user")

        auth_template = MCPServerConfig(auth_method=AuthMethod.API_KEY, api_key_store=api_key_store)
        bot_manager = _FakeBotManager({"finance": _FinanceAgent()})
        cfg = AgentMCPMountConfig(
            agents=["finance"],
            resource_server_url="https://h/mcp/agents/finance",
            default_tenant_id="acme",
        )
        mount = AgentMCPMount(bot_manager, cfg, pbac_resolver=_allow_all, auth_template=auth_template)
        app = web.Application()
        mount.setup(app)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            headers = {"X-API-Key": record.key}
            r = await client.post("/mcp/agents/finance", json=_INIT_REQ, headers=headers)
            assert r.status == 200

            listed = await (await client.post("/mcp/agents/finance", json=_LIST_REQ, headers=headers)).json()
            assert "forecast" in [t["name"] for t in listed["result"]["tools"]]

            called = await (
                await client.post(
                    "/mcp/agents/finance",
                    json=_call_req("forecast", {"q": "x"}),
                    headers=headers,
                )
            ).json()
            assert called["result"]["isError"] is False
        finally:
            await client.close()

    async def test_api_key_rejected_without_key(self):
        """No navigator-auth dependency — a missing API key is a clean 401."""
        api_key_store = APIKeyStore()
        auth_template = MCPServerConfig(auth_method=AuthMethod.API_KEY, api_key_store=api_key_store)
        bot_manager = _FakeBotManager({"finance": _FinanceAgent()})
        cfg = AgentMCPMountConfig(
            agents=["finance"],
            resource_server_url="https://h/mcp/agents/finance",
            default_tenant_id="acme",
        )
        mount = AgentMCPMount(bot_manager, cfg, pbac_resolver=_allow_all, auth_template=auth_template)
        app = web.Application()
        mount.setup(app)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.post("/mcp/agents/finance", json=_INIT_REQ)
            assert r.status == 401
        finally:
            await client.close()

    async def test_oauth_end_to_end_mocked(self, monkeypatch):
        """Discovery -> 401 challenge -> token -> filtered list -> call, with
        introspection and PRM mocked.
        """
        auth_template = MCPServerConfig(
            auth_method=AuthMethod.OAUTH2_EXTERNAL,
            oauth2_introspection_endpoint="https://auth.example.com/introspect",
            oauth2_client_id="claude-client",
            oauth2_client_secret="secret",
            oauth2_issuer_url="https://auth.example.com",
        )
        bot_manager = _FakeBotManager({"finance": _FinanceAgent()})
        cfg = AgentMCPMountConfig(
            agents=["finance"],
            resource_server_url="https://h/mcp/agents/finance",
            default_tenant_id="acme",
        )
        mount = AgentMCPMount(bot_manager, cfg, pbac_resolver=_allow_all, auth_template=auth_template)
        app = web.Application()
        mount.setup(app)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            # 1. No token -> 401 with a resource_metadata challenge (RFC 9728, G4).
            r = await client.post("/mcp/agents/finance", json=_INIT_REQ)
            assert r.status == 401
            assert "resource_metadata=" in r.headers["WWW-Authenticate"]

            # 2. Mock introspection (TASK-2610: navigator-auth is not
            # reachable from CI — mock the introspection leg).
            async def fake_get_token_info(self, token):
                return {
                    "active": True,
                    "sub": "oauth-user",
                    "aud": ["https://h/mcp/agents/finance"],
                    "scope": "mcp:access",
                }

            monkeypatch.setattr(ExternalOAuthValidator, "get_token_info", fake_get_token_info)
            headers = {"Authorization": "Bearer valid-token"}

            r = await client.post("/mcp/agents/finance", json=_INIT_REQ, headers=headers)
            assert r.status == 200

            listed = await (await client.post("/mcp/agents/finance", json=_LIST_REQ, headers=headers)).json()
            assert "forecast" in [t["name"] for t in listed["result"]["tools"]]

            called = await (
                await client.post(
                    "/mcp/agents/finance",
                    json=_call_req("forecast", {"q": "x"}),
                    headers=headers,
                )
            ).json()
            assert called["result"]["isError"] is False
        finally:
            await client.close()

    async def test_agent_isolation_across_mounts(self, monkeypatch):
        """A token scoped (via `aud`) to the finance mount cannot call the
        HR mount (G3) — audience enforcement is the only place per-agent
        authorization can happen against navigator-auth's upstream gate.
        """
        finance_bot_manager = _FakeBotManager({"finance": _FinanceAgent()})
        hr_bot_manager = _FakeBotManager({"hr": _HRAgent()})

        finance_cfg = AgentMCPMountConfig(
            agents=["finance"],
            resource_server_url="https://h/mcp/agents/finance",
            default_tenant_id="acme",
        )
        hr_cfg = AgentMCPMountConfig(
            agents=["hr"],
            resource_server_url="https://h/mcp/agents/hr",
            default_tenant_id="acme",
        )
        auth_template = MCPServerConfig(
            auth_method=AuthMethod.OAUTH2_EXTERNAL,
            oauth2_introspection_endpoint="https://auth.example.com/introspect",
            oauth2_client_id="claude-client",
            oauth2_client_secret="secret",
            oauth2_issuer_url="https://auth.example.com",
        )
        finance_mount = AgentMCPMount(
            finance_bot_manager, finance_cfg, pbac_resolver=_allow_all, auth_template=auth_template
        )
        hr_mount = AgentMCPMount(hr_bot_manager, hr_cfg, pbac_resolver=_allow_all, auth_template=auth_template)
        app = web.Application()
        finance_mount.setup(app)
        hr_mount.setup(app)

        async def fake_get_token_info(self, token):
            # Token is scoped to finance only.
            return {
                "active": True,
                "sub": "oauth-user",
                "aud": ["https://h/mcp/agents/finance"],
                "scope": "mcp:access",
            }

        monkeypatch.setattr(ExternalOAuthValidator, "get_token_info", fake_get_token_info)
        headers = {"Authorization": "Bearer token-for-finance"}

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            ok = await client.post("/mcp/agents/finance", json=_INIT_REQ, headers=headers)
            assert ok.status == 200

            denied = await client.post("/mcp/agents/hr", json=_call_req("roster", {"q": "x"}), headers=headers)
            assert denied.status == 401
        finally:
            await client.close()

    async def test_no_regression_tool_level_server(self):
        """G11 — the existing tool-level MCP server behaves unchanged."""
        from parrot.tools.abstract import AbstractTool

        class EchoTool(AbstractTool):
            name = "echo"
            description = "Echo input back"
            args_schema = Args

            async def _execute(self, q: str) -> str:
                return q

        config = MCPServerConfig(name="tool-level")
        app = web.Application()
        server = StreamableHttpMCPServer(config, parent_app=app)
        server.register_tool(EchoTool())
        server._register_routes(app.router, config.base_path)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.post("/mcp", json=_INIT_REQ)
            assert r.status == 200
        finally:
            await client.close()

    def test_a2a_agent_card_includes_decorated_methods(self):
        """The reification side effect: decorated methods appear as
        `AgentCard` skills, even though they are never in `tool_manager`
        (OQ2).
        """
        agent = _FinanceAgent()
        a2a_server = A2AServer(agent)
        card = a2a_server.get_agent_card()
        assert "forecast" in [s.id for s in card.skills]
