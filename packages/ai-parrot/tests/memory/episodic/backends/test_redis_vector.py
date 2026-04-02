"""Unit tests for RedisVectorBackend with mocked Redis."""
import json
import struct
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.memory.episodic.backends.redis_vector import (
    RedisVectorBackend,
    _embedding_to_bytes,
    _bytes_to_embedding,
    _episode_to_hash,
    _hash_to_episode,
)
from parrot.memory.episodic.models import (
    EpisodeCategory,
    EpisodeOutcome,
    EpisodicMemory,
    MemoryNamespace,
)


@pytest.fixture
def sample_episode() -> EpisodicMemory:
    """A sample episode with embedding."""
    return EpisodicMemory(
        agent_id="test-agent",
        tenant_id="tenant-1",
        situation="User asked about weather forecast for tomorrow",
        action_taken="Called weather API with location parameter",
        outcome=EpisodeOutcome.SUCCESS,
        outcome_details="Returned 5-day forecast",
        category=EpisodeCategory.TOOL_EXECUTION,
        related_tools=["weather_api"],
        embedding=[0.1] * 384,
    )


@pytest.fixture
def failure_episode() -> EpisodicMemory:
    """A failure episode."""
    return EpisodicMemory(
        agent_id="test-agent",
        tenant_id="tenant-1",
        situation="Database connection failed",
        action_taken="Retried with backoff",
        outcome=EpisodeOutcome.FAILURE,
        category=EpisodeCategory.ERROR_RECOVERY,
        is_failure=True,
        embedding=[0.5] * 384,
    )


@pytest.fixture
def mock_redis() -> AsyncMock:
    """A mocked Redis async client."""
    redis = AsyncMock()
    redis.hset = AsyncMock(return_value=1)
    redis.hgetall = AsyncMock(return_value={})
    redis.delete = AsyncMock(return_value=1)
    redis.execute_command = AsyncMock(return_value=[0])
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def backend(mock_redis: AsyncMock) -> RedisVectorBackend:
    """A RedisVectorBackend with mocked Redis client."""
    b = RedisVectorBackend(redis_url="redis://localhost:6379")
    b._redis = mock_redis
    return b


class TestEmbeddingRoundtrip:
    """Tests for embedding serialization utilities."""

    def test_embedding_to_bytes_and_back(self) -> None:
        """Round-trip embedding through bytes should preserve values."""
        original = [0.1, 0.5, -0.3, 0.0, 1.0]
        serialized = _embedding_to_bytes(original)
        restored = _bytes_to_embedding(serialized)
        assert len(restored) == len(original)
        for a, b in zip(original, restored):
            assert abs(a - b) < 1e-5

    def test_bytes_length(self) -> None:
        """Float32 bytes should be 4 bytes per element."""
        embedding = [0.1] * 384
        data = _embedding_to_bytes(embedding)
        assert len(data) == 384 * 4


class TestEpisodeHashSerialization:
    """Tests for episode hash serialization."""

    def test_episode_to_hash_contains_required_fields(
        self, sample_episode: EpisodicMemory
    ) -> None:
        """Hash must contain all required Redis fields."""
        h = _episode_to_hash(sample_episode)
        assert "episode_id" in h
        assert "agent_id" in h
        assert "tenant_id" in h
        assert "embedding" in h
        assert "outcome" in h
        assert "is_failure" in h
        assert "created_at" in h

    def test_episode_roundtrip(self, sample_episode: EpisodicMemory) -> None:
        """Serializing and deserializing should produce equivalent episode."""
        h = _episode_to_hash(sample_episode)
        # Simulate Redis returning bytes for string fields
        decoded = {}
        for k, v in h.items():
            if k == "embedding":
                decoded[k] = v  # keep as bytes
            elif isinstance(v, (int, float)):
                decoded[k] = str(v)
            else:
                decoded[k] = str(v)
        restored = _hash_to_episode(decoded)
        assert restored.episode_id == sample_episode.episode_id
        assert restored.agent_id == sample_episode.agent_id
        assert restored.outcome == sample_episode.outcome


class TestRedisVectorBackendStore:
    """Tests for RedisVectorBackend.store()."""

    async def test_store_episode_calls_hset(
        self, backend: RedisVectorBackend, sample_episode: EpisodicMemory, mock_redis: AsyncMock
    ) -> None:
        """store() should call redis.hset with the episode key."""
        result = await backend.store(sample_episode)
        mock_redis.hset.assert_called_once()
        call_kwargs = mock_redis.hset.call_args
        assert sample_episode.episode_id in str(call_kwargs)
        assert result == sample_episode.episode_id

    async def test_store_returns_episode_id(
        self, backend: RedisVectorBackend, sample_episode: EpisodicMemory
    ) -> None:
        """store() should return the episode_id."""
        result = await backend.store(sample_episode)
        assert result == sample_episode.episode_id

    async def test_store_graceful_on_redis_error(
        self, backend: RedisVectorBackend, sample_episode: EpisodicMemory, mock_redis: AsyncMock
    ) -> None:
        """store() should not raise on Redis connection error."""
        mock_redis.hset = AsyncMock(side_effect=ConnectionError("Redis down"))
        result = await backend.store(sample_episode)
        # Should return episode_id without raising
        assert result == sample_episode.episode_id

    async def test_store_without_configure_logs_warning(
        self, sample_episode: EpisodicMemory
    ) -> None:
        """store() without configure() should return episode_id without raising."""
        backend = RedisVectorBackend()
        result = await backend.store(sample_episode)
        assert result == sample_episode.episode_id


class TestRedisVectorBackendSearch:
    """Tests for RedisVectorBackend.search_similar()."""

    async def test_search_returns_list(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """search_similar() should always return a list."""
        # FT.SEARCH returns empty result
        mock_redis.execute_command = AsyncMock(return_value=[0])
        results = await backend.search_similar(
            embedding=[0.1] * 384,
            namespace_filter={"agent_id": "test-agent"},
            top_k=5,
        )
        assert isinstance(results, list)

    async def test_search_graceful_on_redis_error(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """search_similar() should return [] on Redis connection error."""
        mock_redis.execute_command = AsyncMock(side_effect=ConnectionError("Redis down"))
        results = await backend.search_similar(
            embedding=[0.1] * 384,
            namespace_filter={"agent_id": "test-agent"},
            top_k=5,
        )
        assert results == []

    async def test_search_without_configure_logs_warning(self) -> None:
        """search_similar() without configure() should return []."""
        backend = RedisVectorBackend()
        results = await backend.search_similar(
            embedding=[0.1] * 384,
            namespace_filter={"agent_id": "test-agent"},
        )
        assert results == []

    async def test_namespace_filtering_builds_query(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """Namespace filter fields should appear in the FT.SEARCH query."""
        mock_redis.execute_command = AsyncMock(return_value=[0])
        ns = MemoryNamespace(agent_id="agent-1", tenant_id="t1")
        await backend.search_similar(
            embedding=[0.1] * 384,
            namespace_filter=ns.build_filter(),
            top_k=5,
        )
        # Verify FT.SEARCH was called
        mock_redis.execute_command.assert_called_once()
        call_args = str(mock_redis.execute_command.call_args)
        assert "agent-1" in call_args or "agent_id" in call_args


class TestRedisVectorBackendGetRecent:
    """Tests for RedisVectorBackend.get_recent()."""

    async def test_get_recent_returns_list(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """get_recent() should return a list."""
        mock_redis.execute_command = AsyncMock(return_value=[0])
        results = await backend.get_recent(
            namespace_filter={"agent_id": "test-agent"},
            limit=10,
        )
        assert isinstance(results, list)

    async def test_get_recent_graceful_on_error(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """get_recent() should return [] on error."""
        mock_redis.execute_command = AsyncMock(side_effect=Exception("fail"))
        results = await backend.get_recent(
            namespace_filter={"agent_id": "test-agent"},
        )
        assert results == []


class TestRedisVectorBackendCount:
    """Tests for RedisVectorBackend.count()."""

    async def test_count_returns_int(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """count() should return an integer."""
        mock_redis.execute_command = AsyncMock(return_value=[42])
        result = await backend.count({"agent_id": "test-agent"})
        assert result == 42

    async def test_count_graceful_on_error(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """count() should return 0 on error."""
        mock_redis.execute_command = AsyncMock(side_effect=Exception("fail"))
        result = await backend.count({"agent_id": "test-agent"})
        assert result == 0

    async def test_count_without_configure(self) -> None:
        """count() without configure() should return 0."""
        backend = RedisVectorBackend()
        result = await backend.count({"agent_id": "test-agent"})
        assert result == 0


class TestRedisVectorBackendDeleteExpired:
    """Tests for RedisVectorBackend.delete_expired()."""

    async def test_delete_expired_returns_int(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """delete_expired() should return an integer."""
        mock_redis.execute_command = AsyncMock(return_value=[0])
        result = await backend.delete_expired()
        assert isinstance(result, int)

    async def test_delete_expired_graceful_on_error(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """delete_expired() should return 0 on error."""
        mock_redis.execute_command = AsyncMock(side_effect=Exception("fail"))
        result = await backend.delete_expired()
        assert result == 0


class TestRedisVectorBackendCleanup:
    """Tests for RedisVectorBackend.cleanup()."""

    async def test_cleanup_closes_redis(
        self, backend: RedisVectorBackend, mock_redis: AsyncMock
    ) -> None:
        """cleanup() should close the Redis connection."""
        await backend.cleanup()
        mock_redis.aclose.assert_called_once()
        assert backend._redis is None

    async def test_cleanup_idempotent(self) -> None:
        """cleanup() without configure() should not raise."""
        backend = RedisVectorBackend()
        await backend.cleanup()  # Should not raise
