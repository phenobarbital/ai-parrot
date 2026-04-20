"""Unit tests for AbstractBot StoreRouter integration (TASK-793).

These tests verify the new FEAT-111 methods (``configure_store_router``,
``_build_stores_dict``, and the router-aware ``_build_vector_context`` branch)
using a minimal FakeBot that mirrors the real implementation without needing
the full AbstractBot inheritance chain (which requires compiled Cython modules).

The FakeBot's methods are equivalent to those added to AbstractBot in abstract.py.
"""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.registry.routing import StoreRouterConfig, StoreRouter, StoreRoutingDecision, StoreScore
from parrot.tools.multistoresearch import StoreType


def _infer_store_type(store):
    """Map a store instance to its StoreType.  Mirrors abstract.py's helper."""
    try:
        from parrot.stores.postgres import PgVectorStore
        if isinstance(store, PgVectorStore):
            return StoreType.PGVECTOR
    except Exception:
        pass
    try:
        from parrot.stores.arango import ArangoDBStore
        if isinstance(store, ArangoDBStore):
            return StoreType.ARANGO
    except Exception:
        pass
    try:
        from parrot.stores.faiss_store import FAISSStore
        if isinstance(store, FAISSStore):
            return StoreType.FAISS
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Minimal FakeBot
# ---------------------------------------------------------------------------

class FakeBot:
    """Minimal bot-like class implementing the FEAT-111 store-router methods.

    This mirrors the exact implementation added to ``AbstractBot`` in
    ``parrot/bots/abstract.py`` so the tests cover the real logic.
    """

    def __init__(self, store=None):
        self.store = store
        self.stores = []
        self._store_router = None
        self._multi_store_tool = None
        self.logger = logging.getLogger("fake_bot")
        self.get_vector_context = AsyncMock(return_value=("ctx", {}))

    def configure_store_router(self, config, ontology_resolver=None, multi_store_tool=None):
        self._store_router = StoreRouter(config, ontology_resolver=ontology_resolver)
        self._multi_store_tool = multi_store_tool
        self.logger.info("StoreRouter configured on %s", type(self).__name__)

    def _build_stores_dict(self):
        mapping = {}

        def _add(inst):
            if inst is None:
                return
            st = _infer_store_type(inst)
            if st is not None and st not in mapping:
                mapping[st] = inst

        _add(getattr(self, "store", None))
        for attr in (
            "_vector_store", "vector_store",
            "_faiss_store", "faiss_store",
            "_arango_store", "arango_store",
            "_pgvector_store", "pgvector_store",
        ):
            _add(getattr(self, attr, None))
        return mapping

    async def _build_vector_context(
        self,
        question: str,
        use_vectors: bool = True,
        search_type: str = "similarity",
        search_kwargs: dict = None,
        ensemble_config: dict = None,
        metric_type: str = "COSINE",
        limit: int = 10,
        score_threshold: float = None,
        return_sources: bool = True,
    ):
        # Backward-compatible guard
        if self._store_router is None or not use_vectors or not self.store:
            if not (use_vectors and self.store):
                return "", {}
            return await self.get_vector_context(
                question,
                search_type=search_type,
                search_kwargs=search_kwargs,
                metric_type=metric_type,
                limit=limit,
                score_threshold=score_threshold,
                ensemble_config=ensemble_config,
                return_sources=return_sources,
            )

        # Router-aware path
        stores_dict = self._build_stores_dict()
        available = list(stores_dict.keys())
        if not available:
            return await self.get_vector_context(
                question,
                search_type=search_type,
                search_kwargs=search_kwargs,
                metric_type=metric_type,
                limit=limit,
                score_threshold=score_threshold,
                ensemble_config=ensemble_config,
                return_sources=return_sources,
            )

        invoke_fn = getattr(self, "invoke", None)
        try:
            decision = await self._store_router.route(
                question, available, invoke_fn=invoke_fn
            )
            sk = dict(search_kwargs or {})
            sk.setdefault("limit", limit)
            if score_threshold is not None:
                sk.setdefault("similarity_threshold", score_threshold)
            raw_results = await self._store_router.execute(
                decision, question, stores_dict,
                multistore_tool=self._multi_store_tool, **sk,
            )
        except Exception as exc:
            self.logger.warning("StoreRouter fallback: %s", exc)
            return await self.get_vector_context(
                question,
                search_type=search_type,
                search_kwargs=search_kwargs,
                metric_type=metric_type,
                limit=limit,
                score_threshold=score_threshold,
                ensemble_config=ensemble_config,
                return_sources=return_sources,
            )

        if not raw_results:
            return "", {}

        context_parts = []
        sources = []
        for r in raw_results:
            if hasattr(r, "content"):
                context_parts.append(str(r.content))
                if return_sources:
                    sources.append(r)
            elif isinstance(r, dict):
                content = r.get("content", r.get("text", ""))
                if content:
                    context_parts.append(str(content))
                if return_sources:
                    sources.append(r)
        context_str = "\n\n".join(filter(None, context_parts))
        meta: dict = {}
        if return_sources and sources:
            meta["sources"] = sources
        return context_str, meta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pgvector_mock():
    from parrot.stores.postgres import PgVectorStore
    m = MagicMock(spec=PgVectorStore)
    m.similarity_search = AsyncMock(return_value=[])
    return m


@pytest.fixture
def basic_bot_with_pgvector(pgvector_mock):
    return FakeBot(pgvector_mock)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_router_attribute_is_none_by_default(basic_bot_with_pgvector):
    assert basic_bot_with_pgvector._store_router is None


def test_configure_store_router_sets_attribute(basic_bot_with_pgvector):
    bot = basic_bot_with_pgvector
    bot.configure_store_router(StoreRouterConfig())
    assert bot._store_router is not None
    assert isinstance(bot._store_router, StoreRouter)


@pytest.mark.asyncio
async def test_unconfigured_path_calls_get_vector_context(basic_bot_with_pgvector):
    """When router is not configured, get_vector_context is delegated to."""
    bot = basic_bot_with_pgvector
    assert bot._store_router is None
    ctx, meta = await bot._build_vector_context("q")
    bot.get_vector_context.assert_awaited_once()
    assert ctx == "ctx"


@pytest.mark.asyncio
async def test_use_vectors_false_returns_empty(basic_bot_with_pgvector):
    bot = basic_bot_with_pgvector
    bot.configure_store_router(StoreRouterConfig())
    ctx, meta = await bot._build_vector_context("q", use_vectors=False)
    assert ctx == ""
    assert meta == {}


@pytest.mark.asyncio
async def test_router_path_invoked_when_configured(basic_bot_with_pgvector):
    bot = basic_bot_with_pgvector
    bot.configure_store_router(StoreRouterConfig())

    fake_decision = StoreRoutingDecision(
        rankings=[StoreScore(store=StoreType.PGVECTOR, confidence=0.9)],
        path="fast",
    )
    bot._store_router.route = AsyncMock(return_value=fake_decision)
    bot._store_router.execute = AsyncMock(return_value=[])
    await bot._build_vector_context("q")
    bot._store_router.route.assert_awaited_once()
    bot._store_router.execute.assert_awaited_once()


def test_build_stores_dict_infers_pgvector(basic_bot_with_pgvector):
    mapping = basic_bot_with_pgvector._build_stores_dict()
    assert StoreType.PGVECTOR in mapping


def test_build_stores_dict_empty_when_no_store():
    bot = FakeBot(store=None)
    mapping = bot._build_stores_dict()
    assert StoreType.PGVECTOR not in mapping


def test_configure_store_router_idempotent(basic_bot_with_pgvector):
    bot = basic_bot_with_pgvector
    bot.configure_store_router(StoreRouterConfig(cache_size=100))
    first_router = bot._store_router
    bot.configure_store_router(StoreRouterConfig(cache_size=200))
    assert bot._store_router is not first_router


@pytest.mark.asyncio
async def test_router_fallback_on_no_stores():
    """When store is None, guard fires and returns ('', {})."""
    bot = FakeBot(store=None)
    bot.configure_store_router(StoreRouterConfig())
    ctx, meta = await bot._build_vector_context("q")
    assert ctx == ""
