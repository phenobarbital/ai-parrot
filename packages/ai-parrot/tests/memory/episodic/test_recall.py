"""Unit tests for episodic memory recall strategies."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.memory.episodic.models import (
    EpisodeCategory,
    EpisodeOutcome,
    EpisodeSearchResult,
    EpisodicMemory,
    MemoryNamespace,
)
from parrot.memory.episodic.recall import (
    HybridBM25Strategy,
    RecallStrategy,
    SemanticOnlyStrategy,
)


@pytest.fixture
def sample_episode() -> EpisodicMemory:
    """A sample episode with embedding."""
    return EpisodicMemory(
        agent_id="test-agent",
        situation="User asked about weather forecast",
        action_taken="Called weather API",
        outcome=EpisodeOutcome.SUCCESS,
        category=EpisodeCategory.TOOL_EXECUTION,
        embedding=[0.1] * 384,
    )


@pytest.fixture
def sample_episodes() -> list[EpisodicMemory]:
    """Multiple sample episodes for BM25 index building."""
    return [
        EpisodicMemory(
            agent_id="test-agent",
            situation="User asked about weather forecast for tomorrow",
            action_taken="Called weather API with location parameter",
            outcome=EpisodeOutcome.SUCCESS,
            category=EpisodeCategory.TOOL_EXECUTION,
            embedding=[0.9, 0.1] + [0.0] * 382,
        ),
        EpisodicMemory(
            agent_id="test-agent",
            situation="Database connection failed during query execution",
            action_taken="Retried with exponential backoff",
            outcome=EpisodeOutcome.FAILURE,
            category=EpisodeCategory.ERROR_RECOVERY,
            is_failure=True,
            embedding=[0.1, 0.9] + [0.0] * 382,
        ),
        EpisodicMemory(
            agent_id="test-agent",
            situation="User requested financial report generation",
            action_taken="Generated PDF report using template engine",
            outcome=EpisodeOutcome.SUCCESS,
            category=EpisodeCategory.TOOL_EXECUTION,
            embedding=[0.5, 0.5] + [0.0] * 382,
        ),
    ]


@pytest.fixture
def mock_backend(sample_episodes: list[EpisodicMemory]) -> AsyncMock:
    """A mock backend that returns sample episodes."""
    backend = AsyncMock()
    search_results = [
        EpisodeSearchResult(**ep.model_dump(), embedding=ep.embedding, score=0.8)
        for ep in sample_episodes[:2]
    ]
    backend.search_similar = AsyncMock(return_value=search_results)
    backend.get_recent = AsyncMock(return_value=sample_episodes)
    return backend


class TestSemanticOnlyStrategy:
    """Tests for SemanticOnlyStrategy."""

    async def test_delegates_to_backend_search_similar(
        self, mock_backend: AsyncMock
    ) -> None:
        """Should call backend.search_similar with correct parameters."""
        strategy = SemanticOnlyStrategy()
        embedding = [0.1] * 384
        namespace_filter = {"agent_id": "test-agent", "tenant_id": "default"}

        await strategy.search(
            query="weather",
            query_embedding=embedding,
            backend=mock_backend,
            namespace_filter=namespace_filter,
            top_k=5,
            score_threshold=0.3,
        )

        mock_backend.search_similar.assert_called_once_with(
            embedding=embedding,
            namespace_filter=namespace_filter,
            top_k=5,
            score_threshold=0.3,
            include_failures_only=False,
        )

    async def test_returns_backend_results(
        self, mock_backend: AsyncMock
    ) -> None:
        """Should return exactly what backend returns."""
        strategy = SemanticOnlyStrategy()
        results = await strategy.search(
            query="test",
            query_embedding=[0.1] * 384,
            backend=mock_backend,
            namespace_filter={"agent_id": "test-agent"},
            top_k=5,
        )
        assert isinstance(results, list)

    async def test_passes_include_failures_only(
        self, mock_backend: AsyncMock
    ) -> None:
        """Should forward include_failures_only flag to backend."""
        strategy = SemanticOnlyStrategy()
        await strategy.search(
            query="test",
            query_embedding=[0.1] * 384,
            backend=mock_backend,
            namespace_filter={},
            top_k=5,
            include_failures_only=True,
        )
        call_kwargs = mock_backend.search_similar.call_args[1]
        assert call_kwargs["include_failures_only"] is True

    def test_protocol_compliance(self) -> None:
        """SemanticOnlyStrategy must satisfy RecallStrategy protocol."""
        assert isinstance(SemanticOnlyStrategy(), RecallStrategy)


class TestHybridBM25Strategy:
    """Tests for HybridBM25Strategy."""

    def test_default_weights(self) -> None:
        """Default weights should be 0.4 BM25 / 0.6 semantic."""
        strategy = HybridBM25Strategy()
        assert strategy.bm25_weight == 0.4
        assert strategy.semantic_weight == 0.6

    def test_configurable_weights(self) -> None:
        """Weights should be configurable."""
        strategy = HybridBM25Strategy(bm25_weight=0.3, semantic_weight=0.7)
        assert strategy.bm25_weight == 0.3
        assert strategy.semantic_weight == 0.7

    def test_protocol_compliance(self) -> None:
        """HybridBM25Strategy must satisfy RecallStrategy protocol."""
        assert isinstance(HybridBM25Strategy(), RecallStrategy)

    async def test_builds_index_on_first_search(
        self, mock_backend: AsyncMock
    ) -> None:
        """Should call backend.get_recent on first search to build index."""
        strategy = HybridBM25Strategy()

        with patch.object(strategy, "_build_index", wraps=strategy._build_index) as mock_build:
            # Mock bm25s lazy import to avoid dependency requirement
            with patch("parrot.memory.episodic.recall.lazy_import") as mock_lazy:
                bm25s_mock = MagicMock()
                tokenized_mock = MagicMock()
                retriever_mock = MagicMock()
                retriever_mock.retrieve.return_value = ([[0.5, 0.3, 0.1]], MagicMock())
                bm25s_mock.BM25.return_value = retriever_mock
                bm25s_mock.tokenize.return_value = tokenized_mock
                mock_lazy.return_value = bm25s_mock

                await strategy.search(
                    query="weather forecast",
                    query_embedding=[0.9, 0.1] + [0.0] * 382,
                    backend=mock_backend,
                    namespace_filter={"agent_id": "test-agent", "tenant_id": "default"},
                    top_k=5,
                )

            # get_recent should have been called to build the index
            mock_backend.get_recent.assert_called()

    async def test_falls_back_when_bm25s_missing(
        self, mock_backend: AsyncMock
    ) -> None:
        """Should fall back to semantic search when bm25s is not installed."""
        strategy = HybridBM25Strategy()

        with patch("parrot.memory.episodic.recall.lazy_import", side_effect=ImportError("bm25s not found")):
            results = await strategy.search(
                query="weather",
                query_embedding=[0.1] * 384,
                backend=mock_backend,
                namespace_filter={"agent_id": "test-agent"},
                top_k=5,
            )

        # Should have fallen back to backend.search_similar
        mock_backend.search_similar.assert_called_once()
        assert isinstance(results, list)

    async def test_caches_index_on_second_search(
        self, mock_backend: AsyncMock
    ) -> None:
        """Second search for same namespace should reuse cached index."""
        strategy = HybridBM25Strategy()

        with patch("parrot.memory.episodic.recall.lazy_import") as mock_lazy:
            bm25s_mock = MagicMock()
            tokenized_mock = MagicMock()
            retriever_mock = MagicMock()
            retriever_mock.retrieve.return_value = ([[0.5, 0.3, 0.1]], MagicMock())
            bm25s_mock.BM25.return_value = retriever_mock
            bm25s_mock.tokenize.return_value = tokenized_mock
            mock_lazy.return_value = bm25s_mock

            ns_filter = {"agent_id": "test-agent", "tenant_id": "default"}

            await strategy.search(
                query="first query",
                query_embedding=[0.9, 0.1] + [0.0] * 382,
                backend=mock_backend,
                namespace_filter=ns_filter,
                top_k=3,
            )
            first_call_count = mock_backend.get_recent.call_count

            await strategy.search(
                query="second query",
                query_embedding=[0.5, 0.5] + [0.0] * 382,
                backend=mock_backend,
                namespace_filter=ns_filter,
                top_k=3,
            )
            second_call_count = mock_backend.get_recent.call_count

        # get_recent should NOT have been called again (index cached)
        assert second_call_count == first_call_count

    def test_invalidate_removes_cache_entry(self) -> None:
        """invalidate() should remove the namespace from the cache."""
        strategy = HybridBM25Strategy()
        ns_filter = {"agent_id": "test-agent"}
        key = strategy._namespace_key(ns_filter)

        # Manually insert a dummy entry
        strategy._cache[key] = MagicMock()
        assert key in strategy._cache

        strategy.invalidate(ns_filter)
        assert key not in strategy._cache

    async def test_empty_namespace_falls_back(
        self, mock_backend: AsyncMock
    ) -> None:
        """When namespace has no episodes, should fall back to backend.search_similar."""
        strategy = HybridBM25Strategy()
        mock_backend.get_recent = AsyncMock(return_value=[])

        with patch("parrot.memory.episodic.recall.lazy_import") as mock_lazy:
            bm25s_mock = MagicMock()
            bm25s_mock.tokenize.return_value = MagicMock()
            mock_lazy.return_value = bm25s_mock

            await strategy.search(
                query="test",
                query_embedding=[0.1] * 384,
                backend=mock_backend,
                namespace_filter={"agent_id": "empty-agent"},
                top_k=5,
            )

        mock_backend.search_similar.assert_called_once()
