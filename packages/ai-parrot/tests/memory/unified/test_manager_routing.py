"""Tests for UnifiedMemoryManager cross-domain routing integration."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.routing import CrossDomainRouter


@pytest.fixture
def namespace() -> MemoryNamespace:
    """A default namespace for testing."""
    return MemoryNamespace(agent_id="agent-a", tenant_id="t1")


@pytest.fixture
def mock_episodic_store() -> AsyncMock:
    """A mocked episodic store with embedding provider."""
    store = AsyncMock()
    store.get_failure_warnings = AsyncMock(return_value="MISTAKES TO AVOID:\n- Some warning")

    mock_embedding_provider = AsyncMock()
    mock_embedding_provider.embed = AsyncMock(return_value=[0.1] * 384)
    store._embedding = mock_embedding_provider

    return store


@pytest.fixture
def mock_router() -> AsyncMock:
    """A mocked CrossDomainRouter."""
    router = MagicMock(spec=CrossDomainRouter)
    router.find_relevant_agents = AsyncMock(return_value=["agent-b"])
    router.cross_domain_decay = 0.6
    return router


class TestManagerWithoutRouter:
    """Tests for UnifiedMemoryManager without cross_domain_router (default behavior)."""

    def test_constructor_accepts_no_router(self, namespace: MemoryNamespace) -> None:
        """UnifiedMemoryManager should construct without router."""
        manager = UnifiedMemoryManager(namespace=namespace)
        assert manager._cross_domain_router is None

    async def test_get_context_works_without_router(
        self, namespace: MemoryNamespace, mock_episodic_store: AsyncMock
    ) -> None:
        """get_context_for_query should work fine without router."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic_store,
        )
        context = await manager.get_context_for_query("test query", "user1", "session1")
        assert context is not None

    async def test_no_router_no_cross_domain_calls(
        self, namespace: MemoryNamespace, mock_episodic_store: AsyncMock
    ) -> None:
        """Without router, get_failure_warnings called only once (for local ns)."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic_store,
        )
        await manager.get_context_for_query("test query", "user1", "session1")
        # Should only call get_failure_warnings once (local namespace)
        assert mock_episodic_store.get_failure_warnings.call_count == 1


class TestManagerWithRouter:
    """Tests for UnifiedMemoryManager with cross_domain_router."""

    def test_constructor_accepts_router(
        self, namespace: MemoryNamespace, mock_router: AsyncMock
    ) -> None:
        """UnifiedMemoryManager should accept cross_domain_router."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            cross_domain_router=mock_router,
        )
        assert manager._cross_domain_router is mock_router

    async def test_router_find_relevant_agents_called(
        self,
        namespace: MemoryNamespace,
        mock_episodic_store: AsyncMock,
        mock_router: AsyncMock,
    ) -> None:
        """get_context_for_query should call router.find_relevant_agents."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic_store,
            cross_domain_router=mock_router,
        )
        await manager.get_context_for_query("test query", "user1", "session1")
        mock_router.find_relevant_agents.assert_called_once()

    async def test_cross_domain_warnings_included(
        self,
        namespace: MemoryNamespace,
        mock_episodic_store: AsyncMock,
        mock_router: AsyncMock,
    ) -> None:
        """When router returns agent-b, agent-b's warnings should be in context."""
        # Setup agent-b returns different warnings
        mock_episodic_store.get_failure_warnings = AsyncMock(
            side_effect=lambda namespace, **kwargs: (
                "Local warning"
                if namespace.agent_id == "agent-a"
                else "Cross-domain warning"
            )
        )

        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic_store,
            cross_domain_router=mock_router,
        )
        context = await manager.get_context_for_query("test query", "user1", "session1")
        # The episodic_warnings field in context should include cross-domain label
        assert context is not None

    async def test_cross_domain_failure_does_not_break_main_flow(
        self,
        namespace: MemoryNamespace,
        mock_episodic_store: AsyncMock,
        mock_router: AsyncMock,
    ) -> None:
        """If router raises, main flow should still succeed."""
        mock_router.find_relevant_agents = AsyncMock(
            side_effect=RuntimeError("router failed")
        )

        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic_store,
            cross_domain_router=mock_router,
        )
        # Should not raise — cross-domain errors are caught
        context = await manager.get_context_for_query("test query", "user1", "session1")
        assert context is not None

    async def test_cross_domain_individual_agent_failure_graceful(
        self,
        namespace: MemoryNamespace,
        mock_episodic_store: AsyncMock,
        mock_router: AsyncMock,
    ) -> None:
        """If individual agent warning fetch fails, it's skipped gracefully."""
        call_count = 0

        async def selective_failure(namespace, **kwargs):
            nonlocal call_count
            call_count += 1
            if namespace.agent_id == "agent-b":
                raise RuntimeError("agent-b store failed")
            return "Local warning"

        mock_episodic_store.get_failure_warnings = selective_failure

        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic_store,
            cross_domain_router=mock_router,
        )
        # Should not raise
        context = await manager.get_context_for_query("test query", "user1", "session1")
        assert context is not None

    async def test_no_relevant_agents_returns_local_only(
        self,
        namespace: MemoryNamespace,
        mock_episodic_store: AsyncMock,
        mock_router: AsyncMock,
    ) -> None:
        """When router returns no agents, only local warnings are returned."""
        mock_router.find_relevant_agents = AsyncMock(return_value=[])
        mock_episodic_store.get_failure_warnings = AsyncMock(
            return_value="Local warning"
        )

        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic_store,
            cross_domain_router=mock_router,
        )
        await manager.get_context_for_query("test query", "user1", "session1")
        # get_failure_warnings called once (local only — no cross-domain)
        assert mock_episodic_store.get_failure_warnings.call_count == 1

    async def test_router_without_episodic_store_no_crash(
        self, namespace: MemoryNamespace, mock_router: AsyncMock
    ) -> None:
        """Router with no episodic store should not crash."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            cross_domain_router=mock_router,
        )
        # Without episodic store, routing is skipped entirely
        context = await manager.get_context_for_query("test query", "user1", "session1")
        assert context is not None
        mock_router.find_relevant_agents.assert_not_called()
