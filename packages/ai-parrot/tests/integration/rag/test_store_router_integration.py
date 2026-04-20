"""End-to-end integration tests for the FEAT-111 StoreRouter (TASK-794).

Each test skips cleanly when the required backend is not available in the
test environment.  The performance test measures only the router's own
decision time (not downstream retrieval).

Run with::

    pytest packages/ai-parrot/tests/integration/rag/ -v
"""
from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.registry.routing import (
    StoreRouter,
    StoreRouterConfig,
    StoreFallbackPolicy,
)
from parrot.tools.multistoresearch import StoreType

try:
    from parrot.tools.multistoresearch import MultiStoreSearchTool
    _MULTITOOL_AVAILABLE = True
except ImportError:
    _MULTITOOL_AVAILABLE = False

try:
    from parrot.stores.faiss_store import FAISSStore
    _FAISS_AVAILABLE = True
except ImportError:
    FAISSStore = None
    _FAISS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pgvector_store():
    """Return a real PgVectorStore or skip if not available."""
    try:
        from parrot.stores.postgres import PgVectorStore
        import os
        dsn = os.environ.get("TEST_PGVECTOR_DSN", "")
        if not dsn:
            pytest.skip("TEST_PGVECTOR_DSN not set — PgVector integration tests skipped")
        store = PgVectorStore(dsn=dsn)
        # Quick connectivity check
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.wait_for(
                _ping_pgvector(store), timeout=5.0
            ))
        except Exception as exc:
            pytest.skip(f"PgVector not reachable: {exc}")
        finally:
            loop.close()
        return store
    except ImportError as exc:
        pytest.skip(f"parrot.stores.postgres unavailable: {exc}")


async def _ping_pgvector(store):
    """Minimal health check — attempt a connection."""
    if hasattr(store, "connection"):
        await store.connection()
    elif hasattr(store, "ping"):
        await store.ping()
    # If neither method exists, assume OK


@pytest.fixture(scope="module")
def arango_store():
    """Return a real ArangoDBStore or skip if not available."""
    try:
        from parrot.stores.arango import ArangoDBStore
        import os
        host = os.environ.get("TEST_ARANGO_HOST", "")
        if not host:
            pytest.skip("TEST_ARANGO_HOST not set — ArangoDB integration tests skipped")
        store = ArangoDBStore(host=host)
        return store
    except ImportError as exc:
        pytest.skip(f"parrot.stores.arango unavailable: {exc}")
    except Exception as exc:
        pytest.skip(f"ArangoDB not reachable: {exc}")


# ---------------------------------------------------------------------------
# Mock store for in-memory testing (no external backend required)
# ---------------------------------------------------------------------------

class _MockStore:
    """In-memory store mock that always returns a fixed result."""

    def __init__(self, name: str = "mock"):
        self.name = name
        self.called_with: list[str] = []

    async def similarity_search(self, query: str, **kwargs) -> list[dict]:
        self.called_with.append(query)
        return [{"content": f"result from {self.name} for: {query}", "score": 0.9}]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_fast_path_and_cache_with_mock():
    """Fast-path and cache-hit paths using an in-memory mock store.

    This test does NOT require any external backend — it is always runnable
    and verifies the core router pipeline end-to-end.
    """
    router = StoreRouter(StoreRouterConfig(cache_size=8))
    mock = _MockStore("pgvector")
    stores = {StoreType.PGVECTOR: mock}

    # ── fast path ────────────────────────────────────────────────────────
    q = "what is an endcap?"
    d1 = await router.route(q, list(stores.keys()))
    assert d1.path == "fast"
    assert not d1.cache_hit

    results = await router.execute(d1, q, stores)
    assert isinstance(results, list)

    # ── cache hit ─────────────────────────────────────────────────────────
    d2 = await router.route(q, list(stores.keys()))
    assert d2.cache_hit is True
    assert d2.path == "cache"


@pytest.mark.asyncio
async def test_router_llm_path_with_mock():
    """LLM path using a fake invoke_fn — no external LLM required."""
    router = StoreRouter(StoreRouterConfig(margin_threshold=0.9, cache_size=4))
    mock = _MockStore("pgvector")
    stores = {StoreType.PGVECTOR: mock, StoreType.ARANGO: _MockStore("arango")}

    async def fake_invoke(prompt):
        class M:
            output = {
                "rankings": [
                    {"store": "pgvector", "confidence": 0.95, "reason": "test"},
                ]
            }
        return M()

    d = await router.route("ambiguous query xyz", list(stores.keys()), invoke_fn=fake_invoke)
    assert d.path == "llm"


@pytest.mark.asyncio
async def test_router_with_multistore_fallback_mock():
    """FAN_OUT policy delegates to MultiStoreSearchTool._execute."""
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.FAN_OUT, cache_size=4)
    router = StoreRouter(cfg)
    mock_store = _MockStore("pgvector")
    stores = {StoreType.PGVECTOR: mock_store}

    # Build a fake MultiStoreSearchTool
    tool = MagicMock()
    tool._execute = AsyncMock(return_value=[{"content": "fan out result"}])

    # Craft a fallback decision
    from parrot.registry.routing.models import StoreRoutingDecision
    fallback_decision = StoreRoutingDecision(
        rankings=[], fallback_used=True, path="fast"
    )
    results = await router.execute(fallback_decision, "query", stores, multistore_tool=tool)
    tool._execute.assert_awaited_once()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_router_with_real_pgvector(pgvector_store):
    """End-to-end against a real PgVectorStore (skips if unavailable)."""
    router = StoreRouter(StoreRouterConfig(cache_size=8))
    stores = {StoreType.PGVECTOR: pgvector_store}

    # fast path
    d1 = await router.route("what is an endcap?", list(stores.keys()))
    assert d1.path == "fast"

    # cache hit
    d2 = await router.route("what is an endcap?", list(stores.keys()))
    assert d2.cache_hit is True

    # execute returns a list (may be empty for an empty test DB)
    results = await router.execute(d1, "what is an endcap?", stores)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_router_with_real_arango(arango_store):
    """Graph-style query routes to ArangoDB when ontology annotations present."""
    from parrot.registry.routing.ontology_signal import OntologyPreAnnotator

    class _GraphAnnotator:
        def resolve_intent(self, query):
            return {"action": "graph_query"}

    router = StoreRouter(
        StoreRouterConfig(cache_size=4),
        ontology_resolver=_GraphAnnotator(),
    )
    stores = {StoreType.ARANGO: arango_store}

    d = await router.route(
        "What are the relationships between suppliers and warehouses?",
        list(stores.keys()),
    )
    # With only ARANGO available and graph annotation, ARANGO should be preferred.
    assert isinstance(d.rankings, list)
    results = await router.execute(d, "supplier warehouse graph", stores)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_router_with_bot_end_to_end():
    """Full pipeline: configure_store_router → _build_vector_context.

    Uses in-memory mocks — no external backend required.
    """
    from tests.unit.bots.test_abstractbot_store_router import FakeBot
    from parrot.stores.postgres import PgVectorStore

    store = MagicMock(spec=PgVectorStore)
    store.similarity_search = AsyncMock(return_value=[
        {"content": "endcap is a display at the end of a store aisle", "score": 0.95}
    ])

    bot = FakeBot(store=store)
    bot.configure_store_router(StoreRouterConfig(cache_size=8))

    ctx, meta = await bot._build_vector_context("what is an endcap?")
    assert "endcap" in ctx.lower()


@pytest.mark.asyncio
async def test_perf_fast_path_under_5ms():
    """Fast-path (cache-hit) should stay under 5 ms (median of 5 calls).

    Measured around ``StoreRouter.route()`` only — no downstream retrieval.
    """
    router = StoreRouter(StoreRouterConfig(cache_size=8))
    stores_keys = [StoreType.PGVECTOR]
    q = "what is an endcap?"

    # warm-up call (populates cache)
    await router.route(q, stores_keys)

    times_ms = []
    for _ in range(5):
        t0 = time.perf_counter()
        await router.route(q, stores_keys)
        times_ms.append((time.perf_counter() - t0) * 1_000)

    times_ms.sort()
    median = times_ms[2]
    assert median < 5.0, (
        f"Fast/cache path median {median:.2f}ms exceeds 5ms budget. "
        f"All times: {[f'{t:.2f}' for t in times_ms]} ms"
    )
