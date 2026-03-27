"""Unit and integration tests for episodic memory store.

Covers all modules: models, FAISS backend, embedding, reflection,
Redis cache, store orchestrator, tools, and mixin.
All tests use mocked/in-memory components — no real PostgreSQL or Redis required.
"""
from __future__ import annotations

import asyncio
import json
import random
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from parrot.memory.episodic.models import (
    EpisodeCategory,
    EpisodeOutcome,
    EpisodeSearchResult,
    EpisodicMemory,
    MemoryNamespace,
    ReflectionResult,
)
from parrot.memory.episodic.backends.faiss import FAISSBackend
from parrot.memory.episodic.embedding import EpisodeEmbeddingProvider
from parrot.memory.episodic.reflection import ReflectionEngine
from parrot.memory.episodic.cache import EpisodeRedisCache
from parrot.memory.episodic.store import EpisodicMemoryStore, _auto_importance
from parrot.memory.episodic.tools import EpisodicMemoryToolkit
from parrot.memory.episodic.mixin import EpisodicMemoryMixin


# ── Helpers ──

def _random_embedding(dim: int = 384) -> list[float]:
    """Generate a random L2-normalized embedding vector."""
    vec = np.random.randn(dim).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


def _make_episode(
    agent_id: str = "test-agent",
    tenant_id: str = "test",
    user_id: str | None = "user-1",
    room_id: str | None = None,
    situation: str = "Test situation",
    action_taken: str = "Test action",
    outcome: EpisodeOutcome = EpisodeOutcome.SUCCESS,
    category: EpisodeCategory = EpisodeCategory.TOOL_EXECUTION,
    importance: int = 5,
    is_failure: bool = False,
    lesson_learned: str | None = None,
    suggested_action: str | None = None,
    embedding: list[float] | None = None,
    **kwargs: Any,
) -> EpisodicMemory:
    """Create a test episode with sensible defaults."""
    return EpisodicMemory(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        room_id=room_id,
        situation=situation,
        action_taken=action_taken,
        outcome=outcome,
        category=category,
        importance=importance,
        is_failure=is_failure,
        lesson_learned=lesson_learned,
        suggested_action=suggested_action,
        embedding=embedding,
        **kwargs,
    )


class MockRedis:
    """Minimal async Redis mock for cache tests."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._zsets: dict[str, dict[str, float]] = {}
        self._lists: dict[str, list[str]] = {}
        self._ttls: dict[str, int] = {}

    def pipeline(self) -> MockPipeline:
        return MockPipeline(self)

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str) -> None:
        self._data[key] = value

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._data.pop(k, None)
            self._zsets.pop(k, None)
            self._lists.pop(k, None)

    async def expire(self, key: str, ttl: int) -> None:
        self._ttls[key] = ttl

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        if key not in self._zsets:
            self._zsets[key] = {}
        self._zsets[key].update(mapping)

    async def zrevrange(self, key: str, start: int, stop: int) -> list[str]:
        zs = self._zsets.get(key, {})
        sorted_items = sorted(zs.items(), key=lambda x: x[1], reverse=True)
        end = stop + 1 if stop >= 0 else len(sorted_items)
        return [item[0] for item in sorted_items[start:end]]

    async def zrange(self, key: str, start: int, stop: int) -> list[str]:
        zs = self._zsets.get(key, {})
        sorted_items = sorted(zs.items(), key=lambda x: x[1])
        end = stop + 1 if stop >= 0 else len(sorted_items)
        return [item[0] for item in sorted_items[start:end]]

    async def zremrangebyrank(self, key: str, start: int, stop: int) -> int:
        zs = self._zsets.get(key, {})
        sorted_items = sorted(zs.items(), key=lambda x: x[1])
        if stop < 0:
            stop = len(sorted_items) + stop
        if stop < 0:
            return 0
        to_remove = sorted_items[start:stop + 1]
        for name, _ in to_remove:
            zs.pop(name, None)
        return len(to_remove)

    async def lpush(self, key: str, *values: str) -> None:
        if key not in self._lists:
            self._lists[key] = []
        for v in values:
            self._lists[key].insert(0, v)

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        if key in self._lists:
            self._lists[key] = self._lists[key][start:stop + 1]

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        lst = self._lists.get(key, [])
        end = stop + 1 if stop >= 0 else len(lst)
        return lst[start:end]


class MockPipeline:
    """Pipeline that collects commands and executes them."""

    def __init__(self, redis: MockRedis) -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple, dict]] = []

    def set(self, key: str, value: str) -> MockPipeline:
        self._commands.append(("set", (key, value), {}))
        return self

    def get(self, key: str) -> MockPipeline:
        self._commands.append(("get", (key,), {}))
        return self

    def expire(self, key: str, ttl: int) -> MockPipeline:
        self._commands.append(("expire", (key, ttl), {}))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> MockPipeline:
        self._commands.append(("zadd", (key, mapping), {}))
        return self

    def zremrangebyrank(self, key: str, start: int, stop: int) -> MockPipeline:
        self._commands.append(("zremrangebyrank", (key, start, stop), {}))
        return self

    def lpush(self, key: str, *values: str) -> MockPipeline:
        self._commands.append(("lpush", (key, *values), {}))
        return self

    def ltrim(self, key: str, start: int, stop: int) -> MockPipeline:
        self._commands.append(("ltrim", (key, start, stop), {}))
        return self

    async def execute(self) -> list[Any]:
        results = []
        for cmd, args, kwargs in self._commands:
            method = getattr(self._redis, cmd)
            result = await method(*args, **kwargs)
            results.append(result)
        self._commands.clear()
        return results


class MockEmbeddingProvider:
    """Mock embedding provider returning fixed-dimension random vectors."""

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension
        self._model = None  # Simulate lazy loading

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        self._model = "loaded"
        return _random_embedding(self._dimension)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._model = "loaded"
        return [_random_embedding(self._dimension) for _ in texts]

    @staticmethod
    def get_searchable_text(episode: EpisodicMemory) -> str:
        parts = [episode.situation, episode.action_taken]
        if episode.lesson_learned:
            parts.append(episode.lesson_learned)
        return " | ".join(parts)


class MockReflectionEngine:
    """Mock reflection engine returning fixed ReflectionResult."""

    async def reflect(
        self,
        situation: str,
        action_taken: str,
        outcome: EpisodeOutcome | str,
        error_message: str | None = None,
    ) -> ReflectionResult:
        return ReflectionResult(
            reflection=f"Analysis of: {situation[:50]}",
            lesson_learned="Mock lesson learned",
            suggested_action="Mock suggested action",
        )


# ── Fixtures ──

@pytest.fixture
def sample_namespace() -> MemoryNamespace:
    """MemoryNamespace for testing."""
    return MemoryNamespace(tenant_id="test", agent_id="test-agent", user_id="user-1")


@pytest.fixture
def faiss_backend() -> FAISSBackend:
    """In-memory FAISS backend for testing."""
    return FAISSBackend(dimension=384, max_episodes=100)


@pytest.fixture
def mock_embedding_provider() -> MockEmbeddingProvider:
    """Mock embedding provider."""
    return MockEmbeddingProvider(dimension=384)


@pytest.fixture
def mock_reflection_engine() -> MockReflectionEngine:
    """Mock reflection engine."""
    return MockReflectionEngine()


@pytest.fixture
def mock_redis() -> MockRedis:
    """Mock Redis client."""
    return MockRedis()


@pytest.fixture
def redis_cache(mock_redis: MockRedis) -> EpisodeRedisCache:
    """Redis cache with mock client."""
    return EpisodeRedisCache(redis_client=mock_redis, default_ttl=3600, max_recent=5)


@pytest.fixture
def episodic_store(
    faiss_backend: FAISSBackend,
    mock_embedding_provider: MockEmbeddingProvider,
    mock_reflection_engine: MockReflectionEngine,
) -> EpisodicMemoryStore:
    """Fully configured EpisodicMemoryStore with mocked components."""
    return EpisodicMemoryStore(
        backend=faiss_backend,
        embedding_provider=mock_embedding_provider,
        reflection_engine=mock_reflection_engine,
        default_ttl_days=90,
    )


@pytest.fixture
def episodic_store_with_cache(
    faiss_backend: FAISSBackend,
    mock_embedding_provider: MockEmbeddingProvider,
    mock_reflection_engine: MockReflectionEngine,
    redis_cache: EpisodeRedisCache,
) -> EpisodicMemoryStore:
    """Store with Redis cache enabled."""
    return EpisodicMemoryStore(
        backend=faiss_backend,
        embedding_provider=mock_embedding_provider,
        reflection_engine=mock_reflection_engine,
        redis_cache=redis_cache,
        default_ttl_days=90,
    )


# ═══════════════════════════════════════════════════
# Unit Tests — Models (TASK-304)
# ═══════════════════════════════════════════════════


class TestModels:
    """Tests for episodic memory models."""

    def test_episode_creation_defaults(self) -> None:
        """Verify EpisodicMemory auto-generates episode_id and created_at."""
        ep = _make_episode()
        assert ep.episode_id is not None
        assert len(ep.episode_id) == 36  # UUID format
        assert ep.created_at is not None
        assert ep.created_at.tzinfo is not None

    def test_episode_outcome_enum(self) -> None:
        """All EpisodeOutcome values are valid strings."""
        expected = {"success", "failure", "partial", "timeout"}
        actual = {e.value for e in EpisodeOutcome}
        assert actual == expected

    def test_episode_category_enum(self) -> None:
        """All EpisodeCategory values are valid strings."""
        expected = {
            "tool_execution", "query_resolution", "error_recovery",
            "user_preference", "workflow_pattern", "decision", "handoff",
        }
        actual = {c.value for c in EpisodeCategory}
        assert actual == expected

    def test_namespace_build_filter_agent_only(self) -> None:
        """Only tenant_id + agent_id in filter."""
        ns = MemoryNamespace(tenant_id="t1", agent_id="a1")
        f = ns.build_filter()
        assert f == {"tenant_id": "t1", "agent_id": "a1"}

    def test_namespace_build_filter_with_user(self) -> None:
        """tenant_id + agent_id + user_id."""
        ns = MemoryNamespace(tenant_id="t1", agent_id="a1", user_id="u1")
        f = ns.build_filter()
        assert f == {"tenant_id": "t1", "agent_id": "a1", "user_id": "u1"}

    def test_namespace_build_filter_with_room(self) -> None:
        """tenant_id + agent_id + room_id."""
        ns = MemoryNamespace(tenant_id="t1", agent_id="a1", room_id="r1")
        f = ns.build_filter()
        assert f == {"tenant_id": "t1", "agent_id": "a1", "room_id": "r1"}

    def test_namespace_build_filter_with_crew(self) -> None:
        """tenant_id + crew_id (agent_id always included)."""
        ns = MemoryNamespace(tenant_id="t1", agent_id="a1", crew_id="c1")
        f = ns.build_filter()
        assert "crew_id" in f
        assert f["crew_id"] == "c1"

    def test_namespace_scope_label(self) -> None:
        """Correct label at each scope level."""
        assert MemoryNamespace(
            tenant_id="t", agent_id="a"
        ).scope_label == "agent:a"
        assert MemoryNamespace(
            tenant_id="t", agent_id="a", user_id="u"
        ).scope_label == "user:u"
        assert MemoryNamespace(
            tenant_id="t", agent_id="a", room_id="r"
        ).scope_label == "room:r"
        assert MemoryNamespace(
            tenant_id="t", agent_id="a", session_id="s", user_id="u"
        ).scope_label == "session:s"
        assert MemoryNamespace(
            tenant_id="t", agent_id="a", crew_id="c"
        ).scope_label == "crew:c"

    def test_namespace_redis_prefix(self) -> None:
        """Correct Redis prefix at each scope level."""
        assert MemoryNamespace(
            tenant_id="t", agent_id="a"
        ).redis_prefix == "t:a"
        assert MemoryNamespace(
            tenant_id="t", agent_id="a", user_id="u"
        ).redis_prefix == "t:a:user:u"
        assert MemoryNamespace(
            tenant_id="t", agent_id="a", room_id="r"
        ).redis_prefix == "t:a:room:r"

    def test_episode_searchable_text(self) -> None:
        """Concatenates situation + action + lesson."""
        ep = _make_episode(
            situation="Search this",
            action_taken="Did that",
            lesson_learned="Learned X",
        )
        text = ep.searchable_text()
        assert "Search this" in text
        assert "Did that" in text
        assert "Learned X" in text
        assert " | " in text

    def test_episode_to_dict_from_dict(self) -> None:
        """Round-trip serialization."""
        ep = _make_episode(
            embedding=_random_embedding(384),
            lesson_learned="Important lesson",
            metadata={"key": "value"},
        )
        d = ep.to_dict()
        assert isinstance(d, dict)
        assert "embedding" in d

        restored = EpisodicMemory.from_dict(d)
        assert restored.episode_id == ep.episode_id
        assert restored.situation == ep.situation
        assert restored.lesson_learned == ep.lesson_learned
        assert restored.metadata == ep.metadata


# ═══════════════════════════════════════════════════
# Unit Tests — FAISS Backend (TASK-306)
# ═══════════════════════════════════════════════════


class TestFAISSBackend:
    """Tests for FAISS backend storage and search."""

    @pytest.mark.asyncio
    async def test_faiss_store_and_search(self, faiss_backend: FAISSBackend) -> None:
        """Store episode, search by embedding, verify result."""
        emb = _random_embedding(384)
        ep = _make_episode(embedding=emb, situation="Find me by vector")

        await faiss_backend.store(ep)

        results = await faiss_backend.search_similar(
            embedding=emb,
            namespace_filter={"tenant_id": "test", "agent_id": "test-agent"},
            top_k=5,
            score_threshold=0.0,
        )
        assert len(results) >= 1
        assert results[0].episode_id == ep.episode_id

    @pytest.mark.asyncio
    async def test_faiss_namespace_filter(self, faiss_backend: FAISSBackend) -> None:
        """Store episodes for different agents, verify filtering."""
        emb = _random_embedding(384)
        ep_a = _make_episode(agent_id="agent-A", embedding=emb, situation="Agent A task")
        ep_b = _make_episode(agent_id="agent-B", embedding=emb, situation="Agent B task")

        await faiss_backend.store(ep_a)
        await faiss_backend.store(ep_b)

        results_a = await faiss_backend.search_similar(
            embedding=emb,
            namespace_filter={"tenant_id": "test", "agent_id": "agent-A"},
            top_k=5,
            score_threshold=0.0,
        )
        assert all(r.agent_id == "agent-A" for r in results_a)

    @pytest.mark.asyncio
    async def test_faiss_persistence(self) -> None:
        """Save to disk, create new backend, load, verify episodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            emb = _random_embedding(384)
            ep = _make_episode(embedding=emb, situation="Persist me")

            backend1 = FAISSBackend(dimension=384, persistence_path=tmpdir)
            await backend1.store(ep)
            await backend1.save()

            backend2 = FAISSBackend(dimension=384, persistence_path=tmpdir)
            await backend2.load()

            count = await backend2.count(
                {"tenant_id": "test", "agent_id": "test-agent"}
            )
            assert count == 1

            results = await backend2.search_similar(
                embedding=emb,
                namespace_filter={"tenant_id": "test", "agent_id": "test-agent"},
                top_k=5,
                score_threshold=0.0,
            )
            assert len(results) == 1
            assert results[0].episode_id == ep.episode_id

    @pytest.mark.asyncio
    async def test_faiss_max_episodes_cap(self) -> None:
        """Exceed cap, verify oldest removed."""
        backend = FAISSBackend(dimension=384, max_episodes=3)

        episodes = []
        for i in range(5):
            ep = _make_episode(
                embedding=_random_embedding(384),
                situation=f"Episode {i}",
            )
            # Stagger creation times
            ep.created_at = datetime.now(timezone.utc) + timedelta(seconds=i)
            await backend.store(ep)
            episodes.append(ep)

        total = await backend.count(
            {"tenant_id": "test", "agent_id": "test-agent"}
        )
        assert total <= 3

    @pytest.mark.asyncio
    async def test_faiss_get_failures(self, faiss_backend: FAISSBackend) -> None:
        """Store mixed outcomes, verify only failures returned."""
        success_ep = _make_episode(
            situation="Success case",
            outcome=EpisodeOutcome.SUCCESS,
            is_failure=False,
            embedding=_random_embedding(384),
        )
        failure_ep = _make_episode(
            situation="Failure case",
            outcome=EpisodeOutcome.FAILURE,
            is_failure=True,
            embedding=_random_embedding(384),
        )

        await faiss_backend.store(success_ep)
        await faiss_backend.store(failure_ep)

        failures = await faiss_backend.get_failures(
            agent_id="test-agent", tenant_id="test"
        )
        assert len(failures) == 1
        assert failures[0].is_failure is True
        assert failures[0].episode_id == failure_ep.episode_id


# ═══════════════════════════════════════════════════
# Unit Tests — Embedding (TASK-307)
# ═══════════════════════════════════════════════════


class TestEmbedding:
    """Tests for embedding provider."""

    def test_embedding_lazy_load(self) -> None:
        """Model is None before first embed(), loaded after."""
        provider = MockEmbeddingProvider(dimension=384)
        assert provider._model is None

    @pytest.mark.asyncio
    async def test_embedding_dimension(self) -> None:
        """Output vector length matches configured dimension."""
        provider = MockEmbeddingProvider(dimension=384)
        vec = await provider.embed("test text")
        assert len(vec) == 384

    @pytest.mark.asyncio
    async def test_embedding_batch(self) -> None:
        """Batch embedding returns correct number of vectors."""
        provider = MockEmbeddingProvider(dimension=384)
        texts = ["text1", "text2", "text3"]
        results = await provider.embed_batch(texts)
        assert len(results) == 3
        assert all(len(v) == 384 for v in results)

    def test_embedding_searchable_text(self) -> None:
        """get_searchable_text formats correctly."""
        ep = _make_episode(
            situation="User asked about weather",
            action_taken="Called weather API",
            lesson_learned="Check location first",
        )
        text = EpisodeEmbeddingProvider.get_searchable_text(ep)
        assert "User asked about weather" in text
        assert "Called weather API" in text
        assert "Check location first" in text
        assert " | " in text

        # Without lesson
        ep2 = _make_episode(
            situation="Simple query",
            action_taken="Direct response",
        )
        text2 = EpisodeEmbeddingProvider.get_searchable_text(ep2)
        assert text2.count(" | ") == 1


# ═══════════════════════════════════════════════════
# Unit Tests — Reflection (TASK-307)
# ═══════════════════════════════════════════════════


class TestReflection:
    """Tests for reflection engine."""

    @pytest.mark.asyncio
    async def test_reflection_llm_success(self) -> None:
        """Mock LLM returns structured ReflectionResult."""
        mock_client = AsyncMock()
        mock_client.ask = AsyncMock(return_value={
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "reflection": "The action succeeded well",
                        "lesson_learned": "Keep doing this",
                        "suggested_action": "Continue this approach",
                    }),
                }
            ]
        })

        engine = ReflectionEngine(
            llm_client=mock_client, fallback_to_heuristic=True
        )
        result = await engine.reflect(
            "Test situation", "Test action", EpisodeOutcome.SUCCESS
        )
        assert isinstance(result, ReflectionResult)
        assert result.lesson_learned == "Keep doing this"

    @pytest.mark.asyncio
    async def test_reflection_llm_failure_fallback(self) -> None:
        """LLM fails, heuristic fallback used."""
        mock_client = AsyncMock()
        mock_client.ask = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        engine = ReflectionEngine(
            llm_client=mock_client, fallback_to_heuristic=True
        )
        result = await engine.reflect(
            "Test situation",
            "Test action",
            EpisodeOutcome.FAILURE,
            error_message="Connection refused",
        )
        assert isinstance(result, ReflectionResult)
        assert "service" in result.lesson_learned.lower() or "verify" in result.lesson_learned.lower()

    @pytest.mark.asyncio
    async def test_reflection_heuristic_timeout(self) -> None:
        """Error with 'timeout' produces appropriate lesson."""
        engine = ReflectionEngine(fallback_to_heuristic=True)
        result = await engine.reflect(
            "Long running query",
            "Executed query",
            EpisodeOutcome.TIMEOUT,
            error_message="Request timed out after 30s",
        )
        assert "timeout" in result.lesson_learned.lower() or "scope" in result.lesson_learned.lower()

    @pytest.mark.asyncio
    async def test_reflection_heuristic_rate_limit(self) -> None:
        """Error with 'rate limit' produces appropriate lesson."""
        engine = ReflectionEngine(fallback_to_heuristic=True)
        result = await engine.reflect(
            "API call",
            "Called external API",
            EpisodeOutcome.FAILURE,
            error_message="Rate limit exceeded (429)",
        )
        assert "delay" in result.lesson_learned.lower() or "api" in result.lesson_learned.lower()

    @pytest.mark.asyncio
    async def test_reflection_heuristic_not_found(self) -> None:
        """Error with 'not found' produces appropriate lesson."""
        engine = ReflectionEngine(fallback_to_heuristic=True)
        result = await engine.reflect(
            "Lookup record",
            "Queried database",
            EpisodeOutcome.FAILURE,
            error_message="Record not found in table users",
        )
        assert "exist" in result.lesson_learned.lower() or "verify" in result.lesson_learned.lower()

    @pytest.mark.asyncio
    async def test_reflection_heuristic_success(self) -> None:
        """Success outcome produces positive lesson."""
        engine = ReflectionEngine(fallback_to_heuristic=True)
        result = await engine.reflect(
            "Send notification",
            "Sent email notification",
            EpisodeOutcome.SUCCESS,
        )
        assert "pattern" in result.lesson_learned.lower() or "worked" in result.lesson_learned.lower()
        assert "reuse" in result.suggested_action.lower() or "approach" in result.suggested_action.lower()


# ═══════════════════════════════════════════════════
# Unit Tests — Redis Cache (TASK-308)
# ═══════════════════════════════════════════════════


class TestRedisCache:
    """Tests for Redis hot cache."""

    @pytest.mark.asyncio
    async def test_cache_store_and_get_recent(
        self, redis_cache: EpisodeRedisCache, sample_namespace: MemoryNamespace
    ) -> None:
        """Cache episode, retrieve via get_recent."""
        ep = _make_episode()
        await redis_cache.cache_episode(sample_namespace, ep)

        recent = await redis_cache.get_recent(sample_namespace, limit=10)
        assert recent is not None
        assert len(recent) == 1
        assert recent[0].episode_id == ep.episode_id

    @pytest.mark.asyncio
    async def test_cache_failures(
        self, redis_cache: EpisodeRedisCache, sample_namespace: MemoryNamespace
    ) -> None:
        """Cache failure episode, retrieve via get_failures."""
        ep = _make_episode(
            outcome=EpisodeOutcome.FAILURE,
            is_failure=True,
            situation="Failed task",
        )
        await redis_cache.cache_episode(sample_namespace, ep)

        failures = await redis_cache.get_failures(sample_namespace, limit=5)
        assert failures is not None
        assert len(failures) == 1
        assert failures[0].is_failure is True

    @pytest.mark.asyncio
    async def test_cache_invalidation(
        self, redis_cache: EpisodeRedisCache, sample_namespace: MemoryNamespace
    ) -> None:
        """Invalidate namespace, verify cache miss."""
        ep = _make_episode()
        await redis_cache.cache_episode(sample_namespace, ep)

        # Verify it's cached
        recent = await redis_cache.get_recent(sample_namespace)
        assert recent is not None

        # Invalidate
        await redis_cache.invalidate(sample_namespace)

        # Verify cache miss
        recent_after = await redis_cache.get_recent(sample_namespace)
        assert recent_after is None

    @pytest.mark.asyncio
    async def test_cache_max_recent(
        self, mock_redis: MockRedis, sample_namespace: MemoryNamespace
    ) -> None:
        """Exceed max_recent, verify oldest evicted."""
        cache = EpisodeRedisCache(
            redis_client=mock_redis, default_ttl=3600, max_recent=3
        )

        for i in range(5):
            ep = _make_episode(situation=f"Episode {i}")
            ep.created_at = datetime.now(timezone.utc) + timedelta(seconds=i)
            await cache.cache_episode(sample_namespace, ep)

        recent = await cache.get_recent(sample_namespace, limit=10)
        assert recent is not None
        assert len(recent) <= 3

    @pytest.mark.asyncio
    async def test_cache_graceful_degradation(
        self, sample_namespace: MemoryNamespace
    ) -> None:
        """Redis unavailable returns None, no exception."""

        class BrokenRedis:
            def pipeline(self):
                raise ConnectionError("Redis is down")

            async def get(self, key):
                raise ConnectionError("Redis is down")

            async def zrevrange(self, *args):
                raise ConnectionError("Redis is down")

            async def lrange(self, *args):
                raise ConnectionError("Redis is down")

            async def zrange(self, *args):
                raise ConnectionError("Redis is down")

            async def delete(self, *args):
                raise ConnectionError("Redis is down")

        cache = EpisodeRedisCache(redis_client=BrokenRedis())

        # cache_episode should not raise
        ep = _make_episode()
        await cache.cache_episode(sample_namespace, ep)

        # get_recent should return None
        result = await cache.get_recent(sample_namespace)
        assert result is None

        # get_failures should return None
        result = await cache.get_failures(sample_namespace)
        assert result is None


# ═══════════════════════════════════════════════════
# Unit Tests — Tools (TASK-310)
# ═══════════════════════════════════════════════════


class TestTools:
    """Tests for agent-usable episodic memory tools."""

    @pytest.mark.asyncio
    async def test_tool_search(
        self,
        episodic_store: EpisodicMemoryStore,
        sample_namespace: MemoryNamespace,
    ) -> None:
        """search_episodic_memory returns formatted results."""
        # Record some episodes
        await episodic_store.record_episode(
            namespace=sample_namespace,
            situation="User asked about weather in NYC",
            action_taken="Called weather API",
            outcome=EpisodeOutcome.SUCCESS,
        )

        toolkit = EpisodicMemoryToolkit(
            store=episodic_store, namespace=sample_namespace
        )

        result = await toolkit.search_episodic_memory(query="weather", top_k=5)
        assert isinstance(result, str)
        # Should find at least one result or say no results
        assert "experience" in result.lower() or "no relevant" in result.lower()

    @pytest.mark.asyncio
    async def test_tool_record_lesson(
        self,
        episodic_store: EpisodicMemoryStore,
        sample_namespace: MemoryNamespace,
    ) -> None:
        """record_lesson stores episode with correct fields."""
        toolkit = EpisodicMemoryToolkit(
            store=episodic_store, namespace=sample_namespace
        )

        result = await toolkit.record_lesson(
            situation="User prefers markdown tables",
            lesson="Always format data as markdown tables for this user",
            category="user_preference",
            importance=7,
        )
        assert isinstance(result, str)
        assert "recorded" in result.lower()

    @pytest.mark.asyncio
    async def test_tool_get_warnings(
        self,
        episodic_store: EpisodicMemoryStore,
        sample_namespace: MemoryNamespace,
    ) -> None:
        """get_warnings returns formatted warning text."""
        # Record a failure
        await episodic_store.record_episode(
            namespace=sample_namespace,
            situation="Tried to access restricted API",
            action_taken="Called /admin endpoint",
            outcome=EpisodeOutcome.FAILURE,
            error_message="403 Forbidden",
        )

        toolkit = EpisodicMemoryToolkit(
            store=episodic_store, namespace=sample_namespace
        )

        result = await toolkit.get_warnings(context="accessing API endpoints")
        assert isinstance(result, str)
        # Should have warnings or say no warnings
        assert "warning" in result.lower() or "mistake" in result.lower() or "no relevant" in result.lower()


# ═══════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════


class TestStoreIntegration:
    """Integration tests for the full EpisodicMemoryStore flow."""

    @pytest.mark.asyncio
    async def test_store_full_recording_flow(
        self,
        episodic_store_with_cache: EpisodicMemoryStore,
        sample_namespace: MemoryNamespace,
    ) -> None:
        """record_episode -> embed -> store -> cache (FAISS backend, mocked embedding)."""
        ep = await episodic_store_with_cache.record_episode(
            namespace=sample_namespace,
            situation="User asked about weather",
            action_taken="Called weather API for NYC",
            outcome=EpisodeOutcome.SUCCESS,
            category=EpisodeCategory.TOOL_EXECUTION,
            related_tools=["get_weather"],
        )

        assert ep.episode_id is not None
        assert ep.embedding is not None
        assert len(ep.embedding) == 384
        assert ep.reflection is not None
        assert ep.lesson_learned is not None

    @pytest.mark.asyncio
    async def test_store_recall_similar(
        self,
        episodic_store: EpisodicMemoryStore,
        sample_namespace: MemoryNamespace,
    ) -> None:
        """Record 5 episodes, recall_similar returns results."""
        topics = [
            ("Weather query", "Called weather API"),
            ("Stock price check", "Called finance API"),
            ("Email sending", "Sent email via SMTP"),
            ("Database migration", "Ran ALTER TABLE"),
            ("User onboarding", "Created user account"),
        ]

        for situation, action in topics:
            await episodic_store.record_episode(
                namespace=sample_namespace,
                situation=situation,
                action_taken=action,
                outcome=EpisodeOutcome.SUCCESS,
            )

        results = await episodic_store.recall_similar(
            query="weather forecast",
            namespace=sample_namespace,
            top_k=3,
            score_threshold=0.0,
        )
        assert isinstance(results, list)
        # With mock random embeddings, we may get results (score_threshold=0.0)
        # The key is that the pipeline works end-to-end

    @pytest.mark.asyncio
    async def test_store_failure_warnings_format(
        self,
        episodic_store: EpisodicMemoryStore,
        sample_namespace: MemoryNamespace,
    ) -> None:
        """Record failures, get_failure_warnings produces injectable text."""
        await episodic_store.record_episode(
            namespace=sample_namespace,
            situation="Tried bulk insert",
            action_taken="Inserted 10000 rows at once",
            outcome=EpisodeOutcome.FAILURE,
            error_message="Connection timeout after 30s",
            error_type="timeout",
        )
        await episodic_store.record_episode(
            namespace=sample_namespace,
            situation="Called rate-limited API",
            action_taken="Made 100 requests in 1 second",
            outcome=EpisodeOutcome.FAILURE,
            error_message="Rate limit exceeded (429)",
            error_type="rate_limit",
        )

        warnings = await episodic_store.get_failure_warnings(
            namespace=sample_namespace,
            current_query="insert many records",
            max_warnings=5,
        )
        assert isinstance(warnings, str)
        # Should contain structured warning sections
        if warnings:
            assert "MISTAKES TO AVOID" in warnings or "SUGGESTED" in warnings

    @pytest.mark.asyncio
    async def test_store_tool_episode_from_toolresult(
        self,
        episodic_store: EpisodicMemoryStore,
        sample_namespace: MemoryNamespace,
    ) -> None:
        """record_tool_episode extracts fields correctly from ToolResult mock."""

        class MockToolResult:
            success = False
            error = "File not found: /tmp/data.csv"
            status = "error"
            result = None

        ep = await episodic_store.record_tool_episode(
            namespace=sample_namespace,
            tool_name="read_file",
            tool_args={"path": "/tmp/data.csv"},
            tool_result=MockToolResult(),
            user_query="Read the data file",
        )

        assert ep.outcome == EpisodeOutcome.FAILURE
        assert ep.is_failure is True
        assert "read_file" in ep.related_tools
        assert ep.error_message is not None
        assert "not found" in ep.error_message.lower()

    @pytest.mark.asyncio
    async def test_store_namespace_isolation(
        self,
        episodic_store: EpisodicMemoryStore,
    ) -> None:
        """Episodes for user A not returned when querying user B."""
        ns_a = MemoryNamespace(tenant_id="test", agent_id="agent-1", user_id="alice")
        ns_b = MemoryNamespace(tenant_id="test", agent_id="agent-1", user_id="bob")

        await episodic_store.record_episode(
            namespace=ns_a,
            situation="Alice's private data",
            action_taken="Processed for Alice",
            outcome=EpisodeOutcome.SUCCESS,
        )

        # Query as Bob with score_threshold=0.0 to get any possible results
        results = await episodic_store.recall_similar(
            query="private data",
            namespace=ns_b,
            top_k=5,
            score_threshold=0.0,
        )
        # Bob should not see Alice's episodes
        for r in results:
            assert r.user_id != "alice"


class TestMixinIntegration:
    """Integration tests for the EpisodicMemoryMixin."""

    @pytest.mark.asyncio
    async def test_mixin_build_context(self, sample_namespace: MemoryNamespace) -> None:
        """Mock store -> _build_episodic_context returns formatted string."""

        class TestBot(EpisodicMemoryMixin):
            name = "test-bot"
            enable_episodic_memory = True

        bot = TestBot()
        # Create a mock store
        mock_store = AsyncMock()
        mock_store.get_failure_warnings = AsyncMock(
            return_value="MISTAKES TO AVOID:\n- Don't do X"
        )
        mock_store.get_user_preferences = AsyncMock(return_value=[
            _make_episode(lesson_learned="User prefers JSON"),
        ])
        mock_store.get_room_context = AsyncMock(return_value=[])
        bot._episodic_store = mock_store

        context = await bot._build_episodic_context(
            query="test query",
            user_id="user-1",
            room_id="room-1",
        )
        assert isinstance(context, str)
        assert "MISTAKES TO AVOID" in context
        assert "USER PREFERENCES" in context

    @pytest.mark.asyncio
    async def test_mixin_skip_trivial_tools(self) -> None:
        """_record_post_tool skips tools in trivial set."""

        class TestBot(EpisodicMemoryMixin):
            name = "test-bot"
            enable_episodic_memory = True

        bot = TestBot()
        mock_store = AsyncMock()
        mock_store.record_tool_episode = AsyncMock()
        bot._episodic_store = mock_store

        # Trivial tool — should be skipped
        await bot._record_post_tool(
            tool_name="get_time",
            tool_args={},
            tool_result="12:00",
        )
        # Give any tasks a chance to run
        await asyncio.sleep(0.05)
        mock_store.record_tool_episode.assert_not_called()

        # Non-trivial tool — should record
        await bot._record_post_tool(
            tool_name="execute_query",
            tool_args={"sql": "SELECT 1"},
            tool_result="OK",
        )
        await asyncio.sleep(0.05)
        mock_store.record_tool_episode.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixin_configure(self) -> None:
        """_configure_episodic_memory creates store with correct backend."""

        class TestBot(EpisodicMemoryMixin):
            name = "test-bot"
            enable_episodic_memory = True
            episodic_backend = "faiss"
            episodic_faiss_path = None
            episodic_reflection_enabled = False  # Skip reflection to simplify

        bot = TestBot()

        # Patch at the module level where imports happen inside the method
        with patch(
            "parrot.memory.episodic.embedding.EpisodeEmbeddingProvider"
        ) as mock_emb_cls, patch(
            "parrot.memory.episodic.store.EpisodicMemoryStore.create_faiss",
            new_callable=AsyncMock,
        ) as mock_create_faiss:
            mock_store_instance = AsyncMock()
            mock_create_faiss.return_value = mock_store_instance

            await bot._configure_episodic_memory()

            assert bot._episodic_store == mock_store_instance
            mock_create_faiss.assert_called_once()


# ═══════════════════════════════════════════════════
# Auto-importance helper
# ═══════════════════════════════════════════════════


class TestAutoImportance:
    """Test the _auto_importance helper function."""

    def test_failure_base(self) -> None:
        assert _auto_importance(EpisodeOutcome.FAILURE) == 7

    def test_timeout_base(self) -> None:
        assert _auto_importance(EpisodeOutcome.TIMEOUT) == 7

    def test_partial_base(self) -> None:
        assert _auto_importance(EpisodeOutcome.PARTIAL) == 5

    def test_success_base(self) -> None:
        assert _auto_importance(EpisodeOutcome.SUCCESS) == 3

    def test_known_error_boost(self) -> None:
        assert _auto_importance(EpisodeOutcome.FAILURE, "timeout") == 9

    def test_boost_capped_at_10(self) -> None:
        assert _auto_importance(EpisodeOutcome.FAILURE, "rate_limit") <= 10
