"""Per-tenant runtime, its cache, and the two lifetime hazards.

Everything here runs without a database or an LLM: the runtime holds opaque
objects, so the concurrency and lifetime rules can be tested with stubs.
"""
from __future__ import annotations

import asyncio

import pytest

from parrot_saas.tenancy.context import TenantContext
from parrot_saas.tenancy.registry import TenantAgentRegistry
from parrot_saas.tenancy.runtime import (
    TenantRuntime,
    TenantRuntimeCache,
    clone_tool_manager,
)


def _tenant(slug: str = "bar-pepe") -> TenantContext:
    """A minimal tenant context."""
    return TenantContext(tenant_id=slug, name=slug.title())


class _Agent:
    """Stub agent recording whether it was closed."""

    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


class _ToolManager:
    """Stub tool manager recording teardown and guard reapplication."""

    def __init__(self) -> None:
        self.executors_closed = 0
        self.toolkits_cleaned = 0
        self._grant_guard = None
        self._confirmation_guard = None
        self._broker = None
        self.cloned_with_search = None

    def clone(self, *, include_search_tool: bool = False) -> "_ToolManager":
        """Mirror the real clone(): guards are deliberately NOT carried."""
        other = _ToolManager()
        other.cloned_with_search = include_search_tool
        other._broker = self._broker
        return other

    def set_grant_guard(self, guard) -> None:
        self._grant_guard = guard

    def set_confirmation_guard(self, guard) -> None:
        self._confirmation_guard = guard

    def set_broker(self, broker) -> None:
        self._broker = broker

    async def close_executors(self) -> None:
        self.executors_closed += 1

    async def cleanup_toolkits(self) -> None:
        self.toolkits_cleaned += 1


# ---------------------------------------------------------------------------
# TenantAgentRegistry
# ---------------------------------------------------------------------------


def test_registry_has_no_filesystem_side_effects(tmp_path, monkeypatch) -> None:
    """Constructing a registry must not touch disk or sys.path.

    The whole reason this class exists is that ``AgentRegistry.__init__``
    creates directories, writes agents.yaml and appends to sys.path — fine
    once per process, unacceptable once per tenant.
    """
    import sys

    monkeypatch.chdir(tmp_path)
    before = list(sys.path)

    TenantAgentRegistry("bar-pepe")

    assert list(tmp_path.iterdir()) == []
    assert sys.path == before


def test_registry_lookup_surface() -> None:
    """It satisfies exactly what the flow engine calls."""
    agent = _Agent()
    registry = TenantAgentRegistry("bar-pepe", {"triage": agent})

    assert registry.get_bot_instance("triage") is agent
    assert registry.get_bot_instance("absent") is None
    assert registry.has("triage") is True
    assert len(registry) == 1


async def test_registry_async_lookup_matches_sync() -> None:
    """``get_instance`` mirrors ``get_bot_instance``."""
    registry = TenantAgentRegistry("bar-pepe", {"triage": "A"})

    assert await registry.get_instance("triage") == "A"
    assert await registry.get_instance("absent") is None


# ---------------------------------------------------------------------------
# clone_tool_manager — the silent security downgrade
# ---------------------------------------------------------------------------


def test_clone_reapplies_guards_that_clone_drops() -> None:
    """A tenant's manager must keep the guards the template had.

    ``ToolManager.clone()`` carries tools, resolver and broker but not
    ``_grant_guard``/``_confirmation_guard``. Nothing fails when they are
    lost, which is exactly why this needs a test.
    """
    template = _ToolManager()
    template.set_grant_guard("GRANT")
    template.set_confirmation_guard("CONFIRM")

    clone = clone_tool_manager(template, broker="BROKER")

    assert clone is not template
    assert clone._grant_guard == "GRANT"
    assert clone._confirmation_guard == "CONFIRM"
    assert clone._broker == "BROKER"


def test_raw_clone_would_have_lost_the_guards() -> None:
    """Pin the upstream behaviour this helper compensates for."""
    template = _ToolManager()
    template.set_grant_guard("GRANT")

    assert template.clone()._grant_guard is None


def test_clone_accepts_explicit_guard_overrides() -> None:
    """A tenant may carry its own guards rather than the template's."""
    template = _ToolManager()
    template.set_grant_guard("TEMPLATE")

    clone = clone_tool_manager(template, grant_guard="TENANT")

    assert clone._grant_guard == "TENANT"


# ---------------------------------------------------------------------------
# TenantRuntime
# ---------------------------------------------------------------------------


async def test_runtime_builds_its_own_registry() -> None:
    """A runtime without an explicit registry gets one over its agents."""
    runtime = TenantRuntime(tenant=_tenant(), agents={"triage": "A"})

    assert runtime.agent_registry is not None
    assert runtime.agent_registry.get_bot_instance("triage") == "A"


async def test_aclose_closes_agents_and_tool_manager() -> None:
    """Teardown releases both the agents and the manager's executors."""
    agent, manager = _Agent(), _ToolManager()
    runtime = TenantRuntime(
        tenant=_tenant(), agents={"triage": agent}, tool_manager=manager
    )

    await runtime.aclose()

    assert agent.closed == 1
    assert manager.executors_closed == 1
    assert manager.toolkits_cleaned == 1


async def test_aclose_is_idempotent() -> None:
    """Eviction, invalidate and shutdown can all reach aclose()."""
    agent = _Agent()
    runtime = TenantRuntime(tenant=_tenant(), agents={"triage": agent})

    await runtime.aclose()
    await runtime.aclose()

    assert agent.closed == 1
    assert runtime.closed is True


async def test_aclose_survives_a_failing_agent() -> None:
    """One agent's teardown failure must not abort the rest."""

    class _Exploding:
        async def aclose(self):
            raise RuntimeError("boom")

    good = _Agent()
    manager = _ToolManager()
    runtime = TenantRuntime(
        tenant=_tenant(),
        agents={"bad": _Exploding(), "good": good},
        tool_manager=manager,
    )

    await runtime.aclose()

    assert good.closed == 1
    assert manager.executors_closed == 1


async def test_acquire_tracks_leases() -> None:
    """A lease marks the runtime as in use for the duration of a run."""
    runtime = TenantRuntime(tenant=_tenant())

    assert runtime.in_use is False
    async with runtime.acquire():
        assert runtime.in_use is True
    assert runtime.in_use is False


async def test_acquire_on_a_closed_runtime_raises() -> None:
    """Starting a run on a closed runtime is a bug, not a silent no-op."""
    runtime = TenantRuntime(tenant=_tenant())
    await runtime.aclose()

    with pytest.raises(RuntimeError, match="is closed"):
        async with runtime.acquire():
            pass


async def test_semaphore_bounds_concurrency() -> None:
    """The runtime's semaphore caps concurrent runs for one tenant.

    The flow scheduler enforces no concurrency limit of its own, so this is
    the only thing standing between a webhook burst and unbounded parallel
    LLM calls.
    """
    runtime = TenantRuntime(tenant=_tenant(), semaphore=asyncio.Semaphore(2))
    peak = 0
    active = 0

    async def _run() -> None:
        nonlocal peak, active
        async with runtime.acquire():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(_run() for _ in range(8)))

    assert peak <= 2


# ---------------------------------------------------------------------------
# TenantRuntimeCache
# ---------------------------------------------------------------------------


def _counting_builder():
    """Return a builder plus the list of tenants it was asked to build."""
    built: list[str] = []

    async def _build(tenant: TenantContext) -> TenantRuntime:
        built.append(tenant.tenant_id)
        await asyncio.sleep(0.01)  # make the race window real
        return TenantRuntime(tenant=tenant, agents={"triage": _Agent()})

    return _build, built


async def test_cache_returns_the_same_runtime() -> None:
    """A warm tenant is served from cache."""
    builder, built = _counting_builder()
    cache = TenantRuntimeCache(builder)

    first = await cache.get(_tenant())
    second = await cache.get(_tenant())

    assert first is second
    assert built == ["bar-pepe"]


async def test_concurrent_gets_build_exactly_once() -> None:
    """A burst of webhooks for a cold tenant must build one runtime.

    Without the double check inside the per-tenant lock, every waiter would
    build its own on acquiring it — N clients, N sets of credentials.
    """
    builder, built = _counting_builder()
    cache = TenantRuntimeCache(builder)

    runtimes = await asyncio.gather(*(cache.get(_tenant()) for _ in range(20)))

    assert built == ["bar-pepe"]
    assert all(rt is runtimes[0] for rt in runtimes)


async def test_separate_tenants_get_separate_runtimes() -> None:
    """Two tenants never share a runtime."""
    builder, _ = _counting_builder()
    cache = TenantRuntimeCache(builder)

    a = await cache.get(_tenant("bar-pepe"))
    b = await cache.get(_tenant("hotel-x"))

    assert a is not b
    assert len(cache) == 2


async def test_invalidate_drops_and_closes() -> None:
    """Invalidating a tenant releases its resources and forces a rebuild."""
    builder, built = _counting_builder()
    cache = TenantRuntimeCache(builder)
    runtime = await cache.get(_tenant())

    assert await cache.invalidate("bar-pepe") is True
    assert runtime.closed is True
    assert "bar-pepe" not in cache

    await cache.get(_tenant())
    assert built == ["bar-pepe", "bar-pepe"]


async def test_invalidate_unknown_is_false() -> None:
    """Invalidating a tenant with no runtime is not an error."""
    builder, _ = _counting_builder()

    assert await TenantRuntimeCache(builder).invalidate("nobody") is False


async def test_lru_eviction_respects_capacity() -> None:
    """The cache stays bounded, evicting least-recently-used first."""
    builder, _ = _counting_builder()
    cache = TenantRuntimeCache(builder, max_size=2)

    first = await cache.get(_tenant("aaa-one"))
    await cache.get(_tenant("bbb-two"))
    await cache.get(_tenant("aaa-one"))     # refresh recency of the first
    await cache.get(_tenant("ccc-three"))

    assert len(cache) == 2
    assert "bbb-two" not in cache
    assert "aaa-one" in cache
    assert first.closed is False


async def test_ttl_eviction_closes_idle_runtimes() -> None:
    """An idle runtime is released rather than held open indefinitely."""
    builder, _ = _counting_builder()
    cache = TenantRuntimeCache(builder, ttl=0.0)
    idle = await cache.get(_tenant("aaa-one"))

    await cache.get(_tenant("bbb-two"))  # triggers an eviction pass

    assert "aaa-one" not in cache
    assert idle.closed is True


async def test_a_runtime_in_use_is_never_evicted_from_under_a_run() -> None:
    """Eviction must not close agents a running flow still holds.

    Flow nodes keep their agent by reference, so closing a client mid-run
    would surface as a confusing provider error rather than as an eviction.
    A busy runtime survives an eviction pass even at capacity and even when
    it is the least recently used entry.
    """
    builder, _ = _counting_builder()
    cache = TenantRuntimeCache(builder, max_size=1)
    busy = await cache.get(_tenant("aaa-one"))

    async with busy.acquire():
        fresh = await cache.get(_tenant("bbb-two"))  # over capacity while busy

        assert busy.closed is False, "evicted a runtime with a live run"
        assert "aaa-one" in cache
        assert fresh.closed is False, "handed back a closed runtime"


async def test_get_never_returns_a_runtime_it_just_evicted() -> None:
    """A caller must never receive a closed runtime.

    At capacity with every other entry busy, the only evictable runtime is the
    one just built — the one about to be returned. Evicting it would hand the
    caller a closed runtime, which surfaces much later as an unrelated error.
    """
    builder, _ = _counting_builder()
    cache = TenantRuntimeCache(builder, max_size=1)
    busy = await cache.get(_tenant("aaa-one"))

    async with busy.acquire():
        fresh = await cache.get(_tenant("bbb-two"))

    assert fresh.closed is False
    async with fresh.acquire():
        pass  # would raise RuntimeError if it had been closed


async def test_over_capacity_with_everything_busy_defers_rather_than_closing() -> None:
    """When nothing is evictable the cache exceeds capacity, briefly.

    Deliberate: breaching a soft memory bound is recoverable, closing a
    client out from under a live run is not.
    """
    builder, _ = _counting_builder()
    # Capacity 2 so both runtimes exist before any lease is taken; the pass
    # that matters is the one triggered by the third tenant.
    cache = TenantRuntimeCache(builder, max_size=2)
    first = await cache.get(_tenant("aaa-one"))
    second = await cache.get(_tenant("bbb-two"))

    async with first.acquire(), second.acquire():
        await cache.get(_tenant("ccc-three"))

        assert first.closed is False
        assert second.closed is False
        assert len(cache) == 3


async def test_invalidating_a_busy_runtime_closes_it_once_the_lease_drains() -> None:
    """A config change must not sever a run that is already in flight.

    The runtime leaves the cache immediately — so the next request rebuilds
    with the new configuration — but its resources are released only after the
    running flow lets go.
    """
    builder, _ = _counting_builder()
    cache = TenantRuntimeCache(builder)
    runtime = await cache.get(_tenant())

    async with runtime.acquire():
        assert await cache.invalidate("bar-pepe") is True
        assert "bar-pepe" not in cache
        assert runtime.closed is False, "closed a runtime with a live run"

    for _ in range(40):
        if runtime.closed:
            break
        await asyncio.sleep(0.05)
    assert runtime.closed is True


async def test_aclose_all_releases_everything() -> None:
    """Shutdown closes every runtime."""
    builder, _ = _counting_builder()
    cache = TenantRuntimeCache(builder)
    a = await cache.get(_tenant("aaa-one"))
    b = await cache.get(_tenant("bbb-two"))

    await cache.aclose_all()

    assert a.closed and b.closed
    assert len(cache) == 0


async def test_a_closed_runtime_is_rebuilt_rather_than_served() -> None:
    """A runtime closed out-of-band must not be handed to a new request."""
    builder, built = _counting_builder()
    cache = TenantRuntimeCache(builder)
    runtime = await cache.get(_tenant())
    await runtime.aclose()

    fresh = await cache.get(_tenant())

    assert fresh is not runtime
    assert built == ["bar-pepe", "bar-pepe"]
