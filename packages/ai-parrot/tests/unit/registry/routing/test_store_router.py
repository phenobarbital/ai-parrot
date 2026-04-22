"""Unit tests for parrot.registry.routing.store_router (TASK-792)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.registry.routing import (
    StoreRouter,
    StoreRouterConfig,
    StoreFallbackPolicy,
    NoSuitableStoreError,
)
from parrot.tools.multistoresearch import StoreType


@pytest.fixture
def fake_stores():
    s = {}
    for t in (StoreType.PGVECTOR, StoreType.FAISS, StoreType.ARANGO):
        m = AsyncMock()
        m.similarity_search = AsyncMock(return_value=[])
        s[t] = m
    return s


@pytest.fixture
def config():
    return StoreRouterConfig(
        margin_threshold=0.1,
        fallback_policy=StoreFallbackPolicy.EMPTY,
        cache_size=8,
    )


@pytest.mark.asyncio
async def test_fast_path(config, fake_stores):
    router = StoreRouter(config)
    decision = await router.route(
        "what is an endcap?", list(fake_stores.keys()), invoke_fn=None
    )
    assert decision.path == "fast"
    assert decision.rankings[0].store == StoreType.PGVECTOR


@pytest.mark.asyncio
async def test_cache_hit(config, fake_stores):
    router = StoreRouter(config)
    q = "graph relationships between suppliers"
    d1 = await router.route(q, list(fake_stores.keys()), invoke_fn=None)
    d2 = await router.route(q, list(fake_stores.keys()), invoke_fn=None)
    assert d2.cache_hit is True
    assert d2.path == "cache"
    assert d1.rankings[0].store == d2.rankings[0].store


@pytest.mark.asyncio
async def test_llm_path_triggered_by_tight_margin():
    cfg = StoreRouterConfig(margin_threshold=0.9)  # almost always tight
    router = StoreRouter(cfg)
    calls = []

    async def fake_invoke(prompt):
        calls.append(prompt)

        class M:
            output = {"rankings": [{"store": "arango", "confidence": 0.95, "reason": "x"}]}

        return M()

    decision = await router.route(
        "ambiguous query", list(StoreType), invoke_fn=fake_invoke
    )
    assert len(calls) == 1
    assert decision.path == "llm"


@pytest.mark.asyncio
async def test_llm_timeout_falls_back_to_fast():
    cfg = StoreRouterConfig(margin_threshold=0.9, llm_timeout_s=0.05)
    router = StoreRouter(cfg)

    async def slow(prompt):
        await asyncio.sleep(5)

    decision = await router.route("anything", list(StoreType), invoke_fn=slow)
    # LLM timed out → fast path result used
    assert decision.path == "fast"


@pytest.mark.asyncio
async def test_fan_out_policy_delegates(config, fake_stores):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.FAN_OUT)
    router = StoreRouter(cfg)
    tool = MagicMock()
    tool._execute = AsyncMock(return_value=[{"content": "x"}])
    # Craft an empty-rankings decision
    decision = await router.route("zzzzzz", [StoreType.PGVECTOR], invoke_fn=None)
    decision.fallback_used = True
    decision.rankings = []
    results = await router.execute(decision, "zzzzzz", fake_stores, multistore_tool=tool)
    tool._execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_policy(fake_stores):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.EMPTY)
    router = StoreRouter(cfg)
    decision = await router.route("zzzzzz", [StoreType.PGVECTOR], invoke_fn=None)
    decision.fallback_used = True
    decision.rankings = []
    results = await router.execute(decision, "zzzzzz", fake_stores)
    assert results == []


@pytest.mark.asyncio
async def test_raise_policy(fake_stores):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.RAISE)
    router = StoreRouter(cfg)
    decision = await router.route("zzzzzz", [StoreType.PGVECTOR], invoke_fn=None)
    decision.fallback_used = True
    decision.rankings = []
    with pytest.raises(NoSuitableStoreError):
        await router.execute(decision, "zzzzzz", fake_stores)


@pytest.mark.asyncio
async def test_execute_top_n_concurrent(fake_stores):
    cfg = StoreRouterConfig(top_n=2, margin_threshold=0.01, fallback_policy=StoreFallbackPolicy.EMPTY)
    router = StoreRouter(cfg)
    decision = await router.route("relationship between", list(StoreType), invoke_fn=None)
    await router.execute(decision, "relationship between", fake_stores)
    called = sum(1 for s in fake_stores.values() if s.similarity_search.await_count > 0)
    assert 1 <= called <= cfg.top_n


@pytest.mark.asyncio
async def test_elapsed_ms_populated(config, fake_stores):
    router = StoreRouter(config)
    decision = await router.route("what is x?", list(fake_stores.keys()))
    assert decision.elapsed_ms >= 0.0


@pytest.mark.asyncio
async def test_first_available_policy(fake_stores):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.FIRST_AVAILABLE)
    router = StoreRouter(cfg)
    fake_stores[StoreType.PGVECTOR].similarity_search = AsyncMock(return_value=["result"])
    decision = await router.route("zzzz", [StoreType.PGVECTOR], invoke_fn=None)
    decision.fallback_used = True
    decision.rankings = []
    results = await router.execute(decision, "zzzz", fake_stores)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_fan_out_without_tool_uses_all_stores(fake_stores):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.FAN_OUT)
    router = StoreRouter(cfg)
    decision = await router.route("zzzz", [StoreType.PGVECTOR], invoke_fn=None)
    decision.fallback_used = True
    decision.rankings = []
    results = await router.execute(decision, "zzzz", fake_stores, multistore_tool=None)
    assert isinstance(results, list)
    # All stores should have been called
    total_calls = sum(s.similarity_search.await_count for s in fake_stores.values())
    assert total_calls == len(fake_stores)
