"""FEAT-621 M7 runtime (AC5, AC10, AC11, AC14). Same code on the in-memory repositories and on real Postgres.

``AbstractBot.configure`` is replaced (these tests are about lookup/lifecycle, not LLM start-up) and every built
instance gets an ``AsyncMock`` ``cleanup`` so clean-up counts are observable.
"""
import asyncio
import logging
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from asyncdb import AsyncPool

from parrot.auth.agent_guard import AgentAccessDenied
from parrot.bots.abstract import AbstractBot
from parrot.handlers.studio.storage.migrate import apply_studio_migrations
from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioAgentKey,
    StudioAgentPatch,
    StudioAssetInput,
    StudioModelParams,
    StudioNotFound,
    StudioPartition,
    StudioToolingRefused,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories, studio_transaction
from parrot.handlers.studio.storage.services._common import (
    StudioClassAllowlist,
    StudioLimits,
    StudioToolingGate,
)
from parrot.handlers.studio.storage.services.agents import StudioAgentService
from parrot.handlers.studio.storage.services.tooling import StudioToolingService
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories
from parrot.manager import studio_runtime as runtime_module
from parrot.manager.manager import AgentNotFoundError
from parrot.manager.studio_builder import StudioAgentBuilder
from parrot.manager.studio_runtime import (
    StudioAgentRuntime,
    add_studio_runtime_hooks,
    install_studio_runtime,
    shutdown_studio_runtime,
)
from parrot.registry import agent_registry

ACME = StudioPartition("acme")
BETA = StudioPartition("beta")
GLOBAL = StudioPartition.GLOBAL
NO_GUARD = StudioWriteGuard()
GRACE, SESSION_TTL, IDLE_TTL = 300.0, 3600.0, 3600.0


@pytest.fixture
async def studio_pool():
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; Studio runtime integration tests need Postgres")
    pool = AsyncPool("pg", dsn=dsn)
    await pool.connect()
    await apply_studio_migrations(pool)
    yield pool
    async with pool.acquire() as conn:
        for table in ("ai_agent_assets", "ai_agent_tooling", "ai_agent_drafts", "ai_agents", "ai_skills_catalog"):
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")
    await pool.close()


@pytest.fixture(params=["memory", "postgres"])
def repos(request):
    if request.param == "memory":
        return InMemoryStudioRepositories()
    return build_studio_repositories(request.getfixturevalue("studio_pool"))


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(AbstractBot, "configure", mock)
    return mock


class _Builder(StudioAgentBuilder):
    """The real builder, counting builds and giving each instance an observable ``cleanup``."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.built: list = []

    async def build(self, snapshot, app, *, part):
        bot, directory = await super().build(snapshot, app, part=part)
        bot.cleanup = AsyncMock()
        self.built.append(bot)
        await asyncio.sleep(0)                # a real build yields; makes the single-flight test meaningful
        return bot, directory


def _runtime(repos, tmp_path, **kw):
    manager = SimpleNamespace(registry=SimpleNamespace(evaluator=None), app=web.Application())
    builder = _Builder(agent_registry, tmp_path / "rt", StudioToolingGate(manager.app))
    return StudioAgentRuntime(manager, repos, builder, **kw), builder


def _service(repos):
    gate = StudioToolingGate({})
    return StudioAgentService(
        repos, limits=StudioLimits(), class_allowlist=StudioClassAllowlist(),
        tooling=StudioToolingService(repos, gate=gate), tooling_gate=gate,
    )


async def _create(repos, part=GLOBAL, name="a1", **definition):
    return await _service(repos).create(part, name=name, owner="u1", definition=StudioAgentDefinition(**definition))


def _key(part=GLOBAL, name="a1"):
    return StudioAgentKey(part.tenant, name)


async def _patch(repos, part=GLOBAL, name="a1", **fields):
    return await _service(repos).patch(part, name, StudioAgentPatch(**fields), guard=NO_GUARD)


async def test_get_builds_once_and_reuses_until_the_version_moves(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    assert await rt.get(_key()) is None                                   # unknown agent
    rec = await _create(repos, description="v1")
    first = await rt.get(_key())
    assert first is await rt.get(_key()) and len(builder.built) == 1
    assert (first._studio_agent_id, first.description) == (rec.agent_id, "v1")
    await _patch(repos, description="v2")
    second = await rt.get(_key())
    assert second is not first and second.description == "v2" and len(builder.built) == 2
    assert first.cleanup.await_count == 0                                  # retired, never cleaned on the spot


async def test_single_flight_rebuild(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos)
    bots = await asyncio.gather(*(rt.get(_key()) for _ in range(20)))
    assert len(builder.built) == 1 and all(b is bots[0] for b in bots)


async def test_cross_pod_revalidation(studio_pool, tmp_path):
    repos = build_studio_repositories(studio_pool)
    pod_a, _ = _runtime(repos, tmp_path / "a")
    pod_b, _ = _runtime(repos, tmp_path / "b")
    await _create(repos, description="v1", model_params=StudioModelParams(temperature=0.3))
    a1, b1 = await pod_a.get(_key()), await pod_b.get(_key())
    assert a1._llm_kwargs["temperature"] == b1._llm_kwargs["temperature"] == 0.3 and a1 is not b1
    await _patch(repos, description="v2", model_params=StudioModelParams(temperature=0.7))        # a write on any pod
    a2, b2 = await pod_a.get(_key()), await pod_b.get(_key())
    assert a2.description == b2.description == "v2"
    assert a2._llm_kwargs["temperature"] == b2._llm_kwargs["temperature"] == 0.7
    assert a2._studio_version == b2._studio_version > a1._studio_version


async def test_snapshot_during_edit(studio_pool, tmp_path):
    """Definition and children always come from one committed state, even under concurrent edits."""
    repos = build_studio_repositories(studio_pool)
    rt, _ = _runtime(repos, tmp_path)
    svc = _service(repos)
    await svc.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition(description="v0"),
                     assets=[StudioAssetInput(kind="identity", name="role.md", content="role v0")])
    stop = asyncio.Event()

    async def writer():
        n = 0
        while not stop.is_set():
            n += 1
            async with studio_transaction(repos.pool) as conn:       # one transaction: both move together
                head = await repos.agents.lock(conn, GLOBAL, "a1", NO_GUARD)
                await repos.agents.update_definition(conn, GLOBAL, "a1", StudioAgentDefinition(description=f"v{n}"))
                await repos.assets.put(conn, head.agent_id, StudioAssetInput(kind="identity", name="role.md",
                                                                           content=f"role v{n}"), sha256="0" * 64)
            await asyncio.sleep(0)

    task = asyncio.create_task(writer())
    try:
        for _ in range(40):
            await rt.reload(_key())
            bot = await rt.get(_key())
            assert bot.role == bot.description.replace("v", "role v", 1), (bot.description, bot.role)
    finally:
        stop.set()
        await task


async def test_memory_partitioned_by_agent_id(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    acme, beta = await _create(repos, ACME, "sales"), await _create(repos, BETA, "sales")
    a, b = await rt.get(_key(ACME, "sales")), await rt.get(_key(BETA, "sales"))
    assert a.memory_key_id == str(acme.agent_id) != b.memory_key_id == str(beta.agent_id)
    await _service(repos).delete(ACME, "sales", guard=NO_GUARD)
    recreated = await _create(repos, ACME, "sales")
    again = await rt.get(_key(ACME, "sales"))
    assert again is not a and again.memory_key_id == str(recreated.agent_id) != a.memory_key_id
    assert a._studio_key == again._studio_key == _key(ACME, "sales")      # same name, different identity


async def test_disabled_or_deleted_agent_is_retired_and_not_served(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos)
    bot = await rt.get(_key())
    async with studio_transaction(repos.pool) as conn:
        await repos.agents.set_status(conn, GLOBAL, "a1", "disabled")
    assert await rt.get(_key()) is None
    assert bot in [e.bot for e in rt._cache.all_entries()] and bot.cleanup.await_count == 0   # retired, not cleaned
    async with studio_transaction(repos.pool) as conn:
        await repos.agents.set_status(conn, GLOBAL, "a1", "active")
    assert await rt.get(_key()) is not bot                                                      # served again, rebuilt


async def test_session_entries_and_expiry(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos)
    s1 = await rt.get_session(_key(), "t1")
    assert s1 is await rt.get_session(_key(), "t1") and await rt.get_session(_key(), "t2") is not s1
    assert await rt.get(_key()) is not s1                                     # base and session are separate builds
    assert await rt.get_session(_key(GLOBAL, "nope"), "t1") is None
    await _patch(repos, description="new")
    assert (await rt.get_session(_key(), "t1")) is not s1                    # stale version ⇒ fresh build, no clone
    later = time.monotonic() + SESSION_TTL + 5
    assert await rt.sweep(now=later) >= 2                                     # both t1 builds + t2 are past the TTL...
    assert s1.cleanup.await_count == 1                                         # ...the stale one was retired AND reclaimed


async def test_session_with_a_lease_survives_its_ttl(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path, session_ttl=10.0)
    await _create(repos)
    async with rt.use(_key(), session_id="t1") as bot:
        assert await rt.sweep(now=time.monotonic() + 1000) == 0 and bot.cleanup.await_count == 0
    assert await rt.sweep(now=time.monotonic() + 1000) == 1 and bot.cleanup.await_count == 1


async def test_three_versions_cleanup_once(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos, description="v1")
    v1 = await rt.get(_key())
    await _patch(repos, description="v2")
    v2 = await rt.get(_key())
    await _patch(repos, description="v3")
    v3 = await rt.get(_key())
    now = time.monotonic()
    assert await rt.sweep(now=now + GRACE - 1) == 0                            # grace not over
    assert await rt.sweep(now=now + GRACE + 1) == 2                            # v1 and v2, each reclaimed
    assert await rt.sweep(now=now + GRACE + 2) == 0
    assert [b.cleanup.await_count for b in (v1, v2, v3)] == [1, 1, 0]
    await rt.shutdown()
    assert [b.cleanup.await_count for b in (v1, v2, v3)] == [1, 1, 1]          # each exactly once


async def test_inflight_survives_replacement(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos, description="v1")
    async with rt.use(_key()) as held:
        await _patch(repos, description="v2")
        current = await rt.get(_key())
        assert current is not held and held.description == "v1"                # the request finishes on its version
        assert await rt.sweep(now=time.monotonic() + GRACE + 5) == 0           # leased: not reclaimable even past grace
        assert held.cleanup.await_count == 0
    assert await rt.sweep(now=time.monotonic() + GRACE + 5) == 1 and held.cleanup.await_count == 1
    assert current.cleanup.await_count == 0


async def test_idle_base_entry_is_retired_then_reclaimed(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos)
    bot = await rt.get(_key())
    now = time.monotonic()
    assert await rt.sweep(now=now + IDLE_TTL + 1) == 0 and bot.cleanup.await_count == 0
    assert await rt.sweep(now=now + IDLE_TTL + GRACE + 2) == 1 and bot.cleanup.await_count == 1
    assert await rt.get(_key()) is not bot                                       # rebuilt on the next lookup


async def test_shutdown_cleans_everything_once_and_removes_the_root(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    await rt.start()
    await _create(repos, description="v1")
    base = await rt.get(_key())
    session = await rt.get_session(_key(), "t1")
    await _patch(repos, description="v2")
    new_base = await rt.get(_key())
    async with rt.use(_key()) as leased:
        await rt.shutdown()                                                         # leases are ignored on shutdown
    assert all(b.cleanup.await_count == 1 for b in (base, session, new_base)) and leased is new_base
    assert not builder.runtime_dir.exists() and rt._sweep_task is None
    await rt.shutdown()
    assert new_base.cleanup.await_count == 1                                        # idempotent


async def test_asset_directory_is_shared_by_version_and_removed_by_the_last_user(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    svc = _service(repos)
    rec = await svc.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition(),
                           assets=[StudioAssetInput(kind="kb", name="k.md", content="kb")])
    base, session = await rt.get(_key()), await rt.get_session(_key(), "t1")
    directory = builder.runtime_dir / str(rec.agent_id) / f"v{base._studio_version}"
    assert directory.exists() and directory == base._agents_dir == session._agents_dir
    now = time.monotonic()
    rt._cache.retire(rt._cache.current(_key().qualified), now=now)                   # only the base entry goes
    assert await rt.sweep(now=now + GRACE + 1) == 1 and directory.exists()           # the session still uses it
    assert await rt.sweep(now=now + SESSION_TTL + 5) == 1 and not directory.exists()  # last user gone


async def test_build_refusal_raises_and_is_logged_once(repos, tmp_path, caplog):
    rt, _ = _runtime(repos, tmp_path)
    rec = await _create(repos, ACME)
    from datetime import datetime, timezone

    from parrot.handlers.studio.storage.models import StudioToolingRecord

    async with studio_transaction(repos.pool) as conn:     # a row written before the policy existed, behind the service
        await repos.tooling.replace(conn, rec.agent_id, toolkits=[], mcp_servers=[StudioToolingRecord(
            None, "mcp", "s", 0, {"transport": "stdio", "command": "/bin/sh"}, {}, None, datetime.now(timezone.utc))])
    with caplog.at_level(logging.WARNING, logger="Parrot.AgentStudio.Storage"):
        for _ in range(3):
            with pytest.raises(StudioToolingRefused):
                await rt.get(_key(ACME))
    assert sum("refused at build" in r.message for r in caplog.records) == 1
    assert rt._cache.all_entries() == []


async def test_use_checks_access_before_any_build_and_reports_missing(repos, tmp_path, monkeypatch):
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos)
    denied = AsyncMock(side_effect=AgentAccessDenied("no"))
    monkeypatch.setattr(runtime_module, "enforce_agent_access", denied)
    with pytest.raises(AgentAccessDenied):
        async with rt.use(_key(), request=Mock()):
            pass
    assert builder.built == [] and denied.await_args.args[1] == _key().qualified
    monkeypatch.setattr(runtime_module, "enforce_agent_access", AsyncMock())
    with pytest.raises(StudioNotFound):
        async with rt.use(_key(GLOBAL, "missing")):
            pass


async def test_reload_forces_a_rebuild_and_retires_the_previous(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos)
    old = await rt.get(_key())
    result = await rt.reload(_key())
    assert (result.name, result.reloaded) == ("a1", True) and len(builder.built) == 2
    new = await rt.get(_key())
    assert new is builder.built[1] and new is not old and old.cleanup.await_count == 0
    with pytest.raises(AgentNotFoundError):
        await rt.reload(_key(GLOBAL, "missing"))


async def test_revalidate_ttl_skips_the_head_query(repos, tmp_path, monkeypatch):
    rt, _ = _runtime(repos, tmp_path, revalidate_ttl=60.0)
    await _create(repos)
    calls = []
    real = repos.agents.get_version

    async def counting(part, name):
        calls.append(name)
        return await real(part, name)

    monkeypatch.setattr(repos.agents, "get_version", counting)
    first = await rt.get(_key())
    assert await rt.get(_key()) is first and len(calls) == 2                         # build = head + post-build recheck; none inside the TTL
    strict, _ = _runtime(repos, tmp_path / "strict")
    await strict.get(_key()), await strict.get(_key())
    assert len(calls) == 5                                                           # TTL 0 revalidates every lookup


async def test_sweep_task_runs_and_stops(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path, sweep_interval=0.01, session_ttl=0.0)
    await _create(repos)
    await rt.start()
    session = await rt.get_session(_key(), "t1")
    for _ in range(100):
        if session.cleanup.await_count:
            break
        await asyncio.sleep(0.02)
    assert session.cleanup.await_count == 1                                          # the loop swept it by itself
    await rt.shutdown()
    assert rt._sweep_task is None


# ---- lifecycle hooks (module functions) ---------------------------------------------------------------------------
def test_hooks_are_added_once_per_app():
    app = web.Application()
    add_studio_runtime_hooks(app)
    add_studio_runtime_hooks(app)
    assert app.on_startup.count(install_studio_runtime) == 1 and app.on_cleanup.count(shutdown_studio_runtime) == 1


async def test_install_awaits_storage_first_and_only_serves_the_database_backend(repos, tmp_path, monkeypatch):
    order = []
    manager = SimpleNamespace(registry=SimpleNamespace(evaluator=None), app=None, studio=None)
    app = web.Application()
    app["bot_manager"] = manager
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SESSION_TTL_SECONDS", "42")
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "not-a-number")

    async def fake_ensure(a, backend="database"):
        order.append("ensure")
        return SimpleNamespace(backend=backend, repos=repos if backend == "database" else None)

    monkeypatch.setattr(runtime_module, "ensure_studio_storage", lambda a: fake_ensure(a))
    await install_studio_runtime(app)
    rt = manager.studio
    assert order == ["ensure"] and isinstance(rt, StudioAgentRuntime) and rt.app is app
    assert (rt._session_ttl, rt._sweep_interval) == (42.0, 60.0)                       # bad value → default, logged
    assert rt._sweep_task is not None and (tmp_path / "rt").exists()
    await shutdown_studio_runtime(app)
    assert rt._sweep_task is None and not (tmp_path / "rt").exists()
    other = SimpleNamespace(registry=None, app=None, studio=None)
    app2 = web.Application()
    app2["bot_manager"] = other
    monkeypatch.setattr(runtime_module, "ensure_studio_storage", lambda a: fake_ensure(a, "filesystem"))
    await install_studio_runtime(app2)
    assert other.studio is None
    await shutdown_studio_runtime(app2)                                                # nothing installed: no error


async def test_lifecycle_registry_only_mount():
    """Hooks added BEFORE ``setup_studio_routes`` and without ``BotManager.setup()``: still once, storage first."""
    from parrot.handlers.studio import setup_studio_routes

    app = web.Application()
    add_studio_runtime_hooks(app)
    setup_studio_routes(app)
    setup_studio_routes(app)
    hooks = list(app.on_startup)
    assert hooks.count(install_studio_runtime) == 1
    resolve = [h for h in hooks if getattr(h, "__name__", "") == "resolve_studio_storage"]
    assert len(resolve) == 1


async def test_evict_retires_base_and_sessions_without_cleaning(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos)
    base, session = await rt.get(_key()), await rt.get_session(_key(), "t1")
    rt.evict(_key())
    assert base.cleanup.await_count == session.cleanup.await_count == 0
    assert rt._cache.current(_key().qualified) is None and rt._cache.session(_key().qualified, "t1") is None
    assert await rt.sweep(now=time.monotonic() + GRACE + 1) == 2
    assert base.cleanup.await_count == session.cleanup.await_count == 1


async def test_evict_session_retires_only_that_session(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos)
    base, s1, s2 = await rt.get(_key()), await rt.get_session(_key(), "t1"), await rt.get_session(_key(), "t2")
    assert rt.evict_session(_key(), "t1") is True
    assert rt._cache.session(_key().qualified, "t1") is None
    assert rt._cache.session(_key().qualified, "t2") is not None and rt._cache.current(_key().qualified) is not None
    assert base.cleanup.await_count == s1.cleanup.await_count == s2.cleanup.await_count == 0   # never cleans now
    assert rt.evict_session(_key(), "t1") is False and rt.evict_session(_key(), "nope") is False
    assert await rt.sweep(now=time.monotonic() + GRACE + 1) == 1                # only the retired session is reclaimed
    assert s1.cleanup.await_count == 1 and base.cleanup.await_count == s2.cleanup.await_count == 0


async def test_clean_is_idempotent_per_entry(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos)
    bot = await rt.get(_key())
    entry = rt._cache.current(_key().qualified)
    await rt._clean(entry)
    await rt._clean(entry)
    assert bot.cleanup.await_count == 1 and entry.cleaned


async def test_row_deleted_between_head_and_snapshot_is_not_served(repos, tmp_path, monkeypatch):
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos)
    old = await rt.get(_key())
    await _patch(repos, description="v2")                                # forces a rebuild...

    async def vanished(part, name):
        return None                                                      # ...but the row is gone by snapshot time

    monkeypatch.setattr(repos.agents, "load_snapshot", vanished)
    assert await rt.get(_key()) is None and len(builder.built) == 1
    assert rt._cache.current(_key().qualified) is None and old in [e.bot for e in rt._cache.all_entries()]


async def test_session_lookup_refreshes_the_expiry(repos, tmp_path, monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(runtime_module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos)
    session = await rt.get_session(_key(), "t1")                         # built at t=1000
    clock.now = 1000.0 + SESSION_TTL - 10
    assert await rt.get_session(_key(), "t1") is session                 # used again just before it would expire
    assert await rt.sweep(now=1000.0 + SESSION_TTL + 5) == 0 and session.cleanup.await_count == 0
    assert await rt.sweep(now=1000.0 + 2 * SESSION_TTL) == 1


# ---- W2 review fixes ----------------------------------------------------------------------------------------------
async def test_lease_taken_between_reclaim_and_clean_is_honoured(repos, tmp_path, monkeypatch):
    rt, _ = _runtime(repos, tmp_path, session_ttl=10.0)
    await _create(repos)
    first, second = await rt.get_session(_key(), "t1"), await rt.get_session(_key(), "t2")
    entries = {e.bot: e for e in rt._cache.all_entries()}
    real = runtime_module.cleanup_bot_instance
    seen = []

    async def cleaning_first_takes_a_lease_on_the_second(bot, *, label):
        seen.append(bot)
        entries[second].leases += 1                      # a request arrives while the sweep is awaiting
        return await real(bot, label=label)

    monkeypatch.setattr(runtime_module, "cleanup_bot_instance", cleaning_first_takes_a_lease_on_the_second)
    later = time.monotonic() + 1000
    assert await rt.sweep(now=later) == 1 and seen == [first] and second.cleanup.await_count == 0
    monkeypatch.setattr(runtime_module, "cleanup_bot_instance", real)
    entries[second].leases -= 1
    assert await rt.sweep(now=later + GRACE + 1) == 1 and second.cleanup.await_count == 1


async def test_due_entries_are_unreachable_before_the_first_await(repos, tmp_path, monkeypatch):
    rt, builder = _runtime(repos, tmp_path, session_ttl=10.0)
    await _create(repos)
    await rt.get_session(_key(), "t1")
    await rt.get_session(_key(), "t2")
    observed = []
    real = runtime_module.cleanup_bot_instance

    async def lookup_during_clean(bot, *, label):
        # the sweep is awaiting the FIRST clean-up: the second due entry must already be out of the lookup map
        observed.append((rt._cache.session(_key().qualified, "t1"), rt._cache.session(_key().qualified, "t2")))
        return await real(bot, label=label)

    monkeypatch.setattr(runtime_module, "cleanup_bot_instance", lookup_during_clean)
    assert await rt.sweep(now=time.monotonic() + 1000) == 2 and observed[0] == (None, None)
    assert await rt.get_session(_key(), "t2") is builder.built[-1] and len(builder.built) == 3


async def test_clean_skips_a_leased_entry_unless_forced(repos, tmp_path):
    rt, _ = _runtime(repos, tmp_path)
    await _create(repos)
    bot = await rt.get(_key())
    entry = rt._cache.current(_key().qualified)
    entry.leases = 1
    assert await rt._clean(entry) == 0 and bot.cleanup.await_count == 0
    assert await rt._clean(entry, force=True) == 1 and bot.cleanup.await_count == 1


async def test_shutdown_removes_only_its_own_directories(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    root = builder.runtime_dir
    foreign_dir = root / "11111111-1111-1111-1111-111111111111" / "v1"
    foreign_dir.mkdir(parents=True)
    (foreign_dir / "keep.md").write_text("another process")
    (root / "notes.txt").write_text("not ours")
    await rt.start()
    rec = await _service(repos).create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition(),
                                       assets=[StudioAssetInput(kind="kb", name="k.md", content="kb")])
    bot = await rt.get(_key())
    own = bot._agents_dir
    assert own.exists() and own == root / str(rec.agent_id) / f"v{bot._studio_version}"
    await rt.shutdown()
    assert not own.exists() and not own.parent.exists()
    assert (foreign_dir / "keep.md").read_text() == "another process" and (root / "notes.txt").exists()


async def test_directory_removal_runs_off_the_event_loop(repos, tmp_path, monkeypatch):
    calls = []
    real = asyncio.to_thread

    async def spy(func, *a, **k):
        calls.append(getattr(func, "__name__", str(func)))
        return await real(func, *a, **k)

    monkeypatch.setattr(runtime_module.asyncio, "to_thread", spy)
    rt, _ = _runtime(repos, tmp_path, session_ttl=0.0)
    await _service(repos).create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition(),
                                 assets=[StudioAssetInput(kind="kb", name="k.md", content="kb")])
    await rt.get_session(_key(), "t1")
    assert await rt.sweep(now=time.monotonic() + 5) == 1 and "_remove_dir" in calls
    await rt.shutdown()
    assert "_prune" in calls


async def test_agent_disabled_while_building_is_not_installed(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos)
    real_build = builder.build

    async def build_then_disable(snapshot, app, *, part):
        result = await real_build(snapshot, app, part=part)
        async with studio_transaction(repos.pool) as conn:
            await repos.agents.set_status(conn, GLOBAL, "a1", "disabled")
        return result

    builder.build = build_then_disable
    assert await rt.get(_key()) is None and rt._cache.all_entries() == []
    bot = builder.built[0]
    assert bot.cleanup.await_count == 1 and not bot._agents_dir.exists()
    builder.build = real_build
    assert await rt.get_session(_key(), "t1") is None


async def test_agent_deleted_and_recreated_while_building_is_not_installed(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos)
    real_build = builder.build

    async def build_then_replace(snapshot, app, *, part):
        result = await real_build(snapshot, app, part=part)
        await _service(repos).delete(GLOBAL, "a1", guard=NO_GUARD)
        await _create(repos)
        return result

    builder.build = build_then_replace
    assert await rt.get(_key()) is None and rt._cache.all_entries() == []     # the old identity is never served


async def test_version_bumped_while_building_is_not_installed_and_the_current_one_is_served(repos, tmp_path):
    """PR #1564 (codex P1): the stale snapshot must never be installed or returned once the head moved."""
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos, description="v1")
    real_build = builder.build

    async def build_then_bump(snapshot, app, *, part):
        result = await real_build(snapshot, app, part=part)
        if len(builder.built) == 1:                  # only during the first build
            await _patch(repos, description="v2")
        return result

    builder.build = build_then_bump
    served = await rt.get(_key())
    assert served is not None and served.description == "v2"
    assert len(builder.built) == 2
    stale = builder.built[0]
    assert stale.cleanup.await_count == 1 and not stale._agents_dir.exists()        # discarded, not leaked
    entries = rt._cache.all_entries()
    assert len(entries) == 1 and entries[0].bot is served and entries[0].version == 2
    assert await rt.get(_key()) is served                                            # and it is what is cached


async def test_agent_that_keeps_changing_while_building_is_not_served_stale(repos, tmp_path):
    rt, builder = _runtime(repos, tmp_path)
    await _create(repos, description="v1")
    real_build = builder.build

    async def always_bump(snapshot, app, *, part):
        result = await real_build(snapshot, app, part=part)
        await _patch(repos, description=f"v{len(builder.built) + 1}")
        return result

    builder.build = always_bump
    with pytest.raises(RuntimeError):
        await rt.get(_key())
    assert rt._cache.all_entries() == []
    assert all(bot.cleanup.await_count == 1 for bot in builder.built)


async def test_refused_memory_and_session_count_are_bounded(repos, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_module, "_REFUSED_CAP", 3)
    rt, _ = _runtime(repos, tmp_path, max_sessions=2)
    await _create(repos)
    for n in range(10):
        rt._refused[(n, 1)] = None
    # the cap is applied when a refusal is recorded
    from parrot.handlers.studio.storage.models import StudioToolingRefused as Refused

    async def refuse(snapshot, app, *, part):
        raise Refused("nope")

    rt._builder.build = refuse
    with pytest.raises(Refused):
        await rt.get(_key())
    assert len(rt._refused) <= 3
    rt2, builder2 = _runtime(repos, tmp_path / "s", max_sessions=2)
    sessions = []
    for n in range(5):
        sessions.append(await rt2.get_session(_key(), f"t{n}"))
        await asyncio.sleep(0)
    live = [e for e in rt2._cache.all_entries() if e.session_id and e.retired_at is None]
    assert len(live) == 2 and [e.session_id for e in live] == ["t3", "t4"]        # the oldest were retired...
    assert sessions[0].cleanup.await_count == 0                                   # ...not cleaned on the spot
    assert await rt2.sweep(now=time.monotonic() + GRACE + 1) == 3
