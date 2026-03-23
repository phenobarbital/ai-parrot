"""Unit tests for UnifiedMemoryManager — mocked subsystems."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryConfig
from parrot.memory.episodic.models import MemoryNamespace


@pytest.fixture
def namespace() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="test", agent_id="test-agent", user_id="user1")


@pytest.fixture
def mock_episodic() -> AsyncMock:
    store = AsyncMock()
    store.get_failure_warnings = AsyncMock(return_value="Warning: API rate limit hit")
    store.record_tool_episode = AsyncMock()
    store.configure = AsyncMock()
    store.cleanup = AsyncMock()
    return store


@pytest.fixture
def mock_skills() -> AsyncMock:
    registry = AsyncMock()
    registry.get_relevant_skills = AsyncMock(
        return_value="Skill: use pagination for large queries"
    )
    registry.configure = AsyncMock()
    registry.cleanup = AsyncMock()
    return registry


@pytest.fixture
def mock_conversation() -> AsyncMock:
    memory = AsyncMock()
    history = MagicMock()
    history.turns = []
    memory.get_history = AsyncMock(return_value=history)
    memory.configure = AsyncMock()
    memory.cleanup = AsyncMock()
    return memory


class TestUnifiedMemoryManager:
    @pytest.mark.asyncio
    async def test_parallel_retrieval(self, namespace, mock_episodic, mock_skills):
        """get_context_for_query retrieves from all subsystems."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            skill_registry=mock_skills,
        )
        ctx = await manager.get_context_for_query("test query", "user1", "session1")
        assert "rate limit" in ctx.episodic_warnings
        assert "pagination" in ctx.relevant_skills

    @pytest.mark.asyncio
    async def test_partial_subsystems(self, namespace, mock_episodic):
        """Works with only episodic store; skills section is empty."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            skill_registry=None,
        )
        ctx = await manager.get_context_for_query("test query", "user1", "session1")
        assert ctx.episodic_warnings != ""
        assert ctx.relevant_skills == ""

    @pytest.mark.asyncio
    async def test_record_interaction_safe(self, namespace, mock_episodic):
        """record_interaction does not raise when episodic raises."""
        mock_episodic.record_tool_episode.side_effect = Exception("Redis down")
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
        )
        # Should not raise
        await manager.record_interaction("query", MagicMock(), [], "user1", "session1")

    @pytest.mark.asyncio
    async def test_all_none_subsystems(self, namespace):
        """All-None config returns empty MemoryContext."""
        manager = UnifiedMemoryManager(namespace=namespace)
        ctx = await manager.get_context_for_query("test", "user1", "s1")
        assert ctx.tokens_used == 0

    @pytest.mark.asyncio
    async def test_configure_calls_subsystems(
        self, namespace, mock_episodic, mock_skills
    ):
        """configure() calls configure on each subsystem that has it."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            skill_registry=mock_skills,
        )
        await manager.configure()
        mock_episodic.configure.assert_called_once()
        mock_skills.configure.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_calls_subsystems(
        self, namespace, mock_episodic, mock_skills
    ):
        """cleanup() calls cleanup on each subsystem that has it."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            skill_registry=mock_skills,
        )
        await manager.cleanup()
        mock_episodic.cleanup.assert_called_once()
        mock_skills.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_within_token_budget(self, namespace, mock_episodic):
        """Assembled context respects token budget."""
        config = MemoryConfig(max_context_tokens=500)
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            config=config,
        )
        ctx = await manager.get_context_for_query("query", "user1", "s1")
        assert ctx.tokens_used <= 500

    @pytest.mark.asyncio
    async def test_conversation_formatted_as_turns(
        self, namespace, mock_conversation
    ):
        """Conversation turns are formatted as User/Assistant lines."""
        turn = MagicMock()
        turn.user_message = "hello"
        turn.assistant_response = "hi there"
        mock_conversation.get_history.return_value = MagicMock(turns=[turn])

        manager = UnifiedMemoryManager(
            namespace=namespace,
            conversation_memory=mock_conversation,
        )
        ctx = await manager.get_context_for_query("q", "user1", "s1")
        assert "User: hello" in ctx.conversation_summary
        assert "Assistant: hi there" in ctx.conversation_summary

    @pytest.mark.asyncio
    async def test_episodic_retrieval_error_returns_empty(self, namespace, mock_episodic):
        """When episodic retrieval raises, section is empty (not an exception)."""
        mock_episodic.get_failure_warnings.side_effect = Exception("timeout")
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
        )
        ctx = await manager.get_context_for_query("q", "user1", "s1")
        assert ctx.episodic_warnings == ""

    def test_import(self):
        """Import path works as specified."""
        from parrot.memory.unified.manager import UnifiedMemoryManager as UMM  # noqa: F401
        assert UMM is UnifiedMemoryManager
