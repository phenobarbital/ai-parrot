"""Unit tests for CrossDomainRouter."""
import pytest
from unittest.mock import AsyncMock

from parrot.memory.unified.routing import AgentExpertise, CrossDomainRouter


@pytest.fixture
def router() -> CrossDomainRouter:
    """A CrossDomainRouter with default settings."""
    return CrossDomainRouter(similarity_threshold=0.5, cross_domain_decay=0.6)


@pytest.fixture
def mock_embedding_provider() -> AsyncMock:
    """A mock embedding provider that returns embeddings based on content."""
    provider = AsyncMock()

    async def embed(text: str) -> list[float]:
        """Return different embeddings for different text topics."""
        if "weather" in text.lower():
            return [1.0, 0.0, 0.0] + [0.0] * 381
        elif "finance" in text.lower() or "financial" in text.lower():
            return [0.0, 1.0, 0.0] + [0.0] * 381
        elif "database" in text.lower() or "sql" in text.lower():
            return [0.0, 0.0, 1.0] + [0.0] * 381
        else:
            return [0.5, 0.5, 0.0] + [0.0] * 381

    provider.embed = embed
    return provider


class TestCrossDomainRouterRegistration:
    """Tests for agent expertise registration."""

    def test_register_agent_expertise(self, router: CrossDomainRouter) -> None:
        """Should register an agent in the registry."""
        router.register_agent_expertise("weather-agent", "t1", "Weather forecasting")
        agents = router.list_registered_agents()
        assert "weather-agent" in agents

    def test_register_multiple_agents(self, router: CrossDomainRouter) -> None:
        """Should register multiple agents."""
        router.register_agent_expertise("agent-a", "t1", "Finance")
        router.register_agent_expertise("agent-b", "t1", "Weather")
        agents = router.list_registered_agents()
        assert "agent-a" in agents
        assert "agent-b" in agents

    def test_register_invalidates_cached_embedding(
        self, router: CrossDomainRouter
    ) -> None:
        """Re-registering with different description should invalidate embedding."""
        router.register_agent_expertise("agent-a", "t1", "Finance")
        # Manually set a fake cached embedding
        registry = object.__getattribute__(router, "_registry")
        registry["agent-a"].embedding = [0.1, 0.2, 0.3] + [0.0] * 381

        # Re-register with different description
        router.register_agent_expertise("agent-a", "t1", "Weather forecasting")
        assert registry["agent-a"].embedding is None

    def test_register_preserves_embedding_if_same_description(
        self, router: CrossDomainRouter
    ) -> None:
        """Re-registering with same description should preserve cached embedding."""
        router.register_agent_expertise("agent-a", "t1", "Finance")
        registry = object.__getattribute__(router, "_registry")
        fake_embedding = [0.1, 0.2, 0.3] + [0.0] * 381
        registry["agent-a"] = AgentExpertise(
            agent_id="agent-a",
            tenant_id="t1",
            domain_description="Finance",
            embedding=fake_embedding,
        )

        # Re-register with same description
        router.register_agent_expertise("agent-a", "t1", "Finance")
        assert registry["agent-a"].embedding == fake_embedding


class TestCrossDomainRouterConfiguration:
    """Tests for CrossDomainRouter configuration."""

    def test_default_similarity_threshold(self) -> None:
        """Default similarity threshold should be 0.5."""
        router = CrossDomainRouter()
        assert router.similarity_threshold == 0.5

    def test_default_cross_domain_decay(self) -> None:
        """Default decay factor should be 0.6."""
        router = CrossDomainRouter()
        assert router.cross_domain_decay == 0.6

    def test_configurable_threshold(self) -> None:
        """Should accept custom threshold."""
        router = CrossDomainRouter(similarity_threshold=0.7)
        assert router.similarity_threshold == 0.7

    def test_configurable_decay(self) -> None:
        """Should accept custom decay."""
        router = CrossDomainRouter(cross_domain_decay=0.8)
        assert router.cross_domain_decay == 0.8


class TestCrossDomainRouterFindRelevantAgents:
    """Tests for find_relevant_agents()."""

    async def test_find_relevant_weather_agent(
        self,
        router: CrossDomainRouter,
        mock_embedding_provider: AsyncMock,
    ) -> None:
        """Should find weather agent when query is weather-related."""
        router.register_agent_expertise(
            "weather-agent", "t1", "Weather forecasting and climate data analysis"
        )
        router.register_agent_expertise(
            "finance-agent", "t1", "Financial analysis and stock trading"
        )

        # Weather query embedding
        query_embedding = [1.0, 0.0, 0.0] + [0.0] * 381

        agents = await router.find_relevant_agents(
            query_embedding=query_embedding,
            current_agent_id="other-agent",
            embedding_provider=mock_embedding_provider,
            tenant_id="t1",
        )

        assert "weather-agent" in agents
        assert "finance-agent" not in agents

    async def test_excludes_current_agent(
        self,
        router: CrossDomainRouter,
        mock_embedding_provider: AsyncMock,
    ) -> None:
        """Should exclude the current agent from results."""
        router.register_agent_expertise(
            "weather-agent", "t1", "Weather forecasting"
        )

        # Query embedding close to weather
        query_embedding = [0.95, 0.05, 0.0] + [0.0] * 381

        agents = await router.find_relevant_agents(
            query_embedding=query_embedding,
            current_agent_id="weather-agent",  # This is the current agent
            embedding_provider=mock_embedding_provider,
            tenant_id="t1",
        )

        assert "weather-agent" not in agents

    async def test_tenant_isolation(
        self,
        router: CrossDomainRouter,
        mock_embedding_provider: AsyncMock,
    ) -> None:
        """Should never return agents from different tenants."""
        router.register_agent_expertise("agent-t1", "tenant1", "Weather forecasting")
        router.register_agent_expertise("agent-t2", "tenant2", "Weather forecasting")

        query_embedding = [1.0, 0.0, 0.0] + [0.0] * 381

        agents = await router.find_relevant_agents(
            query_embedding=query_embedding,
            current_agent_id="other-agent",
            embedding_provider=mock_embedding_provider,
            tenant_id="tenant1",
        )

        assert "agent-t1" in agents  # Same tenant
        assert "agent-t2" not in agents  # Different tenant — excluded

    async def test_returns_empty_when_no_agents_registered(
        self,
        mock_embedding_provider: AsyncMock,
    ) -> None:
        """Should return empty list when no agents are registered."""
        router = CrossDomainRouter()
        agents = await router.find_relevant_agents(
            query_embedding=[0.5] * 384,
            current_agent_id="agent-a",
            embedding_provider=mock_embedding_provider,
            tenant_id="t1",
        )
        assert agents == []

    async def test_returns_empty_below_threshold(
        self,
        router: CrossDomainRouter,
        mock_embedding_provider: AsyncMock,
    ) -> None:
        """Should return empty list when similarity is below threshold."""
        router.register_agent_expertise(
            "finance-agent", "t1", "Financial analysis and stock trading"
        )

        # Database query embedding — very different from finance
        query_embedding = [0.0, 0.0, 1.0] + [0.0] * 381

        agents = await router.find_relevant_agents(
            query_embedding=query_embedding,
            current_agent_id="other-agent",
            embedding_provider=mock_embedding_provider,
            tenant_id="t1",
        )

        # Finance agent's embedding is [0, 1, 0] → low similarity with [0, 0, 1]
        assert "finance-agent" not in agents

    async def test_respects_max_relevant_agents(
        self,
        mock_embedding_provider: AsyncMock,
    ) -> None:
        """Should return at most max_relevant_agents agents."""
        router = CrossDomainRouter(
            similarity_threshold=0.0,  # Accept all
            max_relevant_agents=1,
        )
        router.register_agent_expertise("agent-a", "t1", "Weather forecasting")
        router.register_agent_expertise("agent-b", "t1", "Weather forecast too")
        router.register_agent_expertise("agent-c", "t1", "Weather conditions")

        query_embedding = [1.0, 0.0, 0.0] + [0.0] * 381
        agents = await router.find_relevant_agents(
            query_embedding=query_embedding,
            current_agent_id="other",
            embedding_provider=mock_embedding_provider,
            tenant_id="t1",
        )

        assert len(agents) <= 1

    async def test_caches_embeddings(self) -> None:
        """Should compute embeddings only once per agent."""
        router = CrossDomainRouter(similarity_threshold=0.0)
        router.register_agent_expertise("agent-a", "t1", "Weather forecasting")

        call_count = 0

        async def counting_embed(text: str) -> list[float]:
            nonlocal call_count
            call_count += 1
            return [1.0, 0.0, 0.0] + [0.0] * 381

        counting_provider = AsyncMock()
        counting_provider.embed = counting_embed

        query = [1.0, 0.0, 0.0] + [0.0] * 381

        # First call — should compute embedding
        await router.find_relevant_agents(
            query_embedding=query,
            current_agent_id="other",
            embedding_provider=counting_provider,
            tenant_id="t1",
        )

        # Second call — should NOT call embed again (cached)
        await router.find_relevant_agents(
            query_embedding=query,
            current_agent_id="other",
            embedding_provider=counting_provider,
            tenant_id="t1",
        )

        # embed should only have been called once
        assert call_count == 1


class TestCossineSimilarity:
    """Tests for the _cosine_similarity helper."""

    def test_identical_vectors(self) -> None:
        """Identical vectors should have similarity 1.0."""
        v = [0.5, 0.5, 0.5]
        assert abs(CrossDomainRouter._cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        """Orthogonal vectors should have similarity 0.0."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(CrossDomainRouter._cosine_similarity(a, b)) < 1e-6

    def test_zero_vector(self) -> None:
        """Zero vector should return 0.0."""
        assert CrossDomainRouter._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_different_length_vectors(self) -> None:
        """Different length vectors should return 0.0."""
        assert CrossDomainRouter._cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0
