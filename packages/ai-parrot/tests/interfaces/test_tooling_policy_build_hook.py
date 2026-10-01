"""Build-hook plumbing for the tenant tooling policy (FEAT-622 M7, RC-9)."""
import asyncio
import logging
from uuid import uuid4

import pytest

from parrot.interfaces.tools import ToolInterface
from parrot.tools.manager import ToolManager
import parrot.tools.spec as spec_module
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec
from parrot.tools.tooling_policy import TenantToolingPolicy, ToolingSubject


class _Bot(ToolInterface):
    """ToolInterface host backed by a real ToolManager (as in test_apply_tooling_specs)."""

    def __init__(self):
        self.logger = logging.getLogger("test_tooling_policy_build_hook")
        self.tool_manager = ToolManager()
        self.added: list[object] = []
        self._pending_mcp_specs = [
            AgentMCPServerSpec(name="evil", transport="stdio", command="/bin/sh", args=["-c", "x"])
        ]

    async def add_mcp_server(self, config):
        """Record the connection attempt (would spawn the stdio process)."""
        self.added.append(config)
        return []


def _subject(tenant="acme") -> ToolingSubject:
    return ToolingSubject(tenant=tenant, agent_id=uuid4(), actor=None, phase="build")


@pytest.fixture
def spawns(monkeypatch):
    """Counter of process spawns; any call is also a failure signal."""
    calls: list[tuple] = []

    async def _spawn(*args, **kwargs):
        calls.append(args)
        raise AssertionError("subprocess must not start")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    return calls


@pytest.mark.asyncio
async def test_bind_tooling_policy_reaches_configure(spawns, caplog):
    """The no-argument call configure() makes honours the bound policy; stdio spec never connects."""
    bot = _Bot()
    bot.bind_tooling_policy(TenantToolingPolicy.deny_all(), _subject())
    with caplog.at_level(logging.ERROR, logger="test_tooling_policy_build_hook"):
        assert await bot.apply_tooling_specs() == []  # exactly the call at bots/abstract.py:1524
    assert bot.added == [] and spawns == []
    assert any("local_execution" in r.getMessage() for r in caplog.records)
    with pytest.raises(RuntimeError):
        bot.bind_tooling_policy(None, _subject())


@pytest.mark.asyncio
async def test_tenant_subject_without_policy_is_deny_all(spawns):
    """A tenant subject and no policy behaves as deny_all()."""
    bot = _Bot()
    await bot.apply_tooling_specs(tooling_subject=_subject())
    assert bot.added == []


@pytest.mark.asyncio
async def test_explicit_kwargs_win_over_binding():
    """Explicit policy kwarg overrides the bound one (permissive explicit policy lets a clean spec through)."""
    bot = _Bot()
    bot._pending_mcp_specs = [AgentMCPServerSpec(name="ok", url="https://mcp.host/api/x")]
    bot.bind_tooling_policy(TenantToolingPolicy.deny_all(), _subject())
    await bot.apply_tooling_specs(tooling_policy=TenantToolingPolicy(mcp_endpoints=("https://mcp.host/api/",)))
    assert len(bot.added) == 1


@pytest.mark.asyncio
async def test_unbound_bot_builds_as_today():
    """No subject / policy: nothing is policed."""
    bot = _Bot()
    await bot.apply_tooling_specs()
    assert len(bot.added) == 1


@pytest.mark.asyncio
async def test_bound_policy_is_used_when_no_kwargs():
    """A bound permissive policy (not deny_all) is honoured: distinguishes binding from the deny_all default."""
    bot = _Bot()
    bot._pending_mcp_specs = [AgentMCPServerSpec(name="ok", url="https://mcp.host/api/x")]
    bot.bind_tooling_policy(TenantToolingPolicy(mcp_endpoints=("https://mcp.host/api/",)), _subject())
    await bot.apply_tooling_specs()
    assert len(bot.added) == 1


class _RealBot(ToolInterface):
    """Concrete bot: add_mcp_server goes through the real ToolManager / MCPClient path."""

    def __init__(self, specs):
        self.logger = logging.getLogger("test_tooling_policy_build_hook")
        self.tool_manager = ToolManager()
        self._pending_mcp_specs = specs

    async def add_mcp_server(self, config):
        """Real connection path (what AbstractBot/Agent do)."""
        return await self.tool_manager.add_mcp_server(config)


@pytest.mark.asyncio
async def test_real_add_mcp_server_path_never_spawns(monkeypatch):
    """Denied stdio spec (explicit and params-smuggled) reaches neither add_mcp_server nor a subprocess."""
    spawns: list[tuple] = []

    async def _spawn(*args, **kwargs):
        spawns.append(args)
        raise OSError("blocked")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    connects: list[object] = []
    bot = _RealBot([
        AgentMCPServerSpec(name="a", transport="stdio", command="/bin/sh", args=["-c", "x"]),
        AgentMCPServerSpec(name="b", url="https://mcp.host/api/x", params={"transport": "stdio", "command": "sh"}),
    ])
    orig = bot.tool_manager.add_mcp_server

    async def _spy(config, *a, **k):
        connects.append(config)
        return await orig(config, *a, **k)

    monkeypatch.setattr(bot.tool_manager, "add_mcp_server", _spy)
    bot.bind_tooling_policy(TenantToolingPolicy(mcp_endpoints=("https://mcp.host/api/",)), _subject())
    assert await bot.apply_tooling_specs() == []
    assert connects == [] and spawns == []


@pytest.fixture
def vault_reads(monkeypatch):
    """Counter of vault reads (hydrate_params / hydrate_mcp go through this symbol)."""
    reads: list[tuple] = []

    async def _vault(owner, name):
        reads.append((owner, name))
        return {"headers": {"a": "b"}, "token": "t"}

    monkeypatch.setattr(spec_module, "retrieve_vault_credential", _vault)
    return reads


@pytest.mark.asyncio
async def test_build_refuses_foreign_vault_name_without_vault_read(vault_reads, caplog):
    """Foreign vault name / wrong owner at build: toolkit and MCP specs refused, zero vault reads."""
    agent_id = uuid4()
    subject = ToolingSubject(tenant="acme", agent_id=agent_id, actor=None, phase="build")
    bot = _RealBot([AgentMCPServerSpec(
        name="m", url="https://mcp.host/api/x", secret_refs={"headers": "mcp_agent_m_studio-agent:OTHER"},
        vault_owner="u1",
    )])
    bot._pending_toolkit_specs = [ToolkitSpec(
        slug="wiki", secret_refs={"token": "toolkit_wiki_studio-agent:OTHER"}, vault_owner="u1"
    )]
    policy = TenantToolingPolicy(mcp_endpoints=("https://mcp.host/api/",), builtin_tools=frozenset({"wiki"}))
    with caplog.at_level(logging.ERROR, logger="test_tooling_policy_build_hook"):
        assert await bot.apply_tooling_specs(tooling_policy=policy, tooling_subject=subject, tooling_owner="u1") == []
    assert vault_reads == []
    assert sum("secret_ref_not_permitted" in r.getMessage() for r in caplog.records) == 2


@pytest.mark.asyncio
async def test_build_accepts_own_vault_name_and_owner(vault_reads):
    """Control: the agent's own namespace and matching owner pass the build check and read the vault."""
    agent_id = uuid4()
    subject = ToolingSubject(tenant="acme", agent_id=agent_id, actor=None, phase="build")
    bot = _Bot()
    bot._pending_mcp_specs = [AgentMCPServerSpec(
        name="m", url="https://mcp.host/api/x",
        secret_refs={"headers": f"mcp_agent_m_studio-agent:{agent_id}"}, vault_owner="u1",
    )]
    policy = TenantToolingPolicy(mcp_endpoints=("https://mcp.host/api/",))
    await bot.apply_tooling_specs(tooling_policy=policy, tooling_subject=subject, tooling_owner="u1")
    assert len(bot.added) == 1 and len(vault_reads) == 1


@pytest.mark.asyncio
async def test_refused_spec_performs_zero_vault_reads(vault_reads):
    """A stdio spec with VALID own-namespace secret_refs is refused by the pre-check, before any vault read."""
    agent_id = uuid4()
    subject = ToolingSubject(tenant="acme", agent_id=agent_id, actor=None, phase="build")
    bot = _Bot()
    bot._pending_mcp_specs = [AgentMCPServerSpec(
        name="e", transport="stdio", command="sh",
        secret_refs={"headers": f"mcp_agent_e_studio-agent:{agent_id}"}, vault_owner="u1",
    )]
    await bot.apply_tooling_specs(
        tooling_policy=TenantToolingPolicy.deny_all(), tooling_subject=subject, tooling_owner="u1"
    )
    assert vault_reads == [] and bot.added == []
