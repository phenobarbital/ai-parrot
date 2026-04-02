"""Tests for EpisodicMemoryStore scorer/strategy injection points."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.memory.episodic.models import (
    EpisodeCategory,
    EpisodeOutcome,
    EpisodeSearchResult,
    MemoryNamespace,
)
from parrot.memory.episodic.recall import SemanticOnlyStrategy
from parrot.memory.episodic.scoring import HeuristicScorer, ValueScorer
from parrot.memory.episodic.store import EpisodicMemoryStore


@pytest.fixture
def mock_backend() -> AsyncMock:
    """A mocked episode backend."""
    backend = AsyncMock()
    backend.store = AsyncMock(return_value="ep-123")
    backend.search_similar = AsyncMock(return_value=[])
    backend.get_recent = AsyncMock(return_value=[])
    backend.get_failures = AsyncMock(return_value=[])
    backend.count = AsyncMock(return_value=0)
    backend.delete_expired = AsyncMock(return_value=0)
    return backend


@pytest.fixture
def mock_embedding_provider() -> AsyncMock:
    """A mocked embedding provider."""
    provider = AsyncMock()
    provider.embed = AsyncMock(return_value=[0.1] * 384)
    return provider


@pytest.fixture
def namespace() -> MemoryNamespace:
    """A default namespace."""
    return MemoryNamespace(agent_id="test-agent", tenant_id="default")


class TestDefaultBehaviorUnchanged:
    """Tests verifying default behavior without scorer/strategy is unchanged."""

    def test_store_constructs_without_scorer_strategy(
        self, mock_backend: AsyncMock, mock_embedding_provider: AsyncMock
    ) -> None:
        """EpisodicMemoryStore should construct without scorer/strategy."""
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
        )
        assert store._importance_scorer is None
        assert store._recall_strategy is None

    async def test_recall_similar_uses_backend_directly_without_strategy(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """Without recall_strategy, recall_similar() calls backend.search_similar."""
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
        )
        await store.recall_similar("test query", namespace=namespace)
        mock_backend.search_similar.assert_called_once()

    async def test_record_episode_uses_inline_logic_without_scorer(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """Without importance_scorer, record_episode uses inline heuristic."""
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
        )
        episode = await store.record_episode(
            namespace=namespace,
            situation="Test situation",
            action_taken="Test action",
            outcome=EpisodeOutcome.SUCCESS,
        )
        # Default inline logic: SUCCESS → importance 3
        assert episode.importance == 3
        mock_backend.store.assert_called_once()


class TestScorerInjection:
    """Tests for importance_scorer injection."""

    async def test_custom_scorer_overrides_importance(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """Custom importance_scorer should override the inline heuristic."""
        mock_scorer = MagicMock()
        mock_scorer.score = MagicMock(return_value=0.9)  # Will map to importance 9

        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
            importance_scorer=mock_scorer,
        )
        episode = await store.record_episode(
            namespace=namespace,
            situation="Test situation",
            action_taken="Test action",
            outcome=EpisodeOutcome.SUCCESS,
        )

        mock_scorer.score.assert_called_once()
        assert episode.importance == 9  # 0.9 * 10 = 9

    async def test_heuristic_scorer_injected(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """HeuristicScorer can be injected and should produce valid importance."""
        scorer = HeuristicScorer()
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
            importance_scorer=scorer,
        )
        episode = await store.record_episode(
            namespace=namespace,
            situation="Test situation",
            action_taken="Test action",
            outcome=EpisodeOutcome.FAILURE,
        )
        assert 1 <= episode.importance <= 10

    async def test_value_scorer_injected(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """ValueScorer can be injected and should produce valid importance."""
        scorer = ValueScorer()
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
            importance_scorer=scorer,
        )
        episode = await store.record_episode(
            namespace=namespace,
            situation="Long enough situation to pass the word count threshold",
            action_taken="Called important API with parameters",
            outcome=EpisodeOutcome.SUCCESS,
            related_tools=["api_tool"],
        )
        assert 1 <= episode.importance <= 10

    async def test_scorer_failure_falls_back_gracefully(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """If scorer raises, episode is still stored (with inline importance)."""
        failing_scorer = MagicMock()
        failing_scorer.score = MagicMock(side_effect=RuntimeError("scorer broke"))

        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
            importance_scorer=failing_scorer,
        )
        # Should not raise
        episode = await store.record_episode(
            namespace=namespace,
            situation="Test situation",
            action_taken="Test action",
            outcome=EpisodeOutcome.SUCCESS,
        )
        assert episode is not None
        mock_backend.store.assert_called_once()


class TestStrategyInjection:
    """Tests for recall_strategy injection."""

    async def test_custom_strategy_called_in_recall(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """Custom recall_strategy should be called instead of backend directly."""
        mock_strategy = AsyncMock()
        mock_strategy.search = AsyncMock(return_value=[])

        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
            recall_strategy=mock_strategy,
        )

        await store.recall_similar("test query", namespace=namespace)

        mock_strategy.search.assert_called_once()
        mock_backend.search_similar.assert_not_called()

    async def test_strategy_receives_correct_params(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """recall_strategy.search() should receive query, embedding, backend, ns_filter."""
        mock_strategy = AsyncMock()
        mock_strategy.search = AsyncMock(return_value=[])

        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
            recall_strategy=mock_strategy,
        )

        await store.recall_similar("my query", namespace=namespace, top_k=3)

        call_kwargs = mock_strategy.search.call_args[1]
        assert call_kwargs["query"] == "my query"
        assert "query_embedding" in call_kwargs
        assert call_kwargs["backend"] is mock_backend
        assert "namespace_filter" in call_kwargs

    async def test_semantic_only_strategy_injected(
        self,
        mock_backend: AsyncMock,
        mock_embedding_provider: AsyncMock,
        namespace: MemoryNamespace,
    ) -> None:
        """SemanticOnlyStrategy can be injected and should delegate to backend."""
        strategy = SemanticOnlyStrategy()
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding_provider,
            recall_strategy=strategy,
        )
        await store.recall_similar("test query", namespace=namespace)
        # SemanticOnlyStrategy delegates to backend.search_similar
        mock_backend.search_similar.assert_called_once()


class TestFactoryMethods:
    """Tests for EpisodicMemoryStore factory method updates."""

    def test_create_pgvector_accepts_scorer_strategy_params(self) -> None:
        """create_pgvector() factory should accept scorer/strategy params."""
        import inspect
        sig = inspect.signature(EpisodicMemoryStore.create_pgvector)
        params = sig.parameters
        assert "recall_strategy" in params
        assert "importance_scorer" in params

    def test_create_redis_vector_exists(self) -> None:
        """create_redis_vector() factory method should exist."""
        assert hasattr(EpisodicMemoryStore, "create_redis_vector")
        assert callable(EpisodicMemoryStore.create_redis_vector)

    def test_create_redis_vector_accepts_correct_params(self) -> None:
        """create_redis_vector() should accept redis_url, index_name, etc."""
        import inspect
        sig = inspect.signature(EpisodicMemoryStore.create_redis_vector)
        params = sig.parameters
        assert "redis_url" in params
        assert "index_name" in params
        assert "embedding_dim" in params
        assert "recall_strategy" in params
        assert "importance_scorer" in params
