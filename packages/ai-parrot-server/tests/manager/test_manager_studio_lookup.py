"""FEAT-621 R2 / Q9 (AC9, AC17, AC18): a warm Studio cache is unreachable from every legacy path."""
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from parrot.bots.abstract import AbstractBot
from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioAgentKey,
    StudioPartition,
    StudioStorageUnavailable,
)
from parrot.handlers.studio.storage.services._common import (
    StudioClassAllowlist,
    StudioLimits,
    StudioToolingGate,
)
from parrot.handlers.studio.storage.services.agents import StudioAgentService
from parrot.handlers.studio.storage.services.tooling import StudioToolingService
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories
from parrot.auth.agent_guard import AgentAccessDenied
from parrot.manager import manager as manager_module
from parrot.manager.manager import AgentNotFoundError, BotManager
from parrot.manager.studio_builder import StudioAgentBuilder
from parrot.manager.studio_runtime import (
    StudioAgentRuntime,
    add_studio_runtime_hooks,
    install_studio_runtime,
    shutdown_studio_runtime,
)
from parrot.registry import agent_registry

ACME = StudioPartition("acme")
GLOBAL = StudioPartition.GLOBAL


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    monkeypatch.setattr(AbstractBot, "configure", AsyncMock())


class _Builder(StudioAgentBuilder):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.built: list = []

    async def build(self, snapshot, app, *, part):
        bot, directory = await super().build(snapshot, app, part=part)
        bot.cleanup = AsyncMock()
        self.built.append(bot)
        return bot, directory


def _manager() -> BotManager:
    return BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                      enable_swagger_api=False)


async def _with_studio(tmp_path):
    """A manager with an installed runtime over the in-memory repositories and two agents in the store."""
    repos = InMemoryStudioRepositories()
    gate = StudioToolingGate({})
    agents = StudioAgentService(repos, limits=StudioLimits(), class_allowlist=StudioClassAllowlist(),
                                tooling=StudioToolingService(repos, gate=gate), tooling_gate=gate)
    await agents.create(ACME, name="sales", owner="u1", definition=StudioAgentDefinition())
    await agents.create(GLOBAL, name="helper", owner="u1", definition=StudioAgentDefinition())
    manager = _manager()
    builder = _Builder(agent_registry, tmp_path / "rt", gate)
    manager.studio = StudioAgentRuntime(manager, repos, builder)
    return manager, builder


async def test_warm_cache_unreachable_from_legacy(tmp_path):
    manager, builder = await _with_studio(tmp_path)
    runtime = manager.studio
    acme = StudioAgentKey("acme", "sales")
    base = await manager.get_studio_bot(acme)
    session = await manager.get_studio_bot(acme, new=True, session_id="t1")
    helper_key = StudioAgentKey(None, "helper")
    global_base = await manager.get_studio_bot(helper_key)
    assert len(builder.built) == 3 and base is not session
    legacy_before = (dict(manager._bots), dict(manager._botdef), dict(manager._bot_expiration))
    for name in (acme.qualified, f"{acme.qualified}_t1", "studio:acme:sales_abcd", f"studio-agent:{base._studio_agent_id}"):
        for new in (False, True):
            assert await manager.get_bot(name, new=new, session_id="t1") is None, (name, new)
    assert await manager.get_bot("sales") is None                                  # a tenant row is unreachable by name
    assert (manager._bots, manager._botdef, manager._bot_expiration) == legacy_before
    # legacy ``new=True`` on a bare name builds its own default instance (unchanged behaviour); it is never a Studio one
    legacy_clone = await manager.get_bot("sales", new=True, session_id="t1")
    assert legacy_clone is not None and getattr(legacy_clone, "_studio_key", None) is None
    assert legacy_clone not in builder.built and len(builder.built) == 3
    assert not any(getattr(b, "_studio_key", None) is not None for b in manager.get_bots().values())
    assert base not in manager.get_bots().values() and global_base not in manager.get_bots().values()
    with pytest.raises(AgentNotFoundError):
        await manager.reload_agent("sales")
    legacy_clone.cleanup = AsyncMock()
    await manager._cleanup_all_bots(web.Application())
    assert legacy_clone.cleanup.await_count == 1                                   # the legacy sweep ran...
    assert all(b.cleanup.await_count == 0 for b in builder.built)                 # ...and never saw a Studio instance
    assert await runtime.get(acme) is base                                         # still warm and served
    # the one additive fallback: a GLOBAL agent by bare name, served from the Studio cache, never added to _bots
    assert await manager.get_bot("helper") is global_base and "helper" not in manager._bots
    assert "helper" not in manager._botdef and len(builder.built) == 3


async def test_get_bot_global_fallback(tmp_path):
    manager, builder = await _with_studio(tmp_path)
    assert await manager.get_bot("helper") is not None                             # plain host: bare name works
    assert await manager.get_bot("nope") is None
    assert await manager.get_bot("sales") is None                                  # a tenant row is unreachable by name
    cloned = await manager.get_bot("helper", new=True, session_id="s")             # new=True never consults the cache
    assert getattr(cloned, "_studio_key", None) is None and cloned not in builder.built and len(builder.built) == 1
    manager.app = web.Application()
    manager.app["scope_resolver"] = object()                                       # an opted-in host: no fallback
    assert await manager.get_bot("helper") is None
    del manager.app["scope_resolver"]
    manager.app["ui_surfaces_scope_resolver"] = object()                           # the legacy key counts too
    assert await manager.get_bot("helper") is None


async def test_fallback_needs_the_runtime():
    manager = _manager()
    assert manager.studio is None and await manager.get_bot("helper") is None


async def test_fallback_refused_build_is_not_served(tmp_path, monkeypatch):
    manager, _ = await _with_studio(tmp_path)
    monkeypatch.setattr(manager.studio, "get", AsyncMock(side_effect=RuntimeError("build exploded")))
    assert await manager.get_bot("helper") is None


async def test_get_studio_bot_pbac_before_build(tmp_path, monkeypatch):
    manager, builder = await _with_studio(tmp_path)
    denied = AsyncMock(side_effect=AgentAccessDenied("no"))
    monkeypatch.setattr(manager_module, "enforce_agent_access", denied)
    key = StudioAgentKey("acme", "sales")
    with pytest.raises(AgentAccessDenied):
        await manager.get_studio_bot(key, new=True, session_id="t1")
    assert builder.built == [] and denied.await_args.args[1] == key.qualified      # refused BEFORE any build
    with pytest.raises(AgentAccessDenied):
        await manager.get_studio_bot(key)                                           # base: checked on the result
    monkeypatch.setattr(manager_module, "enforce_agent_access", AsyncMock())
    assert await manager.get_studio_bot(StudioAgentKey("acme", "missing")) is None


async def test_get_studio_bot_contract(tmp_path):
    manager, _ = await _with_studio(tmp_path)
    with pytest.raises(ValueError):
        await manager.get_studio_bot(StudioAgentKey("acme", "sales"), new=True)     # a session needs an id
    bare = _manager()
    with pytest.raises(StudioStorageUnavailable):
        await bare.get_studio_bot(StudioAgentKey("acme", "sales"))


def test_setup_registers_hooks_once():
    app, manager = web.Application(), _manager()
    manager.setup(app, studio_routes=False)
    assert app.on_startup.count(install_studio_runtime) == 1 and app.on_cleanup.count(shutdown_studio_runtime) == 1
    add_studio_runtime_hooks(app)                                                  # a second caller adds nothing
    assert app.on_startup.count(install_studio_runtime) == 1 and app.on_cleanup.count(shutdown_studio_runtime) == 1
    assert manager.studio is None                                                  # nothing is built at setup time


def test_load_database_bots_is_untouched():
    import inspect

    source = inspect.getsource(BotManager._load_database_bots)
    assert "studio" not in source.lower() and "ai_agents" not in source


async def test_fallback_enforces_pbac_on_the_bare_name(tmp_path, monkeypatch):
    manager, _ = await _with_studio(tmp_path)
    denied = AsyncMock(side_effect=AgentAccessDenied("no"))
    monkeypatch.setattr(manager_module, "enforce_agent_access", denied)
    with pytest.raises(AgentAccessDenied):
        await manager.get_bot("helper", request=object())
    assert denied.await_args.args[1] == "helper"
