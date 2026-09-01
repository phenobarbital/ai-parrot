"""Unit tests for `AgentMCPMount` (FEAT-477, TASK-2602)."""

import pytest
from aiohttp import web
from parrot.mcp.agent_mount import AgentMCPMount
from parrot.mcp.agent_tools import mcp_tool
from parrot.mcp.config import AgentMCPMountConfig, MCPServerConfig, TransportConfig
from parrot.mcp.parrot_server import ParrotMCPServer
from parrot.tools.abstract import AbstractTool
from pydantic import BaseModel


class Args(BaseModel):
    q: str


class Ret(BaseModel):
    ok: bool


class _ToJsonTool(AbstractTool):
    """Internal plumbing tool that must never be exposed over MCP."""

    name = "to_json"
    description = "internal"
    args_schema = Args

    async def _execute(self, q: str = "") -> dict:
        return {"q": q}


class _OrdinaryTool(AbstractTool):
    """A normal tool_manager tool, distinct from an `@mcp_tool` method."""

    name = "lookup"
    description = "an ordinary tool"
    args_schema = Args

    async def _execute(self, q: str) -> dict:
        return {"looked_up": q}


class _FakeToolManager:
    """Duck-typed stand-in for `ToolManager`."""

    def __init__(self, tools: list[AbstractTool] | None = None):
        self._tools = {t.name: t for t in (tools or [])}

    def list_tools(self) -> list[str]:
        return list(self._tools)

    def get_tool(self, name: str):
        return self._tools.get(name)


class _FinanceAgent:
    """An agent with one `@mcp_tool` method plus ordinary/internal tools."""

    name = "finance"

    def __init__(self):
        self.tool_manager = _FakeToolManager([_ToJsonTool(), _OrdinaryTool()])

    @mcp_tool(name="forecast", description="d", args_schema=Args, returns=Ret, scope="finance:read")
    async def forecast(self, q: str) -> dict:
        return {"forecast": q}


class _FakeBotManager:
    """Duck-typed stand-in for `BotManager` (`get_bots` + `reload_agent`)."""

    def __init__(self, bots: dict):
        self._bots = bots

    def get_bots(self) -> dict:
        return dict(self._bots)

    async def reload_agent(self, name: str):
        self._bots[name] = _FinanceAgent()
        return self._bots[name]


@pytest.fixture
def app() -> web.Application:
    return web.Application()


@pytest.fixture
def bot_manager() -> _FakeBotManager:
    return _FakeBotManager({"finance": _FinanceAgent()})


@pytest.fixture
def cfg() -> AgentMCPMountConfig:
    return AgentMCPMountConfig(agents=["finance"], resource_server_url="https://h/mcp/agents")


@pytest.fixture
def cfg_agg() -> AgentMCPMountConfig:
    return AgentMCPMountConfig(
        agents=["finance"],
        resource_server_url="https://h/mcp/agents",
        aggregate_enabled=True,
    )


@pytest.fixture
def cfg_bad_name() -> AgentMCPMountConfig:
    # `AgentMCPMountConfig` itself already rejects `__` at construction time
    # (TASK-2601's field_validator). `model_construct()` bypasses validation
    # to exercise `AgentMCPMount`'s own defense-in-depth check at mount time
    # (this task's own acceptance criterion), simulating a config that
    # reached the mount without going through normal validation.
    return AgentMCPMountConfig.model_construct(agents=["fin__ance"], resource_server_url="https://h/mcp/agents")


@pytest.fixture
def mount(app, bot_manager, cfg) -> AgentMCPMount:
    m = AgentMCPMount(bot_manager, cfg)
    m.setup(app)
    return m


class TestAgentMCPMount:
    def test_creates_per_agent_endpoint(self, app, bot_manager, cfg):
        AgentMCPMount(bot_manager, cfg).setup(app)
        paths = {r.resource.canonical for r in app.router.routes() if r.resource is not None}
        assert any("/mcp/agents/finance" in p for p in paths)

    def test_registers_exposure_set_and_own_tools(self, mount):
        names = set(mount._servers["finance"].tools)
        assert "forecast" in names
        assert "lookup" in names
        assert "to_json" not in names

    def test_aggregate_prefix(self, app, bot_manager, cfg_agg):
        m = AgentMCPMount(bot_manager, cfg_agg)
        m.setup(app)
        assert "finance__forecast" in m._servers["__aggregate__"].tools
        assert "finance__lookup" in m._servers["__aggregate__"].tools
        assert "finance__to_json" not in m._servers["__aggregate__"].tools

    def test_both_forms_same_pbac_resource(self, mount):
        assert mount.canonical_resource("finance", "forecast") == mount.canonical_resource_from_aggregate(
            "finance__forecast"
        )

    def test_rejects_separator_in_agent_name(self, app, bot_manager, cfg_bad_name):
        with pytest.raises(ValueError, match="__"):
            AgentMCPMount(bot_manager, cfg_bad_name).setup(app)

    def test_rejects_base_path_collision_with_configured_transport(self, app, bot_manager, cfg_agg):
        """The aggregate's fixed `/mcp` collides with the tool-level server's default."""
        parrot_mcp = ParrotMCPServer(transports={"streamable-http": TransportConfig(transport="streamable-http")})
        parrot_mcp.setup(app)
        assert app["parrot_mcp_server"] is parrot_mcp
        with pytest.raises(ValueError, match="collides"):
            AgentMCPMount(bot_manager, cfg_agg).setup(app)

    async def test_mount_resolves_agent_by_name_per_call(self, mount, bot_manager):
        """OQ5 — a reloaded agent must be picked up, not a stale cached object."""
        old = bot_manager.get_bots()["finance"]
        await bot_manager.reload_agent("finance")
        resolved = mount._resolve("finance")
        assert resolved is not old
        # The rebuilt server still serves the (new instance's) exposure set.
        assert "forecast" in mount._servers["finance"].tools

    def test_no_regression_tool_level_server(self, app):
        """G11 — the existing tool-level MCP server still mounts and responds."""
        parrot_mcp = ParrotMCPServer(transports={"streamable-http": TransportConfig(transport="streamable-http")})
        parrot_mcp.setup(app)
        assert app["parrot_mcp_server"] is parrot_mcp
        assert MCPServerConfig().base_path == "/mcp"

    def test_no_declared_agents_registers_nothing(self, app, bot_manager):
        empty_cfg = AgentMCPMountConfig(agents=[], resource_server_url="https://h/x")
        AgentMCPMount(bot_manager, empty_cfg).setup(app)
        assert not any("/mcp/agents/" in (r.resource.canonical if r.resource else "") for r in app.router.routes())
