"""Unit tests for LongTermMemoryMixin."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.memory.unified.mixin import LongTermMemoryMixin


class MockAgent(LongTermMemoryMixin):
    """Minimal test agent using the mixin."""

    name = "test-agent"
    enable_long_term_memory = True

    def __init__(self):
        self._llm = MagicMock()
        self.conversation_memory = None
        self.logger = MagicMock()


class TestLongTermMemoryMixin:
    @pytest.mark.asyncio
    async def test_disabled_is_noop(self):
        """When disabled, configure is a no-op and manager stays None."""
        agent = MockAgent()
        agent.enable_long_term_memory = False
        await agent._configure_long_term_memory()
        assert agent._memory_manager is None

    @pytest.mark.asyncio
    async def test_configure_creates_manager(self):
        """configure() creates a UnifiedMemoryManager when enabled."""
        agent = MockAgent()
        with patch("parrot.memory.unified.mixin.UnifiedMemoryManager") as MockManager:
            instance = MagicMock()
            instance.configure = AsyncMock()
            MockManager.return_value = instance
            # Also patch subsystem factories so they return None quickly
            with (
                patch.object(agent, "_create_episodic_store", AsyncMock(return_value=None)),
                patch.object(agent, "_create_skill_registry", AsyncMock(return_value=None)),
            ):
                await agent._configure_long_term_memory()
        assert agent._memory_manager is not None

    @pytest.mark.asyncio
    async def test_get_memory_context_no_manager(self):
        """Returns empty string when manager is not configured."""
        agent = MockAgent()
        agent._memory_manager = None
        result = await agent.get_memory_context("query", "user1", "s1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_memory_context_disabled(self):
        """Returns empty string when enable_long_term_memory is False."""
        agent = MockAgent()
        agent.enable_long_term_memory = False
        agent._memory_manager = AsyncMock()
        result = await agent.get_memory_context("query", "user1", "s1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_post_response_hook_exception_safe(self):
        """_post_response_memory_hook never raises."""
        agent = MockAgent()
        agent._memory_manager = AsyncMock()
        agent._memory_manager.record_interaction = AsyncMock(
            side_effect=Exception("fail")
        )
        # Should not raise
        await agent._post_response_memory_hook("query", MagicMock(), "user1", "s1")

    @pytest.mark.asyncio
    async def test_post_response_hook_noop_when_disabled(self):
        """Hook is a no-op when enable_long_term_memory is False."""
        agent = MockAgent()
        agent.enable_long_term_memory = False
        mock_manager = AsyncMock()
        agent._memory_manager = mock_manager
        await agent._post_response_memory_hook("query", "response", "u1", "s1")
        mock_manager.record_interaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_memory_context_returns_prompt_string(self):
        """get_memory_context delegates to manager and calls to_prompt_string."""
        agent = MockAgent()
        mock_ctx = MagicMock()
        mock_ctx.to_prompt_string.return_value = "MEMORY CONTENT"
        mock_manager = AsyncMock()
        mock_manager.get_context_for_query = AsyncMock(return_value=mock_ctx)
        agent._memory_manager = mock_manager
        result = await agent.get_memory_context("my query", "user1", "sess1")
        assert result == "MEMORY CONTENT"
        mock_manager.get_context_for_query.assert_called_once_with(
            query="my query", user_id="user1", session_id="sess1"
        )

    def test_create_namespace_uses_agent_name(self):
        """_create_namespace uses self.name as agent_id."""
        agent = MockAgent()
        ns = agent._create_namespace()
        assert ns.agent_id == "test-agent"
        assert ns.tenant_id == "default"

    def test_create_namespace_fallback(self):
        """_create_namespace falls back to 'unknown_agent' when name is empty/None."""
        agent = MockAgent()
        agent.name = ""  # empty string — should fall back to default
        ns = agent._create_namespace()
        assert ns.agent_id == "unknown_agent"

    @pytest.mark.asyncio
    async def test_configure_exception_leaves_manager_none(self):
        """If configure() raises, manager stays None (no crash)."""
        agent = MockAgent()
        with patch("parrot.memory.unified.mixin.UnifiedMemoryManager") as MockManager:
            MockManager.side_effect = RuntimeError("boom")
            with (
                patch.object(agent, "_create_episodic_store", AsyncMock(return_value=None)),
                patch.object(agent, "_create_skill_registry", AsyncMock(return_value=None)),
            ):
                await agent._configure_long_term_memory()
        assert agent._memory_manager is None

    def test_import(self):
        """Import path works as specified."""
        from parrot.memory.unified.mixin import LongTermMemoryMixin as LTM  # noqa: F401
        assert LTM is LongTermMemoryMixin
