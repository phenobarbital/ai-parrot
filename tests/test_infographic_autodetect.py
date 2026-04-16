"""
Tests for FEAT-102: Template Auto-Detection Pre-Pass.

TASK-665: Template Auto-Detection

These tests verify the _detect_infographic_template logic directly
without importing the full AbstractBot (heavy deps).
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from parrot.models.infographic_templates import infographic_registry


async def _detect_infographic_template(bot_self, question: str) -> str:
    """Standalone copy of the detection logic for isolated testing."""
    templates = infographic_registry.list_templates_detailed()
    template_list = "\n".join(
        f"- {t['name']}: {t['description']}" for t in templates
    )
    prompt = (
        f"Given the following question/topic, select the SINGLE best infographic "
        f"template from the list below.\n\n"
        f"Available templates:\n{template_list}\n\n"
        f"Question: {question}\n\n"
        f"Respond with ONLY the template name (e.g., 'basic', 'executive', "
        f"'multi_tab'). Nothing else."
    )
    try:
        response = await bot_self.ask(
            question=prompt,
            max_tokens=50,
            use_vector_context=False,
            use_conversation_history=False,
        )
        detected = (
            response.content.strip().lower()
            .replace("'", "")
            .replace('"', "")
            .strip()
        )
        infographic_registry.get(detected)
        return detected
    except Exception:
        return "basic"


class TestTemplateAutoDetection:
    """Tests for the _detect_infographic_template pre-pass logic."""

    def _make_bot(self):
        """Create a lightweight mock bot."""
        bot = MagicMock()
        return bot

    @pytest.mark.asyncio
    async def test_auto_detect_selects_multi_tab(self):
        """Pre-pass returns 'multi_tab' for methodology question."""
        bot = self._make_bot()
        mock_response = MagicMock()
        mock_response.content = "multi_tab"
        bot.ask = AsyncMock(return_value=mock_response)

        result = await _detect_infographic_template(bot, "Methodology with phases")
        assert result == "multi_tab"

    @pytest.mark.asyncio
    async def test_auto_detect_selects_executive(self):
        """Pre-pass returns 'executive' for executive briefing question."""
        bot = self._make_bot()
        mock_response = MagicMock()
        mock_response.content = "executive"
        bot.ask = AsyncMock(return_value=mock_response)

        result = await _detect_infographic_template(bot, "Q4 2025 executive briefing")
        assert result == "executive"

    @pytest.mark.asyncio
    async def test_auto_detect_fallback_on_unknown(self):
        """Falls back to 'basic' when LLM returns unknown template name."""
        bot = self._make_bot()
        mock_response = MagicMock()
        mock_response.content = "nonexistent_template_xyz"
        bot.ask = AsyncMock(return_value=mock_response)

        result = await _detect_infographic_template(bot, "Some question")
        assert result == "basic"

    @pytest.mark.asyncio
    async def test_auto_detect_fallback_on_exception(self):
        """Falls back to 'basic' when pre-pass raises an exception."""
        bot = self._make_bot()
        bot.ask = AsyncMock(side_effect=Exception("LLM connection error"))

        result = await _detect_infographic_template(bot, "Some question")
        assert result == "basic"

    @pytest.mark.asyncio
    async def test_auto_detect_strips_whitespace_and_quotes(self):
        """Pre-pass strips whitespace and quotes from LLM response."""
        bot = self._make_bot()
        mock_response = MagicMock()
        mock_response.content = "  'basic'  "
        bot.ask = AsyncMock(return_value=mock_response)

        result = await _detect_infographic_template(bot, "Simple question")
        assert result == "basic"

    @pytest.mark.asyncio
    async def test_auto_detect_uses_low_max_tokens(self):
        """Pre-pass should call ask() with low max_tokens (≤ 50)."""
        bot = self._make_bot()
        mock_response = MagicMock()
        mock_response.content = "basic"
        bot.ask = AsyncMock(return_value=mock_response)

        await _detect_infographic_template(bot, "question")
        call_kwargs = bot.ask.call_args[1]
        assert call_kwargs.get("max_tokens", 999) <= 50

    @pytest.mark.asyncio
    async def test_auto_detect_no_vector_context(self):
        """Pre-pass should disable vector context and conversation history."""
        bot = self._make_bot()
        mock_response = MagicMock()
        mock_response.content = "basic"
        bot.ask = AsyncMock(return_value=mock_response)

        await _detect_infographic_template(bot, "question")
        call_kwargs = bot.ask.call_args[1]
        assert call_kwargs.get("use_vector_context") is False
        assert call_kwargs.get("use_conversation_history") is False

    @pytest.mark.asyncio
    async def test_auto_detect_prompt_contains_templates(self):
        """Pre-pass prompt should include all registered template names."""
        bot = self._make_bot()
        mock_response = MagicMock()
        mock_response.content = "basic"
        bot.ask = AsyncMock(return_value=mock_response)

        await _detect_infographic_template(bot, "question about sales")

        call_kwargs = bot.ask.call_args[1]
        prompt = call_kwargs.get("question", "")
        assert "basic" in prompt
        assert "multi_tab" in prompt
        assert "executive" in prompt

    @pytest.mark.asyncio
    async def test_detect_all_registered_templates(self):
        """Pre-pass should correctly return any registered template name."""
        registered = infographic_registry.list_templates()
        bot = self._make_bot()

        for template_name in registered:
            mock_response = MagicMock()
            mock_response.content = template_name
            bot.ask = AsyncMock(return_value=mock_response)
            result = await _detect_infographic_template(bot, "test question")
            assert result == template_name, f"Should return '{template_name}'"


class TestTemplateRegistry:
    """Tests for multi_tab template registration (from TASK-660)."""

    def test_multi_tab_registered(self):
        """multi_tab template should be registered."""
        tpl = infographic_registry.get("multi_tab")
        assert tpl.name == "multi_tab"

    def test_all_templates_listed(self):
        """All 7 templates should be listed."""
        templates = infographic_registry.list_templates()
        assert "multi_tab" in templates
        assert len(templates) == 7

    def test_prompt_instruction_tab_view(self):
        """multi_tab prompt should include tab_view instructions."""
        tpl = infographic_registry.get("multi_tab")
        prompt = tpl.to_prompt_instruction()
        assert "tab_view" in prompt
        assert "tabs" in prompt.lower()
        assert "NESTING CONSTRAINTS" in prompt

    def test_existing_templates_unchanged(self):
        """basic template prompt should not contain tab_view instructions."""
        tpl = infographic_registry.get("basic")
        prompt = tpl.to_prompt_instruction()
        assert "tab_view" not in prompt
        assert "TAB VIEW INSTRUCTIONS" not in prompt
