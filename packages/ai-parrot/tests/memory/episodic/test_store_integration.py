"""Tests for EpisodicMemoryStore scorer/strategy injection points."""
import asyncio
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
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


class _NonPagingBackend:
    """Expose the baseline backend protocol without SQLite's optional paging capability."""

    def __init__(self, backend: SQLiteEpisodeBackend) -> None:
        """Delegate baseline operations to a configured SQLite backend."""
        self.store = backend.store
        self.search_similar = backend.search_similar
        self.get_recent = backend.get_recent
        self.get_failures = backend.get_failures
        self.count = backend.count
        self.delete_expired = backend.delete_expired
        self.update_metadata = backend.update_metadata


@pytest.mark.asyncio
async def test_recall_lane_survives_excluded_matches_across_pages(tmp_path: Path) -> None:
    """More than two excluded pages cannot hide an older eligible interaction."""
    backend = SQLiteEpisodeBackend(tmp_path / "paged-recall.sqlite")
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend, default_ttl_days=0)
        scope = MemoryNamespace(agent_id="memory-agent", user_id="user-a")
        eligible = await store.record_episode(
            namespace=MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="older-session"),
            situation="Migration planning succeeded",
            action_taken="Recorded the reusable migration approach",
            outcome=EpisodeOutcome.SUCCESS,
            episode_id="eligible-older",
        )
        await store.record_episode(
            namespace=MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="other-session"),
            situation="Migration planning was superseded",
            action_taken="Recorded a retracted migration approach",
            outcome=EpisodeOutcome.SUCCESS,
            metadata={"coder_feedback_retracted": True},
            episode_id="excluded-retracted",
        )
        await store.record_episode(
            namespace=MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="other-session"),
            situation="Migration planning failed",
            action_taken="Recorded the failed migration attempt",
            outcome=EpisodeOutcome.FAILURE,
            episode_id="excluded-failure",
        )
        current_scope = MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="current-session")
        for index in range(511):
            await store.record_episode(
                namespace=current_scope,
                situation=f"Migration planning in the current session {index}",
                action_taken="Recorded a current-session migration interaction",
                outcome=EpisodeOutcome.SUCCESS,
                episode_id=f"excluded-current-{index:03d}",
            )

        results = await store.recall_interactions(
            "migration planning",
            scope,
            top_k=1,
            exclude_session_id="current-session",
        )

        assert [result.episode_id for result in results] == [eligible.episode_id]
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_interaction_recall_bypasses_vector_and_strategy_caps(tmp_path: Path) -> None:
    """Injected embeddings and strategies are never called by interaction recall."""
    backend = SQLiteEpisodeBackend(tmp_path / "lexical-only.sqlite", vector_ceiling=1)
    await backend.configure()
    try:
        writer = EpisodicMemoryStore(backend, default_ttl_days=0)
        scope = MemoryNamespace(agent_id="memory-agent", user_id="user-a")
        eligible = await writer.record_episode(
            namespace=MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="older-session"),
            situation="Recovered the billing migration",
            action_taken="Applied the known migration sequence",
            outcome=EpisodeOutcome.SUCCESS,
            episode_id="eligible-vector-bypass",
        )
        await writer.record_episode(
            namespace=MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="current-session"),
            situation="Retried the billing migration",
            action_taken="Created a newer vector candidate",
            outcome=EpisodeOutcome.SUCCESS,
            episode_id="excluded-vector-candidate",
        )

        embedding = AsyncMock()
        embedding.embed = AsyncMock(side_effect=AssertionError("embedding recall must not run"))
        strategy = AsyncMock()
        strategy.search = AsyncMock(side_effect=AssertionError("strategy recall must not run"))
        vector_search = AsyncMock(side_effect=AssertionError("vector search must not run"))
        backend.search_similar = vector_search
        store = EpisodicMemoryStore(
            backend,
            embedding_provider=embedding,
            recall_strategy=strategy,
            default_ttl_days=0,
        )

        results = await store.recall_interactions(
            "billing migration",
            scope,
            top_k=1,
            exclude_session_id="current-session",
        )

        assert [result.episode_id for result in results] == [eligible.episode_id]
        embedding.embed.assert_not_awaited()
        strategy.search.assert_not_awaited()
        vector_search.assert_not_awaited()
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_recall_exclusions_exhaust_without_widening_scope(tmp_path: Path) -> None:
    """All-excluded populations terminate; inputs validate; scope stays narrow."""
    backend = SQLiteEpisodeBackend(tmp_path / "nonpaged-recall.sqlite")
    await backend.configure()
    try:
        writer = EpisodicMemoryStore(backend, default_ttl_days=0)
        scope = MemoryNamespace(agent_id="memory-agent", user_id="user-a")
        for episode_scope, outcome, metadata, episode_id in (
            (
                MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="current-session"),
                EpisodeOutcome.SUCCESS,
                {},
                "excluded-current",
            ),
            (
                MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="older-session"),
                EpisodeOutcome.FAILURE,
                {},
                "excluded-failure",
            ),
            (
                MemoryNamespace(agent_id="memory-agent", user_id="user-a", session_id="older-session"),
                EpisodeOutcome.SUCCESS,
                {"coder_feedback_retracted": True},
                "excluded-retracted",
            ),
            (
                MemoryNamespace(
                    agent_id="memory-agent",
                    user_id="user-a",
                    session_id="older-session",
                    room_id="other-room",
                ),
                EpisodeOutcome.SUCCESS,
                {},
                "excluded-null-dimension",
            ),
            (
                MemoryNamespace(agent_id="memory-agent", user_id="user-b", session_id="older-session"),
                EpisodeOutcome.SUCCESS,
                {},
                "excluded-other-user",
            ),
        ):
            await writer.record_episode(
                namespace=episode_scope,
                situation="Database migration review",
                action_taken="Recorded a migration interaction",
                outcome=outcome,
                metadata=metadata,
                episode_id=episode_id,
            )

        store = EpisodicMemoryStore(_NonPagingBackend(backend), default_ttl_days=0)
        assert (
            await store.recall_interactions(
                "database migration",
                scope,
                exclude_session_id="current-session",
                null_dimensions=("room_id",),
            )
            == []
        )
        with pytest.raises(ValueError, match="top_k"):
            await store.recall_interactions("database migration", scope, top_k=-1)
        for threshold in (-0.1, 1.1, float("nan")):
            with pytest.raises(ValueError, match="score_threshold"):
                await store.recall_interactions("database migration", scope, score_threshold=threshold)
        assert await store.recall_interactions("database migration", scope, top_k=0) == []
        assert await store.recall_interactions("a ?!", scope) == []

        cancelling_backend = _NonPagingBackend(backend)
        cancelling_backend.count = AsyncMock(side_effect=asyncio.CancelledError())
        cancelling_store = EpisodicMemoryStore(cancelling_backend, default_ttl_days=0)
        with pytest.raises(asyncio.CancelledError):
            await cancelling_store.recall_interactions("database migration", scope)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_warning_retraction_order_is_unchanged(tmp_path: Path) -> None:
    """Warning top-k retraction ordering remains unchanged."""
    backend = SQLiteEpisodeBackend(tmp_path / "retraction-order.sqlite")
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend, default_ttl_days=0)
        scope = MemoryNamespace(agent_id="memory-agent", user_id="user-a")
        older_warning = await store.record_episode(
            namespace=scope,
            situation="Warning outage occurred",
            action_taken="Recorded the older warning",
            outcome=EpisodeOutcome.FAILURE,
            episode_id="older-warning",
        )
        await store.record_episode(
            namespace=scope,
            situation="Warning outage recurred",
            action_taken="Recorded the retracted warning",
            outcome=EpisodeOutcome.FAILURE,
            metadata={"coder_feedback_retracted": True},
            episode_id="newer-retracted-warning",
        )
        older_interaction = await store.record_episode(
            namespace=scope,
            situation="Deployment interaction succeeded",
            action_taken="Recorded the reusable deployment sequence",
            outcome=EpisodeOutcome.SUCCESS,
            episode_id="older-interaction",
        )
        await store.record_episode(
            namespace=scope,
            situation="Deployment interaction was superseded",
            action_taken="Recorded the retracted deployment sequence",
            outcome=EpisodeOutcome.SUCCESS,
            metadata={"coder_feedback_retracted": True},
            episode_id="newer-retracted-interaction",
        )

        warning_results = await store.recall_similar(
            "warning outage",
            scope,
            top_k=1,
            include_failures_only=True,
        )
        interaction_results = await store.recall_interactions("deployment interaction", scope, top_k=1)

        assert warning_results == []
        assert older_warning.episode_id not in {result.episode_id for result in warning_results}
        assert [result.episode_id for result in interaction_results] == [older_interaction.episode_id]
    finally:
        await backend.close()


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
