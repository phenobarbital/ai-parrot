"""Build-hook plumbing for the tenant tooling policy (FEAT-622 M7, RC-9)."""
import asyncio
import logging
from uuid import uuid4

import pytest

from parrot.interfaces.tools import ToolInterface
from parrot.tools.manager import ToolManager
from parrot.tools.spec import AgentMCPServerSpec
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
