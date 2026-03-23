"""Integration tests for long-term memory hooks in bot base classes."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.memory.unified.mixin import LongTermMemoryMixin


# ---------------------------------------------------------------------------
# Minimal stubs to test create_system_prompt in isolation
# ---------------------------------------------------------------------------

class StubBot:
    """Minimal bot stub that exercises create_system_prompt without heavy deps."""

    system_prompt_template = "You are a helpful assistant. $context $chat_history $user_context"
    _prompt_builder = None

    def __init__(self):
        self.logger = MagicMock()
        self._dynamic_values = None

    async def create_system_prompt(
        self,
        user_context: str = "",
        vector_context: str = "",
        conversation_context: str = "",
        kb_context: str = "",
        pageindex_context: str = "",
        metadata=None,
        memory_context=None,
        **kwargs,
    ) -> str:
        """Simplified version mirroring the real implementation's contract."""
        result = self.system_prompt_template
        if memory_context:
            result += f"\n\n{memory_context}"
        return result


class MixinBot(LongTermMemoryMixin, StubBot):
    """Bot that uses the mixin."""

    name = "mixin-bot"
    enable_long_term_memory = True

    def __init__(self):
        super().__init__()
        self.conversation_memory = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBotIntegrationHooks:
    @pytest.mark.asyncio
    async def test_system_prompt_without_memory_context(self):
        """create_system_prompt works with memory_context=None (unchanged behaviour)."""
        bot = StubBot()
        prompt = await bot.create_system_prompt(memory_context=None)
        assert "helpful assistant" in prompt
        assert "\n\n" not in prompt  # no memory injected

    @pytest.mark.asyncio
    async def test_system_prompt_with_memory_context(self):
        """Memory context is appended to the system prompt when provided."""
        bot = StubBot()
        prompt = await bot.create_system_prompt(memory_context="MEMORY: avoid X")
        assert "MEMORY: avoid X" in prompt

    @pytest.mark.asyncio
    async def test_agent_without_mixin_unchanged(self):
        """Bot without LongTermMemoryMixin works as before (no _memory_manager attr)."""
        bot = StubBot()
        assert not hasattr(bot, '_memory_manager')
        # create_system_prompt with no memory_context is fine
        prompt = await bot.create_system_prompt()
        assert "helpful assistant" in prompt

    @pytest.mark.asyncio
    async def test_get_memory_context_called_when_manager_active(self):
        """get_memory_context is called when _memory_manager is set."""
        bot = MixinBot()
        bot._memory_manager = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.to_prompt_string.return_value = "MEMORY SECTION"
        bot._memory_manager.get_context_for_query = AsyncMock(return_value=mock_ctx)

        result = await bot.get_memory_context("query", "user1", "sess1")
        assert result == "MEMORY SECTION"
        bot._memory_manager.get_context_for_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_memory_context_no_manager(self):
        """get_memory_context returns empty string when manager is None."""
        bot = MixinBot()
        bot._memory_manager = None
        result = await bot.get_memory_context("query", "user1", "sess1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_post_response_hook_exception_safe(self):
        """_post_response_memory_hook never raises even when record_interaction fails."""
        bot = MixinBot()
        bot._memory_manager = AsyncMock()
        bot._memory_manager.record_interaction = AsyncMock(
            side_effect=Exception("storage unavailable")
        )
        # Must not raise
        await bot._post_response_memory_hook("query", MagicMock(), "user1", "sess1")

    @pytest.mark.asyncio
    async def test_post_response_hook_noop_without_manager(self):
        """_post_response_memory_hook is a no-op when manager is None."""
        bot = MixinBot()
        bot._memory_manager = None
        # Should return immediately without errors
        await bot._post_response_memory_hook("query", "response", "user1", "sess1")

    @pytest.mark.asyncio
    async def test_memory_context_injected_into_system_prompt(self):
        """When mixin provides memory context it appears in the assembled prompt."""
        bot = MixinBot()
        bot._memory_manager = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.to_prompt_string.return_value = "<past_failures>\nDon't call X\n</past_failures>"
        bot._memory_manager.get_context_for_query = AsyncMock(return_value=mock_ctx)

        mem_ctx = await bot.get_memory_context("test query", "user1", "s1")
        prompt = await bot.create_system_prompt(memory_context=mem_ctx)
        assert "Don't call X" in prompt
